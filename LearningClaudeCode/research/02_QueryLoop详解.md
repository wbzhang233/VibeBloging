# QueryLoop 执行引擎详解

> 本文档是可视化 `images/01_QueryLoop执行引擎.html` 的技术脚本。

---

## 一、QueryLoop 是什么

QueryLoop 是 Claude Code 的**核心执行引擎**——所有用户指令、模型推理、工具调用都在这个循环中流转。可以把它类比为 CPU 的指令执行周期（Fetch → Decode → Execute → Writeback），只不过这里的"指令"是 AI 的工具调用。

---

## 二、完整伪代码

```python
# ─── 启动阶段 ───────────────────────────────────────────
def startup():
    load_claude_md()          # 加载项目记忆（CLAUDE.md）
    load_memory_files()       # 加载持久记忆（.claude/memory/）
    build_system_prompt()     # 组装系统提示（项目规范 + 工具定义 + 行为约束）
    connect_mcp_servers()     # 初始化 MCP 连接
    return initial_context

# ─── 主循环 ─────────────────────────────────────────────
def query_loop(user_input: str):
    messages = [system_prompt, {"role": "user", "content": user_input}]

    while True:
        # 1. 模型推理
        response = claude_api(messages, tools=all_tools)

        if response.has_tool_call:
            tool_call = response.tool_calls[0]

            # 2. 权限检查
            permission = check_permissions(tool_call)
            if permission == DENY:
                messages.append({"role": "tool", "content": "Permission denied"})
                continue
            if permission == NEEDS_APPROVAL:
                approved = prompt_user_approval(tool_call)
                if not approved:
                    continue

            # 3. PreToolUse Hooks
            run_hooks("PreToolUse", tool_call)

            # 4. 工具执行
            result = execute_tool(tool_call)

            # 5. PostToolUse Hooks
            run_hooks("PostToolUse", tool_call, result)

            # 6. 结果注入上下文
            messages.append({"role": "tool", "content": result})

            # 7. 上下文压缩检查
            if context_usage_ratio() > 0.70:
                compress_context(messages)

        else:
            # 没有工具调用 → 输出最终结果
            display_output(response.text)
            run_hooks("Stop", response)

            # 等待下一轮用户输入
            user_input = wait_for_input()
            if user_input is None:
                break  # 用户退出（Ctrl+C / /exit）
            messages.append({"role": "user", "content": user_input})
```

---

## 三、状态机图

```
┌─────────────────────────────────────────────────────────────┐
│                     QueryLoop 状态机                         │
│                                                             │
│    START                                                    │
│      ↓                                                      │
│  [INIT]  load_claude_md → load_memory → build_system_prompt │
│      ↓                                                      │
│  [WAIT]  ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   │
│      │ user_input                                       │   │
│      ↓                                                  │   │
│  [REASON] claude_api() → response                       │   │
│      │                                                  │   │
│      ├─── has_tool_call ──→ [PERMISSION_CHECK]          │   │
│      │                           │ DENY                 │   │
│      │                           ↓                      │   │
│      │                      [BLOCKED] ──────────────────┘   │
│      │                           │ APPROVE               │   │
│      │                           ↓                      │   │
│      │                      [PRE_HOOK] run PreToolUse   │   │
│      │                           ↓                      │   │
│      │                      [EXECUTE] tool execution    │   │
│      │                           ↓                      │   │
│      │                      [POST_HOOK] run PostToolUse │   │
│      │                           ↓                      │   │
│      │                      [INJECT] append tool_result │   │
│      │                           ↓                      │   │
│      │                     context > 70%?               │   │
│      │                      ├── YES → [COMPRESS]        │   │
│      │                      └── NO  ──────────────────→ ┘   │
│      │                            back to [REASON]          │
│      │                                                       │
│      └─── no_tool_call ──→ [OUTPUT] display_output          │
│                                 ↓                           │
│                            [STOP_HOOK] run Stop hooks       │
│                                 ↓                           │
│                             WAIT ──────────────────────────→│
└─────────────────────────────────────────────────────────────┘
```

---

## 四、关键设计细节

### 4.1 工具调用是同步阻塞的

每次工具调用都需要完整的模型推理往返（API 调用）：

```
User Input
    ↓
[API Call #1] → model reasons → outputs tool_call(Read, "file.py")
    ↓
Execute Read tool → returns file content
    ↓
[API Call #2] → model reasons → outputs tool_call(Edit, "file.py", ...)
    ↓
Execute Edit tool → returns success
    ↓
[API Call #3] → model reasons → no tool_call → outputs final text
    ↓
Display to User
```

**关键洞见**：一次复杂任务可能触发 10-30+ 次 API 调用，每次都消耗 tokens（这也是为什么 Prompt Cache 如此重要）。

### 4.2 上下文压缩（/compact）

当上下文窗口使用率超过 **70%** 时，Claude Code 自动压缩：

```
压缩策略：
├── 保留：System Prompt（始终在最前，受 Prompt Cache 保护）
├── 保留：最近 N 轮对话（保持近期连贯性）
├── 摘要：中间轮次（LLM 生成摘要替代原始内容）
└── 丢弃：过时的工具调用结果（已被消化的信息）
```

用户也可手动触发：`/compact` 命令。

### 4.3 Hooks 注入点

```
工具调用生命周期中的 5 个 Hook 注入点：

UserPromptSubmit → [用户输入进入循环]
    ↓
PreToolUse → [工具即将执行前]
    ↓
[工具执行]
    ↓
PostToolUse → [工具执行后]
    ↓
Stop → [模型输出最终结果，循环本轮结束]
    ↓
Notification → [需要用户注意时]
```

### 4.4 API 时序图

```
Browser/Terminal
    │
    ├─── User Input ──────────────────────→ Harness
    │                                          │
    │                                     [Build Messages]
    │                                          │
    │                              ┌─── Claude API (Streaming)
    │                              │         │
    │                              │    [Stream tokens...]
    │                              │         │
    │                              │    tool_call detected
    │                              │         │
    │◄──── Display partial text ───┘    [Pause stream]
    │                                          │
    │                                    [Execute Tool]
    │                                          │
    │                                    [Inject result]
    │                                          │
    │                              ┌─── Claude API (Continue)
    │                              │         │
    │◄──── Display final text ─────┘    [Final response]
    │
```

---

## 五、性能特征

| 特征 | 说明 |
|------|------|
| 推理方式 | 流式输出（streaming），边生成边显示 |
| 工具执行 | 同步阻塞，一次一个（除非子 Agent 并行） |
| 上下文复杂度 | O(n²)——每次 API 调用都要发送完整历史 |
| 压缩收益 | /compact 后上下文减少约 60-80%，成本显著降低 |
| Prompt Cache 命中 | System Prompt + CLAUDE.md 通常 >90% 缓存命中 |
