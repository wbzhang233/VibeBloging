# 多 Agent 与 Worktree 详解

> 本文档是可视化 `images/03_多Agent_Worktree编排.html` 的技术脚本。

---

## 一、为什么需要多 Agent

单 Agent 模式的瓶颈：

1. **上下文窗口有限**：复杂任务积累大量历史，token 消耗激增
2. **串行执行慢**：需要并发探索多个代码库区域时，只能一个个来
3. **隔离性差**：子任务的中间状态污染主代理上下文

多 Agent 架构的价值：

```
单 Agent（串行）           多 Agent（并行）
┌─────────────────┐        ┌──── Explore A ────┐
│ Task 1（10s）   │        │ Task 1（10s）      │
│ Task 2（10s）   │   vs   │ Task 2（10s）      │ → 全部并行 = 10s
│ Task 3（10s）   │        │ Task 3（10s）      │
└─────────────────┘        └────────────────────┘
总计: 30s                  总计: 10s（理想情况）
```

---

## 二、内置 Agent 类型

| Agent 类型 | 定位 | 可用工具 | 典型用途 |
|-----------|------|---------|---------|
| `general-purpose` | 通用复杂任务 | 全工具集（含 Edit/Write/Bash） | 代码生成、调试、重构 |
| `Explore` | 快速代码库探索 | 只读（Glob/Grep/Read/WebFetch，无 Edit/Write） | 理解代码结构、找文件 |
| `Plan` | 架构设计规划 | 只读（无 Edit/Write/NotebookEdit） | 设计方案、识别关键文件 |
| `claude-code-guide` | Claude 自身知识问答 | Glob/Grep/Read/WebFetch/WebSearch | 查询 Claude Code 文档 |

---

## 三、多 Agent 架构图

```
Coordinator（主代理）
│   上下文：完整对话历史
│   权限：全工具
│
├── [并行] Explore 子代理 × N
│   │  上下文：独立（隔离）
│   │  权限：只读
│   │  工具：Glob, Grep, Read, WebFetch
│   └── 返回：探索摘要（压缩后）
│
├── [并行] Plan 子代理
│   │  上下文：独立（隔离）
│   │  权限：只读
│   │  工具：Glob, Grep, Read
│   └── 返回：实现计划（步骤列表）
│
└── [串行/并行] Execute 子代理 × M
    │  上下文：独立（隔离）
    │  权限：全工具（含写入）
    │  隔离：git worktree（可选）
    └── 返回：执行摘要 + 变更清单
```

---

## 四、Agent 工具调用协议

```python
# 主代理启动子代理（并行）
Agent(
    description="探索认证模块",
    subagent_type="Explore",
    prompt="找出所有与用户认证相关的文件，返回文件路径和功能摘要",
    run_in_background=True   # 后台运行
)

Agent(
    description="探索数据库层",
    subagent_type="Explore",
    prompt="找出所有 ORM 模型和迁移文件，返回表结构摘要",
    run_in_background=True
)

# 等待所有子代理完成（通过 TaskOutput）
# 主代理收集摘要，继续规划
```

**关键设计**：子代理运行在**独立上下文**中，完成后只返回摘要文本给主代理，而不是完整对话历史。这保护了主代理的上下文窗口。

---

## 五、Worktree 隔离机制

### 5.1 什么是 git worktree

`git worktree` 允许在同一 git 仓库的不同分支上同时工作，每个 worktree 是独立的工作目录：

```
原始仓库
.git/           ← 共享的 git 对象存储
src/            ← main 分支工作区

.claude/worktrees/agent-abc123/   ← 子代理 worktree（新分支）
    src/                           ← 完全独立的文件系统视图
    .git                           ← 指向原始 .git 的符号链接
```

### 5.2 Worktree 生命周期

```
[创建] EnterWorktree(name="feature-x")
    ↓
git worktree add .claude/worktrees/feature-x -b worktree/feature-x
    ↓
子代理在 worktree 内独立执行（所有文件修改隔离在此分支）
    ↓
[合并] 主代理审查变更 → cherry-pick / merge
    ↓
[清理] ExitWorktree(action="remove")
    ↓
git worktree remove + git branch -d
```

### 5.3 Worktree 的价值

```
不用 worktree（直接在主分支操作）：
├── 子代理 A 修改 src/auth.py
└── 子代理 B 同时修改 src/auth.py → 冲突！

用 worktree（每个子代理独立分支）：
├── 子代理 A → worktree/agent-a/src/auth.py
└── 子代理 B → worktree/agent-b/src/auth.py → 无冲突，主代理合并时解决
```

---

## 六、SendMessage 协议

子代理之间可以直接通信，无需通过主代理中转：

```python
# 子代理 A 发现依赖信息，通知子代理 B
SendMessage(
    to="agent-b",           # 目标 Agent ID 或名称
    message="auth 模块使用 JWT，secret 在 config/jwt.yml"
)

# 子代理 B 收到消息，继续其上下文
# （完整上下文保留，无需重启）
```

**带依赖追踪的任务列表**：

```python
# 任务 3 必须等任务 1 和 2 完成后才能开始
TaskCreate("实现认证中间件", description="...")
TaskUpdate(taskId="3", addBlockedBy=["1", "2"])
```

---

## 七、子代理隔离总结

| 隔离维度 | 是否隔离 | 说明 |
|---------|---------|------|
| 上下文窗口 | ✅ 完全隔离 | 每个子代理有独立对话历史 |
| 文件系统 | ✅ 可选隔离 | 通过 `isolation: "worktree"` 参数 |
| 工具权限 | ✅ 按类型限制 | Explore/Plan 为只读 |
| git 历史 | ✅ 隔离（worktree 模式） | 独立分支，主代理审查后合并 |
| 环境变量 | ❌ 共享 | 继承父进程环境 |
| MCP 连接 | ❌ 共享 | 复用已建立的 MCP Server 连接 |
