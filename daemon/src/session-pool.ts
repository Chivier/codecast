import { ChildProcess, spawn } from "child_process";
import { createInterface, Interface as ReadlineInterface } from "readline";
import { v4 as uuidv4 } from "uuid";
import { existsSync } from "fs";
import {
  ManagedSession,
  SessionStatus,
  PermissionMode,
  StreamEvent,
  SessionInfo,
  ClaudeStdinMessage,
  ClaudeStdoutMessage,
  modeToCliFlag,
} from "./types";
import { MessageQueue } from "./message-queue";

interface InternalSession extends ManagedSession {
  process: ChildProcess | null;
  stdin: NodeJS.WritableStream | null;
  stdoutReader: ReadlineInterface | null;
  queue: MessageQueue;
  /** Listeners waiting for stream events */
  streamListeners: Set<(event: StreamEvent) => void>;
  /** Whether we're currently processing a message */
  processing: boolean;
}

/**
 * SessionPool manages multiple Claude CLI long-lived processes.
 *
 * Key design (from claude-cli-communication.md lessons):
 * - Uses Claude CLI with --input-format stream-json --output-format stream-json
 * - Keeps stdin OPEN for bidirectional communication (lesson #3: never close stdin)
 * - One long-lived process per session (lesson #1: don't spawn per message)
 */
export class SessionPool {
  private sessions: Map<string, InternalSession> = new Map();

  /**
   * Create a new session: spawn a Claude CLI process at the given path
   */
  async create(path: string, mode: PermissionMode = "auto"): Promise<string> {
    // Validate path exists
    if (!existsSync(path)) {
      throw new Error(`Path does not exist: ${path}`);
    }

    const sessionId = uuidv4();

    // Build CLI arguments
    const args = [
      "--input-format",
      "stream-json",
      "--output-format",
      "stream-json",
      "--include-partial-messages",
      "--verbose",
      ...modeToCliFlag(mode),
    ];

    console.log(`[SessionPool] Creating session ${sessionId} at ${path}`);
    console.log(`[SessionPool] Command: claude ${args.join(" ")}`);

    // Spawn Claude CLI as long-lived process
    const child = spawn("claude", args, {
      cwd: path,
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        // Ensure Claude knows it's not in a TTY
        TERM: "dumb",
      },
    });

    const session: InternalSession = {
      sessionId,
      path,
      mode,
      status: "idle",
      sdkSessionId: null,
      createdAt: new Date(),
      lastActivityAt: new Date(),
      process: child,
      stdin: child.stdin,
      stdoutReader: null,
      queue: new MessageQueue(),
      streamListeners: new Set(),
      processing: false,
    };

    // Set up stdout line reader
    if (child.stdout) {
      session.stdoutReader = createInterface({
        input: child.stdout,
        crlfDelay: Infinity,
      });

      session.stdoutReader.on("line", (line: string) => {
        this.handleStdoutLine(sessionId, line);
      });
    }

    // Handle stderr (log warnings/errors)
    if (child.stderr) {
      const stderrReader = createInterface({
        input: child.stderr,
        crlfDelay: Infinity,
      });
      stderrReader.on("line", (line: string) => {
        console.error(`[Session ${sessionId}] stderr: ${line}`);
      });
    }

    // Handle process exit
    child.on("exit", (code, signal) => {
      console.log(
        `[Session ${sessionId}] Process exited: code=${code}, signal=${signal}`
      );
      session.status = "error";
      session.process = null;
      session.stdin = null;

      // Notify all listeners of the exit
      const exitEvent: StreamEvent = {
        type: "error",
        message: `Claude process exited (code=${code}, signal=${signal})`,
      };
      this.emitEvent(sessionId, exitEvent);
    });

    child.on("error", (err) => {
      console.error(`[Session ${sessionId}] Process error:`, err);
      session.status = "error";

      const errorEvent: StreamEvent = {
        type: "error",
        message: `Claude process error: ${err.message}`,
      };
      this.emitEvent(sessionId, errorEvent);
    });

    this.sessions.set(sessionId, session);

    // Wait briefly for the process to start and check it's alive
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (session.status === "error") {
      throw new Error("Claude process failed to start");
    }

    return sessionId;
  }

  /**
   * Send a message to a session's Claude process.
   * Returns an async iterable of stream events.
   */
  async *send(
    sessionId: string,
    message: string
  ): AsyncGenerator<StreamEvent, void, unknown> {
    const session = this.getSession(sessionId);

    // If Claude is busy, queue the message
    if (session.processing) {
      const position = session.queue.enqueueUser(message);
      yield { type: "queued", position };
      return;
    }

    // Process this message
    yield* this.processMessage(session, message);
  }

  /**
   * Internal: process a single message through Claude
   */
  private async *processMessage(
    session: InternalSession,
    message: string
  ): AsyncGenerator<StreamEvent, void, unknown> {
    if (!session.stdin || !session.process) {
      throw new Error("Session process is not running");
    }

    session.processing = true;
    session.status = "busy";
    session.lastActivityAt = new Date();

    // Create a promise-based event queue for this request
    const eventQueue: StreamEvent[] = [];
    let resolveWait: (() => void) | null = null;
    let done = false;

    const listener = (event: StreamEvent) => {
      eventQueue.push(event);
      if (resolveWait) {
        resolveWait();
        resolveWait = null;
      }
      if (event.type === "result" || event.type === "error") {
        done = true;
      }
    };

    session.streamListeners.add(listener);

    try {
      // Write message to Claude's stdin
      const stdinMsg: ClaudeStdinMessage = {
        type: "user_message",
        content: message,
      };
      session.stdin.write(JSON.stringify(stdinMsg) + "\n");

      // Yield events as they arrive
      while (!done) {
        if (eventQueue.length > 0) {
          const event = eventQueue.shift()!;

          // Capture SDK session ID from result/system messages
          if (event.session_id) {
            session.sdkSessionId = event.session_id;
          }

          yield event;

          if (event.type === "result" || event.type === "error") {
            break;
          }
        } else {
          // Wait for next event
          await new Promise<void>((resolve) => {
            resolveWait = resolve;
          });
        }
      }
    } finally {
      session.streamListeners.delete(listener);
      session.processing = false;
      session.status =
        session.process && !session.process.killed ? "idle" : "error";

      // Process next queued message if any
      if (session.queue.hasUserPending() && session.status === "idle") {
        const next = session.queue.dequeueUser();
        if (next) {
          // Process in background - don't yield from here
          this.processQueuedMessage(session, next.message);
        }
      }
    }
  }

  /**
   * Process a queued message in the background.
   * Events go to the queue's response buffer for later retrieval.
   */
  private async processQueuedMessage(
    session: InternalSession,
    message: string
  ): Promise<void> {
    try {
      const gen = this.processMessage(session, message);
      for await (const event of gen) {
        // If client is disconnected, buffer the response
        if (!session.queue.clientConnected) {
          session.queue.bufferResponse(event);
        }
        // Otherwise events go to stream listeners (if any are attached)
      }
    } catch (err) {
      console.error(
        `[Session ${session.sessionId}] Error processing queued message:`,
        err
      );
    }
  }

  /**
   * Handle a line from Claude CLI's stdout
   */
  private handleStdoutLine(sessionId: string, line: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    let parsed: ClaudeStdoutMessage;
    try {
      parsed = JSON.parse(line);
    } catch {
      // Not JSON, log it
      console.log(`[Session ${sessionId}] non-JSON stdout: ${line}`);
      return;
    }

    // Convert Claude CLI message to our StreamEvent format
    const event = this.convertToStreamEvent(parsed);
    this.emitEvent(sessionId, event);
  }

  /**
   * Convert Claude CLI stdout JSON to our StreamEvent format
   */
  private convertToStreamEvent(msg: ClaudeStdoutMessage): StreamEvent {
    switch (msg.type) {
      case "system":
        return {
          type: "system",
          subtype: msg.subtype,
          session_id: msg.session_id,
          raw: msg,
        };

      case "assistant":
        // Extract text content from assistant message
        if (msg.message?.content) {
          const textBlocks = msg.message.content.filter(
            (b) => b.type === "text"
          );
          const toolBlocks = msg.message.content.filter(
            (b) => b.type === "tool_use"
          );

          if (toolBlocks.length > 0) {
            return {
              type: "tool_use",
              tool: toolBlocks[0].name,
              input: toolBlocks[0].input,
              raw: msg,
            };
          }

          if (textBlocks.length > 0) {
            return {
              type: "text",
              content: textBlocks.map((b) => b.text).join(""),
              raw: msg,
            };
          }
        }
        return { type: "text", content: "", raw: msg };

      case "stream_event":
        // Handle streaming deltas
        if (msg.event?.type === "content_block_delta") {
          if (msg.event.delta?.text) {
            return {
              type: "partial",
              content: msg.event.delta.text,
            };
          }
          if (msg.event.delta?.partial_json) {
            return {
              type: "partial",
              content: msg.event.delta.partial_json,
            };
          }
        }
        if (msg.event?.type === "content_block_start") {
          if (msg.event.content_block?.type === "tool_use") {
            return {
              type: "tool_use",
              tool: msg.event.content_block.name,
              raw: msg,
            };
          }
        }
        return { type: "partial", content: "", raw: msg };

      case "tool_progress":
        return {
          type: "tool_use",
          tool: msg.tool_name,
          message: msg.status,
          raw: msg,
        };

      case "result":
        return {
          type: "result",
          session_id: msg.session_id,
          raw: msg,
        };

      default:
        return { type: "system", raw: msg };
    }
  }

  /**
   * Emit a stream event to all listeners of a session
   */
  private emitEvent(sessionId: string, event: StreamEvent): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    for (const listener of session.streamListeners) {
      try {
        listener(event);
      } catch (err) {
        console.error(
          `[Session ${sessionId}] Error in stream listener:`,
          err
        );
      }
    }
  }

  /**
   * Resume a session with an existing SDK session ID.
   * Implements CodePilot-style fallback strategy.
   */
  async resume(
    sessionId: string,
    sdkSessionId?: string
  ): Promise<{ ok: boolean; fallback: boolean; newSessionId?: string }> {
    const session = this.sessions.get(sessionId);

    if (session && session.process && session.status !== "error") {
      // Session process is still alive, just reconnect
      session.queue.onClientReconnect();
      return { ok: true, fallback: false };
    }

    // Process is dead, need to restart
    // Try to resume with SDK session ID
    if (session) {
      const path = session.path;
      const mode = session.mode;
      const effectiveSdkId = sdkSessionId || session.sdkSessionId;

      // Clean up old session
      this.sessions.delete(sessionId);

      // Create new process with --resume flag
      const args = [
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        ...modeToCliFlag(mode),
      ];

      if (effectiveSdkId) {
        args.push("--resume", effectiveSdkId);
      }

      try {
        const child = spawn("claude", args, {
          cwd: path,
          stdio: ["pipe", "pipe", "pipe"],
          env: { ...process.env, TERM: "dumb" },
        });

        const newSession: InternalSession = {
          sessionId,
          path,
          mode,
          status: "idle",
          sdkSessionId: effectiveSdkId,
          createdAt: session.createdAt,
          lastActivityAt: new Date(),
          process: child,
          stdin: child.stdin,
          stdoutReader: null,
          queue: new MessageQueue(),
          streamListeners: new Set(),
          processing: false,
        };

        if (child.stdout) {
          newSession.stdoutReader = createInterface({
            input: child.stdout,
            crlfDelay: Infinity,
          });
          newSession.stdoutReader.on("line", (line: string) => {
            this.handleStdoutLine(sessionId, line);
          });
        }

        if (child.stderr) {
          const stderrReader = createInterface({
            input: child.stderr,
            crlfDelay: Infinity,
          });
          stderrReader.on("line", (line: string) => {
            console.error(`[Session ${sessionId}] stderr: ${line}`);
          });
        }

        child.on("exit", (code, signal) => {
          console.log(
            `[Session ${sessionId}] Process exited: code=${code}, signal=${signal}`
          );
          newSession.status = "error";
          newSession.process = null;
          newSession.stdin = null;
          this.emitEvent(sessionId, {
            type: "error",
            message: `Claude process exited (code=${code}, signal=${signal})`,
          });
        });

        child.on("error", (err) => {
          console.error(`[Session ${sessionId}] Process error:`, err);
          newSession.status = "error";
          this.emitEvent(sessionId, {
            type: "error",
            message: `Claude process error: ${err.message}`,
          });
        });

        this.sessions.set(sessionId, newSession);

        await new Promise((resolve) => setTimeout(resolve, 500));
        if (newSession.status === "error") {
          throw new Error("Resume failed - Claude process died");
        }

        return { ok: true, fallback: false };
      } catch (err) {
        // Resume failed - fallback: start fresh session
        console.warn(
          `[Session ${sessionId}] Resume failed, starting fresh:`,
          err
        );
        try {
          const newId = await this.create(path, mode);
          // Move session to keep the same sessionId
          const freshSession = this.sessions.get(newId)!;
          this.sessions.delete(newId);
          freshSession.sessionId = sessionId;
          freshSession.sdkSessionId = null;
          this.sessions.set(sessionId, freshSession);
          return { ok: true, fallback: true, newSessionId: sessionId };
        } catch (createErr) {
          console.error(
            `[Session ${sessionId}] Fallback create also failed:`,
            createErr
          );
          return { ok: false, fallback: true };
        }
      }
    }

    return { ok: false, fallback: false };
  }

  /**
   * Destroy a session: kill the Claude process and clean up
   */
  async destroy(sessionId: string): Promise<boolean> {
    const session = this.sessions.get(sessionId);
    if (!session) return false;

    // Close stdin gracefully first
    if (session.stdin) {
      try {
        session.stdin.end();
      } catch {
        // ignore
      }
    }

    // Kill process
    if (session.process && !session.process.killed) {
      session.process.kill("SIGTERM");

      // Force kill after 5 seconds
      setTimeout(() => {
        if (session.process && !session.process.killed) {
          session.process.kill("SIGKILL");
        }
      }, 5000);
    }

    // Clean up readline
    if (session.stdoutReader) {
      session.stdoutReader.close();
    }

    session.status = "destroyed";
    session.streamListeners.clear();
    session.queue.clear();

    this.sessions.delete(sessionId);
    console.log(`[SessionPool] Destroyed session ${sessionId}`);
    return true;
  }

  /**
   * Set the permission mode for a session.
   * Note: this requires restarting the Claude process since mode is a CLI flag.
   */
  async setMode(
    sessionId: string,
    mode: PermissionMode
  ): Promise<boolean> {
    const session = this.getSession(sessionId);
    const oldMode = session.mode;

    if (oldMode === mode) return true;

    // Need to restart the process with new flags
    const path = session.path;
    const sdkSessionId = session.sdkSessionId;

    await this.destroy(sessionId);

    // Recreate with new mode
    const args = [
      "--input-format",
      "stream-json",
      "--output-format",
      "stream-json",
      "--include-partial-messages",
      "--verbose",
      ...modeToCliFlag(mode),
    ];

    if (sdkSessionId) {
      args.push("--resume", sdkSessionId);
    }

    const child = spawn("claude", args, {
      cwd: path,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, TERM: "dumb" },
    });

    const newSession: InternalSession = {
      sessionId,
      path,
      mode,
      status: "idle",
      sdkSessionId,
      createdAt: new Date(),
      lastActivityAt: new Date(),
      process: child,
      stdin: child.stdin,
      stdoutReader: null,
      queue: new MessageQueue(),
      streamListeners: new Set(),
      processing: false,
    };

    if (child.stdout) {
      newSession.stdoutReader = createInterface({
        input: child.stdout,
        crlfDelay: Infinity,
      });
      newSession.stdoutReader.on("line", (line: string) => {
        this.handleStdoutLine(sessionId, line);
      });
    }

    if (child.stderr) {
      const stderrReader = createInterface({
        input: child.stderr,
        crlfDelay: Infinity,
      });
      stderrReader.on("line", (line: string) => {
        console.error(`[Session ${sessionId}] stderr: ${line}`);
      });
    }

    child.on("exit", (code, signal) => {
      newSession.status = "error";
      newSession.process = null;
      newSession.stdin = null;
      this.emitEvent(sessionId, {
        type: "error",
        message: `Claude process exited (code=${code}, signal=${signal})`,
      });
    });

    child.on("error", (err) => {
      newSession.status = "error";
      this.emitEvent(sessionId, {
        type: "error",
        message: `Claude process error: ${err.message}`,
      });
    });

    this.sessions.set(sessionId, newSession);

    await new Promise((resolve) => setTimeout(resolve, 500));
    return newSession.status !== "error";
  }

  /**
   * Get session info (without internal process details)
   */
  getSessionInfo(sessionId: string): SessionInfo {
    const session = this.getSession(sessionId);
    return {
      sessionId: session.sessionId,
      path: session.path,
      status: session.status,
      mode: session.mode,
      sdkSessionId: session.sdkSessionId,
      createdAt: session.createdAt.toISOString(),
      lastActivityAt: session.lastActivityAt.toISOString(),
    };
  }

  /**
   * List all sessions
   */
  listSessions(): SessionInfo[] {
    return Array.from(this.sessions.values()).map((s) => ({
      sessionId: s.sessionId,
      path: s.path,
      status: s.status,
      mode: s.mode,
      sdkSessionId: s.sdkSessionId,
      createdAt: s.createdAt.toISOString(),
      lastActivityAt: s.lastActivityAt.toISOString(),
    }));
  }

  /**
   * Mark client as disconnected for a session (for MQ buffering)
   */
  clientDisconnect(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.queue.onClientDisconnect();
    }
  }

  /**
   * Mark client as reconnected, return buffered events
   */
  clientReconnect(sessionId: string): StreamEvent[] {
    const session = this.sessions.get(sessionId);
    if (session) {
      return session.queue.onClientReconnect();
    }
    return [];
  }

  /**
   * Get queue stats for a session
   */
  getQueueStats(
    sessionId: string
  ): { userPending: number; responsePending: number; clientConnected: boolean } | null {
    const session = this.sessions.get(sessionId);
    if (!session) return null;
    return session.queue.stats();
  }

  /**
   * Destroy all sessions (cleanup on shutdown)
   */
  async destroyAll(): Promise<void> {
    const sessionIds = Array.from(this.sessions.keys());
    await Promise.all(sessionIds.map((id) => this.destroy(id)));
  }

  /**
   * Get a session by ID, throwing if not found
   */
  private getSession(sessionId: string): InternalSession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session not found: ${sessionId}`);
    }
    return session;
  }
}
