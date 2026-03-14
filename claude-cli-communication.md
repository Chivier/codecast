# 如何与 Claude CLI 进程通信：经验总结

## 结论先行

与 Claude CLI 通信有两种主流方式：

| 方式 | 代表项目 | 核心机制 | 适用场景 |
|------|---------|---------|---------|
| **Claude Agent SDK** | CodePilot | SDK 封装 subprocess，stdin/stdout 双向 JSON 流 | 推荐方式，功能完整 |
| **单次 spawn + stdout 解析** | 本项目 (remote-claudecode) | 每次命令 spawn 新进程，`--print` 模式，只读 stdout | 简单但功能受限 |

**推荐方案：使用 Claude Agent SDK (`@anthropic-ai/claude-agent-sdk`)**

---

## 方式一：Claude Agent SDK（CodePilot 的做法）

### 核心原理

SDK 将 Claude CLI 作为**长驻子进程**启动，通过 **stdin/stdout JSON-lines 协议**双向通信：

```
你的应用 ──stdin(JSON)──► Claude CLI 子进程 ──stdout(JSON)──► 你的应用
                              ↑
                         保持运行，持有会话状态
```

### 关键代码模式

```typescript
import { Claude } from '@anthropic-ai/claude-agent-sdk';

// 创建客户端（底层 spawn claude 子进程）
const client = new Claude({
  // CLI 启动参数
  inputFormat: 'stream-json',
  outputFormat: 'stream-json',
  includePartialMessages: true,
});

// 发送消息并流式接收
const conversation = client.startConversation({
  prompt: "帮我写一个函数",
  systemPrompt: "你是一个代码助手",
  // 可选：恢复之前的会话
  sessionId: previousSessionId,
});

for await (const message of conversation) {
  switch (message.type) {
    case 'assistant':
      // 助手回复（可能包含 tool_use）
      break;
    case 'stream_event':
      // 实时文本增量
      break;
    case 'tool_progress':
      // 工具执行进度
      break;
    case 'result':
      // 完成，包含 token 用量
      break;
  }
}
```

### CLI 启动参数

```bash
claude --input-format stream-json --output-format stream-json --include-partial-messages
```

- `--input-format stream-json`：stdin 接受 JSON 输入（而非交互式终端）
- `--output-format stream-json`：stdout 输出 JSON-lines 流
- `--include-partial-messages`：包含部分消息（用于实时流式显示）

### 通信协议

**发送消息（写入 stdin）：**
```json
{"type": "user_message", "content": "帮我写一个排序函数"}
```

**接收消息（从 stdout 逐行读取）：**
```json
{"type": "assistant", "message": {"role": "assistant", "content": [...]}}
{"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"text": "..."}}}
{"type": "tool_progress", "tool_name": "file_write", "status": "running"}
{"type": "result", "usage": {"input_tokens": 1234, "output_tokens": 567}}
```

### 优势

1. **会话保持**：子进程持续运行，上下文不丢失
2. **双向通信**：可以中途发送新消息、中断、恢复
3. **权限回调**：SDK 支持工具执行前的权限确认
4. **会话恢复**：通过 `sessionId` 恢复之前的对话
5. **MCP 支持**：可以传入 MCP server 配置
6. **官方维护**：Anthropic 官方 SDK，与 CLI 版本同步更新

---

## 方式二：单次 spawn + stdout（本项目的做法）

### 核心原理

每次用户发送消息，spawn 一个新的 CLI 进程，用 `--print` 模式执行单次命令：

```
用户消息 → spawn claude --print "消息" --output-format stream-json
                              ↓
         逐行读取 stdout JSON → 流式返回给前端
                              ↓
                     进程退出，会话结束
```

### 关键代码（broker/src/session.rs）

```rust
let child = Command::new("claude")
    .args(&["--print", &command, "--output-format", "stream-json", "--verbose"])
    .current_dir(cwd)
    .stdout(Stdio::piped())
    .stderr(Stdio::piped())
    .stdin(Stdio::null())     // ← 关键：stdin 关闭，无法追加输入
    .spawn()?;

// 逐行读取 stdout
let reader = BufReader::new(child.stdout.take().unwrap());
while let Some(line) = reader.lines().next_line().await? {
    let json: Value = serde_json::from_str(&line)?;
    // 发送给前端
    ws_sender.send(BrokerResponse::ProviderMessage { data: json }).await;
}
// 等待进程退出
let exit_code = child.wait().await?;
```

### 局限性

1. **无会话保持**：每次命令都是新进程，上下文靠 `--resume` 参数勉强维持
2. **单向通信**：stdin 关闭，无法中途发送追加消息
3. **无权限交互**：`--print` 模式下 CLI 不会请求权限确认
4. **进程开销大**：每个消息都 spawn 新进程，初始化成本高（~50K tokens 上下文加载）
5. **会话恢复脆弱**：依赖 CLI 内部的 session ID 机制，容易断裂

---

## 架构对比

```
┌─────────────────────────────────────────────────────┐
│ CodePilot (SDK 方式)                                  │
│                                                       │
│  Electron App                                         │
│    └─ claude-agent-sdk                                │
│         └─ spawn claude CLI (长驻)                     │
│              ├─ stdin  ← JSON 消息                     │
│              └─ stdout → JSON 流式响应                  │
│                                                       │
│  特点：一个进程处理整个会话                                │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ remote-claudecode (spawn 方式)                        │
│                                                       │
│  React Frontend                                       │
│    └─ WebSocket → Rust Backend                        │
│         └─ WebSocket → Rust Broker                    │
│              └─ spawn claude --print (每次新进程)       │
│                   └─ stdout → JSON 流式响应            │
│                                                       │
│  特点：三层转发，每消息新进程                              │
└─────────────────────────────────────────────────────┘
```

---

## 实践建议

### 如果重新开始，应该这样做：

#### 1. 使用 Claude Agent SDK

```bash
npm install @anthropic-ai/claude-agent-sdk
```

这是最正确的方式。SDK 封装了所有 subprocess 管理细节。

#### 2. 如果必须自己管理进程

关键参数：
```bash
# 启动长驻进程（双向通信）
claude --input-format stream-json --output-format stream-json --include-partial-messages

# 单次执行（只读输出）
claude --print "你的问题" --output-format stream-json
```

stdin 写入格式：
```json
{"type": "user_message", "content": "你的问题"}
```

stdout 读取：逐行读取，每行是一个完整 JSON 对象。

#### 3. 会话管理

- SDK 自动处理 session ID 和会话恢复
- 手动管理时需要保存 CLI 返回的 `session_id`，下次用 `--resume <id>` 恢复
- 注意：`--resume` 在 `--print` 模式下可用，但上下文加载开销大

#### 4. 其他 CLI 工具的参数对照

| 功能 | Claude | Codex | Gemini | OpenCode |
|------|--------|-------|--------|----------|
| 流式 JSON 输出 | `--output-format stream-json` | `exec --json` | `--output-format stream-json` | `run --format json` |
| 单次执行 | `--print "msg"` | `exec "msg"` | `--prompt "msg"` | `run "msg"` |
| 会话恢复 | `--resume <id>` | `resume <id>` | N/A | `--session <id>` |
| 跳过权限 | `--dangerously-skip-permissions` | `--full-auto` | `--yolo` | N/A |

---

## 本项目的教训

1. **不要重新发明轮子**：Claude Agent SDK 已经解决了进程管理问题，不需要自己写 broker
2. **避免多层转发**：Frontend → Backend → Broker → CLI 四层架构增加了大量复杂度和故障点
3. **stdin 不能关闭**：`stdin: Stdio::null()` 导致无法实现真正的对话式交互
4. **serde 格式要对齐**：Rust 后端的 `#[serde(flatten)]` vs 前端的嵌套 `{options: {...}}` 导致了难调试的 bug
5. **连接不要缓存**：WebSocket 连接缓存导致 stale writer 问题，应该每次新建
6. **Provider 信息要贯穿**：Complete 消息缺少 provider 信息导致前端无法路由响应

---

## Session 管理：Resume、Fork、Plan 模式

### Claude Agent SDK 的 Session API

SDK 提供以下会话管理参数（传给 `query()` 的 `options`）：

```typescript
interface Options {
  // 继续最近的会话（不需要知道 session ID）
  continue: boolean;           // default: false

  // 恢复指定会话（需要 session ID）
  resume: string;              // session ID

  // 恢复到特定消息点
  resumeSessionAt: string;     // message UUID

  // 分叉：基于 resume 的会话创建新分支
  forkSession: boolean;        // default: false

  // 指定 session ID（否则自动生成 UUID）
  sessionId: string;

  // 权限模式（含 plan 模式）
  permissionMode: 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan';

  // 是否持久化会话到磁盘
  persistSession: boolean;     // default: true
}
```

Session 文件存储在：`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`

SDK 还提供列出和读取历史会话的工具函数：

```typescript
// 列出所有会话
const sessions = await listSessions();
// → [{sessionId, summary, lastModified, fileSize, cwd, gitBranch, ...}]

// 读取某个会话的消息记录
const messages = await getSessionMessages(sessionId);
// → [{type: "user"|"assistant", uuid, session_id, message}]
```

### Session ID 如何获取

SDK 在两个消息中返回 `session_id`：

```typescript
// 1. 初始化时的 system 消息
{ type: "system", subtype: "init", session_id: "uuid-xxx", ... }

// 2. 完成时的 result 消息
{ type: "result", subtype: "success", session_id: "uuid-xxx", duration_ms: 1234, ... }
```

---

## 各项目的 Resume/Fork/Plan 实现对比

### 对比总结

| 功能 | CodePilot | Claude-to-IM | claudecode-discord | 本项目 |
|------|-----------|-------------|-------------------|--------|
| **Resume** | SDK `resume` 参数 + DB 存储 sdkSessionId + 自动降级 | SDK `sdkSessionId` 参数 + DB 存储 | SDK `resumeSessionId` 参数 + DB 存储 | CLI `--resume` flag，每次新进程 |
| **Fork** | 未实现 | 未实现 | 未实现 | 协议定义了但前端未暴露 |
| **Plan 模式** | `permissionMode: 'plan'` + UI 模式切换 | `/mode plan` 命令切换 | 未实现（用 auto-approve 替代） | `permissionMode` 字段传给 CLI |
| **会话列表** | SQLite 查询 | BridgeStore 接口 | 扫描 `~/.cache/claude/sessions/` | 未实现 |

---

### CodePilot 的 Resume 实现

CodePilot 的 resume 是最完善的，包含**自动降级机制**：

```typescript
// claude-client.ts 核心流程

// 1. 从 DB 读取上次的 SDK session ID
const sdkSessionId = getSession(sessionId)?.sdk_session_id;

// 2. 尝试 resume
if (sdkSessionId) {
  queryOptions.resume = sdkSessionId;
}

// 3. 调用 SDK
let conversation = query({ prompt, options: queryOptions });

// 4. 如果 resume 失败，自动降级为全新会话 + 历史注入
try {
  for await (const msg of conversation) { /* ... */ }
} catch (error) {
  // Resume 失败！清除旧 session ID
  updateSdkSessionId(sessionId, '');
  delete queryOptions.resume;

  // 用历史消息重建上下文
  const promptWithHistory = buildPromptWithHistory(prompt, conversationHistory);

  // 重试为全新会话
  conversation = query({ prompt: promptWithHistory, options: queryOptions });

  // 通知前端
  emitSSE('info', 'Previous session could not be resumed. Starting fresh conversation.');
}

// 5. 成功后保存新的 SDK session ID
if (newSdkSessionId) {
  updateSdkSessionId(sessionId, newSdkSessionId);
}
```

**关键设计**：
- Resume 失败时**不报错**，而是静默降级为新会话
- 降级时用 `buildPromptWithHistory()` 把最近 50 条消息注入 prompt，模拟上下文恢复
- `sdkSessionId` 在错误时清空，防止重复失败

---

### Claude-to-IM 的 Resume 实现

Claude-to-IM 是一个 IM 桥接库，架构更清晰：

```typescript
// conversation-engine.ts

// 1. 从 ChannelBinding 获取上次的 sdkSessionId
const binding = router.resolve(msg.address);

// 2. 传给 LLM Provider
const stream = llm.streamChat({
  prompt: text,
  sessionId,
  sdkSessionId: binding.sdkSessionId || undefined,  // ← Resume 关键
  workingDirectory: binding.workingDirectory,
  permissionMode,
  conversationHistory: historyMsgs,
});

// 3. 流式处理完成后，保存新的 sdkSessionId
if (result.sdkSessionId && !result.hasError) {
  store.updateChannelBinding(binding.id, { sdkSessionId: result.sdkSessionId });
} else if (result.hasError) {
  store.updateChannelBinding(binding.id, { sdkSessionId: '' });  // 出错时清空
}
```

**数据模型**：

```typescript
interface ChannelBinding {
  channelType: 'telegram' | 'discord' | 'feishu' | 'qq';
  chatId: string;
  codepilotSessionId: string;     // 应用层 session
  sdkSessionId: string;            // Claude SDK session（用于 resume）
  workingDirectory: string;
  mode: 'code' | 'plan' | 'ask';  // 权限模式
}
```

---

### claudecode-discord 的 Resume 实现

claudecode-discord 直接用 SDK，最简洁：

```typescript
// session-manager.ts

// 1. 查找已有 session
const existingSession = activeQueries.get(channelId);
const dbSession = getSession(channelId);

// 2. 用 resumeSessionId 恢复
const { queryInstance, sdkSessionId } = await query({
  projectPath: currentProject.path,
  resumeSessionId: existingSession?.sessionId ?? dbSession?.session_id ?? undefined,
  // ...
});

// 3. 保存 session ID
if (sdkSessionId) {
  upsertSession(dbId, channelId, sdkSessionId, 'online');
}
```

**会话列表**（扫描文件系统）：

```typescript
// /sessions 命令
function listSessions(sessionDir: string) {
  return fs.readdirSync(sessionDir)
    .filter(f => f.endsWith('.jsonl'))
    .map(file => ({
      sessionId: file.replace('.jsonl', ''),
      firstMessage: getFirstUserMessage(file),
      timestamp: fs.statSync(file).mtime,
      isActive: sessionId === getActiveSessionId(channelId)
    }))
    .sort((a, b) => b.timestamp - a.timestamp);
}
```

---

### 本项目 (remote-claudecode) 的 Resume 实现

本项目的 resume 是最原始的——每次都 spawn 新进程，用 CLI flag：

```rust
// broker/src/session.rs

// Claude: --resume <session_id>
if let Some(session_id) = options.get("sessionId").and_then(|v| v.as_str()) {
    if options.get("resume").and_then(|v| v.as_bool()).unwrap_or(false) {
        args.push("--resume".to_string());
        args.push(session_id.to_string());
    }
}

// Codex: --session <session_id>
// Gemini: --resume <session_id>
// OpenCode: --session <session_id>
```

**问题**：每次 resume 都要重新 spawn 进程 → 重新加载上下文（~50K tokens）→ 慢且浪费。

---

## Fork 的正确实现方式

**所有三个参考项目都没有实现 fork**，但 Claude Agent SDK 原生支持：

```typescript
// SDK 的 fork 用法
let forkedSessionId: string;

for await (const message of query({
  prompt: "换个方案，用 OAuth2 替代 JWT",
  options: {
    resume: originalSessionId,     // 基于原来的会话
    forkSession: true              // ← 创建分支，不修改原会话
  }
})) {
  if (message.type === "system" && message.subtype === "init") {
    forkedSessionId = message.session_id;  // 新的 session ID，不同于原来的
  }
}
```

**Fork vs Resume 的区别**：

| 操作 | 效果 | 原会话 |
|------|------|--------|
| `resume: id` | 继续原会话，追加新消息 | 被修改 |
| `resume: id` + `forkSession: true` | 基于原会话创建新分支 | 不受影响 |
| `continue: true` | 继续当前目录下最近的会话 | 被修改 |

**Fork 的应用场景**：
- 用户想尝试不同方案但保留原来的对话
- A/B 测试不同的实现路径
- 从某个中间点分叉出多个方向

---

## Plan 模式的实现对比

### SDK 层面

Plan 模式通过 `permissionMode: 'plan'` 启用。在 plan 模式下：
- Claude 只能使用只读工具：`Read`, `Glob`, `Grep`, `WebSearch`, `WebFetch`, `TodoRead`, `TodoWrite`
- 不能执行 `Bash`, `Edit`, `Write` 等修改操作
- 通过 `ExitPlanMode` 工具输出计划内容

```typescript
// Plan 模式调用
for await (const message of query({
  prompt: "分析并规划 auth 模块的重构",
  options: {
    permissionMode: "plan"  // ← Plan 模式
  }
})) {
  // Claude 会探索代码，输出计划，但不执行任何修改
}
```

**ExitPlanMode 工具的输入/输出**：

```typescript
// Claude 调用 ExitPlanMode 时的输入
{
  allowedPrompts?: Array<{
    tool: "Bash";
    prompt: string;  // 描述允许的操作类别
  }>;
}

// 输出
{
  plan: string;              // 计划内容（markdown）
  isAgent: boolean;
  filePath?: string;         // 计划文件路径
  awaitingLeaderApproval?: boolean;
}
```

### CodePilot 的 Plan 模式

CodePilot 在 UI 层面支持 mode 切换：

```typescript
// ChatView.tsx
const [mode, setMode] = useState<'code' | 'plan'>(initialMode || 'code');

// 切换模式
const handleModeChange = async (newMode) => {
  await fetch(`/api/chat/sessions/${sessionId}`, {
    method: 'PATCH', body: JSON.stringify({ mode: newMode })
  });
  setMode(newMode);
};
```

Plan 模式不是通过 SDK 参数传递的，而是**被动检测**：监听 system 消息中的 `permissionMode` 变化。

### Claude-to-IM 的 Plan 模式

最清晰的实现——通过 `/mode` 命令切换：

```typescript
// bridge-manager.ts
case '/mode': {
  if (!validateMode(args)) {
    response = 'Usage: /mode plan|code|ask';
    break;
  }
  router.updateBinding(binding.id, { mode: args });
  response = `Mode set to <b>${args}</b>`;
  break;
}

// 发送消息时映射为 permissionMode
let permissionMode: string;
switch (binding.mode) {
  case 'plan': permissionMode = 'plan'; break;
  case 'ask':  permissionMode = 'default'; break;
  default:     permissionMode = 'acceptEdits'; break;
}
```

三种模式：
- **code** (`acceptEdits`)：自动接受文件编辑，Bash 需确认
- **plan** (`plan`)：只读分析，不执行修改
- **ask** (`default`)：所有工具都需要确认

### claudecode-discord 的权限处理

没有 plan 模式，用 auto-approve 开关替代：

```typescript
// canUseTool 回调
canUseTool: async (tool: Tool) => {
  // 只读工具自动通过
  if (['Read', 'Glob', 'Grep', 'WebSearch', 'WebFetch'].includes(tool.name)) {
    return { approved: true };
  }
  // auto-approve 开启时全部通过
  if (currentProject?.auto_approve) {
    return { approved: true };
  }
  // 否则发 Discord 按钮让用户确认
  const approval = await requestDiscordApproval(tool);
  return { approved: approval };
};
```

---

## 权限请求的交互处理

这是一个重要的实现细节：当 Claude 请求工具权限时，各项目如何让用户交互确认。

### Claude-to-IM（IM 按钮确认）

```typescript
// permission-broker.ts
// 当 Claude 请求权限时，SDK 触发 permission_request 事件
case 'permission_request': {
  const perm = {
    permissionRequestId: data.permissionRequestId,
    toolName: data.toolName,
    toolInput: data.toolInput,
    suggestions: data.suggestions,
  };
  // 立即转发到 IM（不等待，因为流会阻塞直到用户响应）
  onPermissionRequest(perm).catch(console.error);
}
```

用户在 Telegram/Discord 中点击按钮回复 → `/perm allow|deny <id>` → SDK 继续执行。

### claudecode-discord（Discord 按钮）

```typescript
// 发送带按钮的 embed
channel.send({
  embeds: [toolApprovalEmbed(tool)],
  components: [approveButton(), denyButton()]
});

// 等待用户点击（5 分钟超时）
message.awaitMessageComponent({ time: 300000 })
  .then(interaction => {
    pendingApprovals.get(requestId)?.(interaction.customId === 'approve');
  })
  .catch(() => {
    pendingApprovals.get(requestId)?.(false);  // 超时自动拒绝
  });
```

---

## 推荐的 Session 管理实践

### 1. Session ID 存储

```
应用层 Session ID (你的 DB)  ←→  SDK Session ID (Claude CLI 内部)
          1:1 映射，但生命周期不同
```

- 应用层 Session ID：你自己管理，永久有效
- SDK Session ID：从 `system.init` 消息获取，可能因 resume 失败而失效

### 2. Resume 必须有降级策略

```typescript
async function sendMessage(prompt, sdkSessionId, history) {
  try {
    // 先尝试 resume
    return await queryWithResume(prompt, sdkSessionId);
  } catch {
    // resume 失败 → 清除旧 ID + 注入历史 + 新会话
    clearSdkSessionId();
    const enrichedPrompt = prependHistory(prompt, history);
    return await queryFresh(enrichedPrompt);
  }
}
```

### 3. Fork 暂时可以不实现

三个参考项目都没有实现 fork。如果需要，SDK 已经原生支持，加一个 `forkSession: true` 即可。

### 4. Plan 模式建议用 `/mode` 命令切换

Claude-to-IM 的 `/mode plan|code|ask` 模式是最好的 UX 设计——简单、明确、用户可控。

---

## 参考链接

- [Claude Agent SDK - TypeScript](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk)
- [CodePilot 项目](https://github.com/op7418/CodePilot)
- [Claude-to-IM 项目](https://github.com/op7418/Claude-to-IM)
- [claudecode-discord 项目](https://github.com/chadingTV/claudecode-discord)
- [Claude CLI 文档](https://docs.anthropic.com/en/docs/claude-code)
