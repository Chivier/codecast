"""
Message Formatter - handles splitting long messages for Discord/Telegram
and formatting various Claude output types.
"""

import re
from typing import Any


def split_message(text: str, max_len: int = 2000) -> list[str]:
    """
    Split a long message into chunks that fit within platform limits.
    Smart splitting: avoids breaking code blocks, prefers paragraph boundaries.

    Args:
        text: The text to split
        max_len: Maximum length per chunk (Discord=2000, Telegram=4096)

    Returns:
        List of message chunks
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Find the best split point within max_len
        split_at = _find_split_point(remaining, max_len)
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")

    return [c for c in chunks if c.strip()]


def _find_split_point(text: str, max_len: int) -> int:
    """Find the best point to split text at, within max_len."""
    segment = text[:max_len]

    # Check if we're inside a code block
    code_blocks = list(re.finditer(r'```', segment))
    if len(code_blocks) % 2 == 1:
        # Odd number of ``` means we're inside a code block
        # Find the last complete code block end before max_len
        last_block_start = code_blocks[-1].start()
        if last_block_start > 200:  # Don't split too early
            return last_block_start

    # Try to split at paragraph boundary (\n\n)
    last_para = segment.rfind("\n\n")
    if last_para > max_len * 0.3:  # At least 30% of the way through
        return last_para + 1

    # Try to split at line boundary (\n)
    last_line = segment.rfind("\n")
    if last_line > max_len * 0.3:
        return last_line + 1

    # Try to split at sentence boundary
    for pattern in [". ", "! ", "? ", "; "]:
        last_sentence = segment.rfind(pattern)
        if last_sentence > max_len * 0.5:
            return last_sentence + 2

    # Try space
    last_space = segment.rfind(" ")
    if last_space > max_len * 0.5:
        return last_space + 1

    # Force split at max_len
    return max_len


def format_tool_use(event: dict[str, Any]) -> str:
    """Format a tool_use event for display in chat."""
    tool = event.get("tool", "unknown")
    input_data = event.get("input")
    message = event.get("message", "")

    if message:
        return f"**[Tool: {tool}]** {message}"

    if input_data:
        input_str = _truncate(str(input_data), 500)
        return f"**[Tool: {tool}]**\n```\n{input_str}\n```"

    return f"**[Tool: {tool}]**"


def format_session_info(session: Any) -> str:
    """Format a session for display."""
    status_icon = {
        "active": "●",
        "detached": "○",
        "destroyed": "✕",
        "idle": "●",
        "busy": "◉",
        "error": "✕",
    }.get(getattr(session, "status", ""), "?")

    if hasattr(session, "channel_id"):
        # Session from SessionRouter
        return (
            f"{status_icon} `{session.daemon_session_id[:8]}...` "
            f"**{session.machine_id}**:`{session.path}` "
            f"[{session.mode}] ({session.status})"
        )
    else:
        # Session info dict from daemon
        sid = session.get("sessionId", "?")[:8]
        return (
            f"{status_icon} `{sid}...` "
            f"**{session.get('path', '?')}** "
            f"[{session.get('mode', '?')}] ({session.get('status', '?')})"
        )


def format_machine_list(machines: list[dict[str, Any]]) -> str:
    """Format machine list for display."""
    if not machines:
        return "No machines configured."

    lines = ["**Machines:**"]
    for m in machines:
        status_icon = "🟢" if m.get("status") == "online" else "🔴"
        daemon_icon = "⚡" if m.get("daemon") == "running" else "💤"
        line = f"{status_icon} **{m['id']}** ({m['host']}) {daemon_icon}"
        if m.get("default_paths"):
            paths = ", ".join(f"`{p}`" for p in m["default_paths"])
            line += f"\n  Paths: {paths}"
        lines.append(line)

    return "\n".join(lines)


def format_session_list(sessions: list[Any]) -> str:
    """Format session list for display."""
    if not sessions:
        return "No sessions found."

    lines = ["**Sessions:**"]
    for s in sessions:
        lines.append(format_session_info(s))

    return "\n".join(lines)


def format_error(error: str) -> str:
    """Format an error message."""
    return f"**Error:** {error}"


def format_status(session: Any, queue_stats: dict[str, Any] | None = None) -> str:
    """Format session status for /status command."""
    lines = [
        f"**Session Status**",
        f"Machine: **{session.machine_id}**",
        f"Path: `{session.path}`",
        f"Mode: **{session.mode}**",
        f"Status: **{session.status}**",
        f"Session ID: `{session.daemon_session_id[:12]}...`",
    ]

    if session.sdk_session_id:
        lines.append(f"SDK Session: `{session.sdk_session_id[:12]}...`")

    if queue_stats:
        lines.append(f"Queue: {queue_stats.get('userPending', 0)} pending messages")
        lines.append(f"Buffered: {queue_stats.get('responsePending', 0)} responses")

    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
