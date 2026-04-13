# Hooks 系统 — 深度研究笔记

> 来源: src/utils/hooks.js + src/services/tools/toolHooks.ts + src/utils/hooks/postSamplingHooks.ts + s08

---

## Hooks 设计哲学

**核心思想**：从外部扩展 Agent 行为，无需修改主循环代码。

Hooks 是固定扩展点（Extension Points）：
- 在特定生命周期事件触发自定义 Shell 脚本
- 通过 exit code 协议与主循环通信
- 可以审计、通知、阻止、注入

---

## 6种 Hook 事件类型（来自源码）

### 对外暴露（可配置）:

| Hook | 触发时机 | 可阻止? | 典型用途 |
|------|---------|--------|---------|
| `PreToolUse` | 工具执行前 | 是（exit 1 / JSON block） | 安全检查、日志 |
| `PostToolUse` | 工具执行后 | 否 | 后处理、格式化 |
| `Stop` | 模型最终输出时 | 否 | 通知、自动保存 |
| `TaskCompleted` | 任务完成时 | 否 | 结果回调 |
| `TeammateIdle` | 队友进入空闲 | 否 | 资源回收 |
| `UserPromptSubmit` | 用户消息进入时 | 否 | 输入预处理 |
| `NotifyAfterTimeout` | 超时后通知 | 否 | 长任务提醒 |

### 内部专用（不可外部配置）:

| Hook | 触发时机 | 用途 |
|------|---------|------|
| `PostSampling` | 模型采样完成后（内部） | AutoDream、PromptSuggestion、内部分析 |

---

## Hook Exit Code 协议

```bash
# PreToolUse:
exit 0  → 继续执行工具（静默通过）
exit 1  → 阻止工具执行，stderr 作为错误原因返回
exit 2  → 将 stderr 注入对话，工具仍然执行

# PostToolUse:
exit 0  → 继续正常
exit 2  → 将 stderr 追加到工具结果

# 高级阻止（JSON 格式，PreToolUse）:
echo '{"decision":"block","reason":"安全策略禁止此操作"}' | exit 0
```

---

## Hook 附件类型（toolHooks.ts）

```typescript
type HookAttachment =
  | { type: 'hook_cancelled' }           // Hook 取消了工具执行
  | { type: 'hook_blocking_error', message: string }  // Hook 返回阻止错误
  | { type: 'hook_output', content: string }  // Hook 注入的消息内容
```

---

## Hooks 配置位置

```json
// ~/.claude/settings.json 或 .claude/settings.json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "python /path/to/bash-auditor.py"
      },
      {
        "matcher": "Write",
        "command": "/path/to/lint-check.sh"
      }
    ],
    "PostToolUse": [
      {
        "command": "logger 'Tool used' >> /var/log/claude.log"
      }
    ],
    "Stop": [
      {
        "command": "notify-send 'Claude finished' '$(cat /tmp/last-response.txt)'"
      }
    ]
  }
}
```

---

## Hook 执行环境变量

```bash
HOOK_EVENT=PreToolUse         # 事件类型
HOOK_TOOL_NAME=Bash           # 工具名
HOOK_TOOL_INPUT='{"command":"ls -la"}'  # 工具输入（JSON）
HOOK_TOOL_OUTPUT='...'        # 工具输出（仅PostToolUse）
```

---

## Matcher 规则

```json
{
  "matcher": "Bash"           // 精确匹配工具名
  "matcher": "Bash(git *)"    // 带参数模式匹配
  "matcher": "Write(*)"       // 通配符
  // 无matcher → 匹配所有工具
}
```

---

## AutoDream（PostSampling Hook，内部）

Feature Gate: `TEMPLATES`

```
触发：PostSampling（每次模型采样后）
功能：
  - 分析当前会话上下文
  - 自动生成可能有用的提示建议
  - 通过 PromptSuggestion 注入建议
  - 基于历史模式的 JobClassifier 分类

相关文件: src/services/autoDream/
```

---

## EXTRACT_MEMORIES（PostSampling Hook，内部）

```
触发：模型对话结束后
功能：
  - 分析对话内容提取关键事实
  - 自动写入 Memory Files

相关文件: src/services/extractMemories/
```

---

## Hooks 在完整管道中的位置

```
UserPromptSubmit Hook    ←── 用户输入时（最早）
  │
  ▼
[LLM 推理]
  │
  ▼ PostSampling Hook（内部，模型采样后）
  │
  ▼
[工具调用]
  │
PreToolUse Hook     ←── 工具执行前（可阻止）
  │
  ▼
[工具执行]
  │
PostToolUse Hook    ←── 工具执行后（可追加内容）
  │
  ▼
[LLM 最终输出]
  │
Stop Hook           ←── 模型停止时（最晚）
  │
TaskCompleted Hook  ←── 任务完成时
```

---

## runPostToolUseHooks() 实现细节（toolHooks.ts）

```typescript
async function* runPostToolUseHooks(
  toolResult: ToolResult,
  context: HookContext
): AsyncGenerator<HookAttachment> {
  // 执行所有匹配的 PostToolUse hooks
  for (const hook of getMatchingHooks('PostToolUse', context)) {
    const result = await executeHook(hook, context)
    if (result.exitCode === 2) {
      yield {
        type: 'hook_output',
        content: result.stderr
      }
    }
  }
}
```
