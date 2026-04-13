# Coordinator/Worker 架构 — 深度研究笔记

> 来源: src/coordinator/coordinatorMode.ts + s04/s15/s16/s17 章节

---

## 两种运行模式

### 模式1：单Agent普通模式
- 一个 QueryEngine 实例
- 用户 → Claude → 工具执行 → 响应
- 权限通过交互式对话框

### 模式2：Coordinator/Worker 模式
- `CLAUDE_CODE_COORDINATOR_MODE` 环境变量激活
- Coordinator 作为中枢协调多个 Worker
- Worker 通过 `<task-notification>` XML 接收任务

---

## Coordinator 架构

```
用户输入
  │
  ▼
┌─────────────────────────────────┐
│        COORDINATOR              │
│  (600行+ 专用系统提示)          │
│                                 │
│  isCoordinatorMode() = true     │
│  getCoordinatorSystemPrompt()   │
│  getCoordinatorUserContext()    │
│                                 │
│  制定计划 → 分解任务 → 派发     │
└───────────┬────────────┬────────┘
            │            │
            ▼            ▼
┌───────────────┐  ┌───────────────┐
│   Worker A    │  │   Worker B    │
│  独立上下文   │  │  独立上下文   │
│  有限工具集   │  │  有限工具集   │
│               │  │               │
│ <task-notif>  │  │ <task-notif>  │
│ XML任务接收   │  │ XML任务接收   │
└───────┬───────┘  └───────┬───────┘
        │                  │
        ▼                  ▼
    摘要结果              摘要结果
        │                  │
        └──────┬───────────┘
               ▼
        Coordinator 汇聚
```

---

## task-notification XML 协议

Worker 通过 user-role 消息中的 XML 接收任务：

```xml
<task-notification>
  <task-id>task_001</task-id>
  <instructions>
    分析 src/auth/ 目录下的所有文件并生成安全审查报告
  </instructions>
  <allowed-tools>Read, Grep, Glob, WebFetch</allowed-tools>
  <output-format>markdown</output-format>
</task-notification>
```

---

## INTERNAL_WORKER_TOOLS（Worker专用工具）

```
TeamCreate      → 创建团队成员
TeamDelete      → 删除团队成员
SendMessage     → 向队友发消息
SyntheticOutput → 向Coordinator输出结果（专用返回通道）
```

---

## scratchpad 共享知识目录

Feature Gate: `tengu_scratch`

```
scratchpadDir: shared cross-worker knowledge directory
  ↳ 多个Worker可以读写同一目录
  ↳ 知识共享，避免重复工作
  ↳ Coordinator可以注入 scratchpad context
```

---

## 三种Agent类型

### Subagent（一次性子代理，s04）
```
特点：
  - 一次性派发，完成返回摘要，然后销毁
  - 无独立身份，无跨会话记忆
  - Agent工具（原名：Task工具）派生
  - 独立上下文窗口

Explore子代理:
  - 仅只读工具：Glob/Grep/Read/WebFetch/WebSearch
  - 用于快速代码库探索

Plan子代理:
  - 仅只读工具 + 规划工具
  - 用于方案设计

Execute子代理:
  - 全工具权限
  - 用于实际执行
```

### Teammate（持久队友，s15）
```
特点：
  - 长期存活，有独立身份和角色
  - JSONL收件箱（.team/inbox/name.jsonl）
  - 每次LLM调用前检查收件箱
  - 状态：spawn → WORKING → IDLE → WORKING → SHUTDOWN
  - 存储：.team/config.json（团队花名册）

通信机制：
  MessageBus.send(sender, to, content) → 追加到JSONL文件
  MessageBus.read_inbox(name) → 读取并清空（drain）
```

### Autonomous Agent（自主代理，s17）
```
特点：
  - 可以自主认领任务，无需人工派发
  - 基于任务板（Task Board）的协调机制
  - WorktreeRecord：每个自主代理有独立执行通道
```

---

## 子代理独立上下文与 Worktree

```
主代理（Coordinator）
  │
  ├── 创建 git worktree:
  │     git worktree add .claude/worktrees/{name} HEAD
  │
  ├── 派发 Worker（独立上下文）
  │     每个Worker有自己的 messages[]
  │     每个Worker有自己的 QueryEngine 实例
  │
  ├── Worker执行（在独立worktree目录）
  │     文件改动不影响主目录
  │
  ├── Worker返回摘要（通过SyntheticOutput）
  │
  └── 主代理合并结果
        git merge / cherry-pick（如需要）
        清理worktree
```

---

## Coordinator 系统提示结构（coordinatorMode.ts）

```
getCoordinatorSystemPrompt() 返回 600行+ 的特化提示，包含：
  - 任务分解策略
  - Worker派发协议
  - 进度追踪规范
  - 结果汇聚格式
  - 错误处理预案
  - ASYNC_AGENT_ALLOWED_TOOLS 说明
  - scratchpad 使用指南
```

---

## SendMessage 协议（队友间通信）

```
MessageEnvelope:
{
  "type": "message" | "request" | "response" | "handoff",
  "from": "alice",
  "to": "bob",
  "content": "...",
  "request_id": "req_001",  // 用于 ProtocolRequest 追踪
  "timestamp": 1234567890
}
```

---

## TaskRecord（持久工作图）

```
TaskRecord:
{
  "id": "task_001",
  "goal": "重构认证模块",
  "status": "pending" | "in_progress" | "completed" | "failed",
  "blocks": ["task_002", "task_003"],  // 这个任务阻塞哪些
  "blocked_by": ["task_000"],          // 被哪些任务阻塞
  "owner": "worker_alice",
  "result": null
}
```

RuntimeTaskState = 同一任务的运行时执行槽（live executor），与TaskRecord分离。
