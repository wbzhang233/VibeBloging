# MCP、Hooks 与 Skills 扩展层详解

> 本文档是可视化 `images/06_MCP_Hooks_Skills扩展层.html` 的技术脚本。

---

## 一、扩展层三件套概览

```
┌──────────────────┬──────────────────┬──────────────────┐
│       MCP        │      Hooks       │     Skills       │
├──────────────────┼──────────────────┼──────────────────┤
│ 连接外部服务      │ 事件响应脚本      │ 可复用任务模板    │
│ 工具/资源/提示    │ 5个触发点         │ 懒加载语言匹配    │
│ 标准化协议        │ 自动化工作流      │ 三层加载          │
│ JSON-RPC          │ Shell/Python     │ YAML 元数据       │
└──────────────────┴──────────────────┴──────────────────┘
```

---

## 二、MCP（Model Context Protocol）

### 2.1 架构

```
Claude Code（MCP Client）
        │
        │  JSON-RPC 2.0
        │  Transport: stdio / SSE / HTTP
        │
   MCP Server（工具适配器）
        │
   ┌────┴────┐
   │         │
数据库      第三方API
文件系统    内部服务
```

### 2.2 三种能力类型

| 能力 | 说明 | 示例 |
|------|------|------|
| **Tools** | 可调用函数，模型主动发起 | `query_database(sql)`, `create_github_issue(...)` |
| **Resources** | 可读数据，URI 寻址 | `file://path/to/doc`, `postgres://table/users` |
| **Prompts** | 提示模板，可参数化 | `code-review-template`, `git-commit-template` |

### 2.3 传输协议

| 传输方式 | 适用场景 | 特点 |
|---------|---------|------|
| **stdio** | 本地进程 | 最简单，适合本地工具服务 |
| **SSE（Server-Sent Events）** | 远程服务 | 服务器推送，适合长连接 |
| **HTTP** | REST 风格 | 无状态，适合简单 API 适配 |

### 2.4 配置示例

```json
// .claude/settings.json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
    },
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": {
        "POSTGRES_URL": "postgresql://localhost/mydb"
      }
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

### 2.5 MCP 工具调用流程

```
模型决定调用 MCP 工具
    ↓
Harness 识别工具名前缀（mcp__servername__toolname）
    ↓
通过 JSON-RPC 发送请求到对应 MCP Server
    ↓
MCP Server 执行（查询数据库、调用 API 等）
    ↓
返回结果（JSON）
    ↓
Harness 转换为 tool_result 注入上下文
```

---

## 三、Hooks 系统

### 3.1 五个事件点

```
时序轴：

用户输入
    │
    ▼
[1] UserPromptSubmit    ← 用户消息进入系统时
    │                     用途：输入预处理、日志记录
    ▼
[2] PreToolUse          ← 工具即将执行前
    │                     用途：安全检查、参数记录、阻止危险操作
    ▼
[工具执行]
    │
    ▼
[3] PostToolUse         ← 工具执行完成后
    │                     用途：结果日志、触发后续动作
    ▼
[模型生成最终输出]
    │
    ▼
[4] Stop                ← 模型输出最终结果时
    │                     用途：通知、自动保存、质量检查
    ▼
[5] Notification        ← 需要用户关注时
                          用途：自定义通知方式（声音/推送等）
```

### 3.2 配置格式

```json
// settings.json → hooks 字段
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/validate_command.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/log_file_changes.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python scripts/notify_completion.py"
          }
        ]
      }
    ]
  }
}
```

### 3.3 Hook 脚本接收的上下文（stdin）

```json
// PreToolUse Hook 收到的 JSON
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push origin main",
    "description": "Push changes to remote"
  },
  "session_id": "abc123"
}

// Hook 脚本通过 exit code 控制行为：
// exit 0 → 继续执行
// exit 2 → 阻止工具执行（BlockingError）
// 其他   → 记录警告，继续执行
```

### 3.4 典型 Hook 应用场景

| 场景 | Hook 点 | 实现 |
|------|---------|------|
| 命令安全审计 | PreToolUse(Bash) | 正则匹配危险命令，exit 2 阻止 |
| 文件变更日志 | PostToolUse(Write\|Edit) | 记录到 change_log.json |
| 完成通知 | Stop | 发送系统通知/飞书消息 |
| 自动格式化 | PostToolUse(Write) | 运行 prettier/black |
| 用户输入处理 | UserPromptSubmit | 自动附加项目上下文 |

---

## 四、Skills 系统

### 4.1 什么是 Skills

Skills 是**可复用的任务级指令包**，类似"AI 程序"：打包了完成特定任务所需的指令、工具权限和参数配置。

与 MCP 的区别：
- MCP 扩展了"工具"（AI 能做什么）
- Skills 扩展了"任务"（AI 怎么做一类工作）

### 4.2 三层懒加载架构

```
加载时机              内容
─────────────────────────────────────────────────────
会话启动时            元数据层（metadata）
                      name, description, trigger_keywords
                      → 常驻内存，用于匹配触发

用户触发 Skill 时     指令层（instructions）
                      完整的任务指令（可达数千 token）
                      → 按需加载到上下文

执行过程中            资源层（resources）
                      引用的数据文件、示例、模板
                      → 仅在需要时读取
```

**价值**：避免把所有 Skills 指令都放入 System Prompt（会浪费大量 token）。

### 4.3 SKILL.md 结构

```yaml
---
# YAML Front Matter（元数据层，常驻）
name: news-analyzer
description: |
  Analyze financial news articles for sentiment and impact.
  Triggers on: "analyze news", "news sentiment", "新闻分析"
version: 1.0.0
author: team-aiwe

# 工具权限（限制 Skill 可使用的工具）
allowed-tools:
  - Read
  - WebFetch
  - WebSearch
  - Bash(python *)

# 是否需要独立子代理
context: fork  # fork = 在子代理中隔离执行

# 是否禁止模型自主调用（需用户触发）
disable-model-invocation: false
---

# News Analyzer Skill（指令层，触发时加载）

## 任务描述
分析给定的金融新闻文章，输出结构化的情感分析结果...

## 执行步骤
1. 读取输入文章
2. 识别实体（公司/人物/事件）
3. 评估情感极性（正面/负面/中性）
4. 计算置信度
5. 输出 JSON 格式结果

## 输出格式
```json
{
  "sentiment": "positive|negative|neutral",
  "score": -1.0 to 1.0,
  "confidence": 0.0 to 1.0,
  "entities": [...],
  "reasoning": "..."
}
```
```

### 4.4 触发机制

```
语言模型匹配（非硬编码关键词）：

用户输入："帮我分析一下这篇新闻的情绪"
         ↓
系统提示中的 Skills 元数据：
  "news-analyzer: Analyze financial news articles for sentiment..."
         ↓
模型语义匹配 → 决定调用 news-analyzer Skill
         ↓
加载完整 SKILL.md 指令层
         ↓
执行（在 fork 子代理中）
```

**关键特性**：触发是语义匹配，不是正则/关键词匹配，因此中英文都能触发。

### 4.5 `context: fork` 的作用

```python
# 当 SKILL.md 包含 context: fork 时：
# Skill 在独立子代理中执行，完成后只返回摘要

# 类似于：
Agent(
    description="执行 news-analyzer Skill",
    subagent_type="general-purpose",
    prompt=skill_instructions + user_input,
    # 子代理上下文完全独立
)
```

---

## 五、三者对比表

| 维度 | MCP | Hooks | Skills |
|------|-----|-------|--------|
| **本质** | 外部工具接入协议 | 事件响应脚本 | 可复用任务包 |
| **抽象层次** | 工具级（单次调用） | 操作级（执行前后） | 任务级（完整工作流） |
| **触发方式** | 模型主动调用 | 系统事件自动触发 | 用户指令语义匹配 |
| **编写语言** | 任意（实现 MCP 协议） | Shell / Python / 任意 | Markdown（SKILL.md）|
| **作用域** | 跨会话持久 | 跨会话持久 | 按需加载 |
| **典型用途** | 接数据库/API/文件系统 | 审计/通知/格式化 | 领域专业任务 |
| **隔离性** | 无 | 无 | 可选（context: fork）|
| **权限控制** | 通过 settings.json | 通过 exit code | 通过 allowed-tools |
