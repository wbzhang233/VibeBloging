# 深度解析：Function Call、MCP、Tools、Skills、Agent 与 Harness

> 作者：内部技术分享
> 日期：2026-03-24
> 受众：产品 + 研发混合

---

## 写在前面

AI 领域有一堆听起来很像、但实际上指向不同层次的词：

> Function Call、Tool Use、MCP、Skills、Agent、Harness……

有人以为 Function Call 就是 Tool Use，有人以为 MCP 就是"把工具给 AI 用"，有人把 Agent 和 Harness 混为一谈。

这篇文章从技术原理出发，把这 6 个概念**逐一拆清楚**，最后用一张对比表给出每个概念的适用边界。

---

## 一、从一个问题开始

**AI 为什么需要"手"？**

大语言模型的本质是**文本预测机器**：输入 token 序列，输出 token 序列。它能写代码、能分析问题、能给建议——但它天生只能"说"，不能"做"。

```
传统 LLM 的边界：
  输入 → [模型推理] → 输出（文字）

  ✅ 能做：生成文本、回答问题、逻辑推理
  ❌ 不能做：读取文件、调用 API、发送消息、执行代码
```

为了让 AI 从"说"变成"做"，业界发展出了一套完整的工具体系。这套体系从底到上，分为 6 个层次：

```
┌─────────────────────────────────────┐
│           Harness（运行时）           │  ← 谁在"跑"这一切
├─────────────────────────────────────┤
│           Agent（智能体）             │  ← AI 怎么"决策"
├─────────────────────────────────────┤
│           Skills（技能包）            │  ← 任务级别的复用
├─────────────────────────────────────┤
│     MCP（模型上下文协议）              │  ← 工具的标准化接入
├─────────────────────────────────────┤
│      Tool Use / Function Call        │  ← AI 怎么"调用"工具
└─────────────────────────────────────┘
```

理解这 6 个概念，就是理解这张图的每一层在做什么。

---

## 二、Function Call：AI 学会"点菜"

### 2.1 问题起点

2023 年 6 月，OpenAI 在 GPT-4 上推出了 **Function Calling** 功能，这是一个影响整个 AI 生态的关键设计。

**核心问题**：如何让模型的"意图"变成可执行的"指令"？

在 Function Calling 之前，AI 只能输出自然语言，开发者要自己从文本里解析意图——既不稳定，也不标准。

### 2.2 技术原理

Function Calling 的本质：**让模型输出结构化的 JSON，而不是自然语言**。

```python
# 开发者预先定义"菜单"（函数描述）
functions = [
    {
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
            },
            "required": ["city"]
        }
    }
]

# 用户提问
user_message = "北京今天天气怎么样？"

# 模型的输出（不是文字！是 JSON）
model_output = {
    "function_call": {
        "name": "get_weather",
        "arguments": '{"city": "北京", "unit": "celsius"}'
    }
}

# 开发者拿到 JSON，自己去执行
result = call_weather_api("北京", "celsius")

# 把结果再喂给模型
# 模型最终输出："北京今天气温 8°C，晴转多云。"
```

**关键洞见**：
- 模型**没有**真的调用函数——它只是输出了一个"我想调用这个函数"的 JSON
- **实际执行**是由应用程序（Host）来做的
- 模型充当的角色是"决策者"，Host 是"执行者"

```
┌──────────┐   1. 发送问题+函数定义   ┌──────────┐
│  应用程序  │ ────────────────────→  │   模型    │
│  (Host)  │                         │  (Brain) │
│          │ ←────────────────────   │          │
│          │   2. 返回 function_call  │          │
│          │      (JSON 结构)         └──────────┘
│          │
│          │   3. 应用程序自己执行函数
│          │      result = execute(function_call)
│          │
│          │   4. 把结果再发给模型     ┌──────────┐
│          │ ────────────────────→  │   模型    │
│          │ ←────────────────────   │          │
└──────────┘   5. 模型生成最终回复    └──────────┘
```

### 2.3 Function Call 与 Tool Use 的关系

这两个词指的是**同一件事**，只是不同厂商的叫法：

| 厂商 | 术语 | 备注 |
|------|------|------|
| OpenAI | Function Calling | 2023 年 6 月首推 |
| Anthropic | Tool Use | Claude 的叫法 |
| Google | Function Calling | Gemini 沿用 OpenAI 叫法 |
| 业界通用 | Tool Call / Tool Use | 逐渐成为标准叫法 |

Anthropic 在技术文档中将其称为 **Tool Use**，Claude 在响应中会输出 `<tool_use>` 块：

```xml
<!-- Claude 的 Tool Use 响应格式 -->
<tool_use>
  <tool_name>read_file</tool_name>
  <parameters>
    {"path": "/src/utils/helper.ts"}
  </parameters>
</tool_use>
```

**本质相同**：都是"模型输出结构化请求 → Host 执行 → 结果返回模型"。

---

## 三、Tool Use：工具系统的全貌

### 3.1 从 Function Call 到 Tool Use 体系

Function Call 只描述了"如何调用"，**Tool Use** 是一个更完整的概念，包含：

1. **工具定义**（Tool Definition）：描述工具的名称、参数、用途
2. **工具调用**（Tool Call）：模型决定调用哪个工具，带什么参数
3. **工具执行**（Tool Execution）：Host 实际运行工具，获取结果
4. **结果注入**（Result Injection）：把执行结果塞回模型上下文
5. **继续推理**（Continue Inference）：模型拿着结果继续决策

以 Claude Code 为例，它的内置工具覆盖了常见操作类别：

```
文件操作类：
  Read    → 读取文件（支持 PDF、图片、Jupyter Notebook）
  Write   → 创建/覆盖文件
  Edit    → 精确字符串替换
  Glob    → 文件模式匹配
  Grep    → 内容搜索（底层是 ripgrep）

执行类：
  Bash    → 执行 Shell 命令（支持后台运行、超时）
  TaskOutput → 获取后台任务输出（异步轮询）

网络类：
  WebFetch  → 抓取网页并 AI 提取
  WebSearch → 联网搜索

协作类：
  Agent     → 启动子 Agent 并行处理
  TodoWrite → 任务清单管理
```

### 3.2 工具调用的完整循环

```python
# Tool Use 的伪代码本质
messages = [system_prompt, user_input]

while True:
    response = model(messages)          # 模型推理

    if response.has_tool_call:
        tool_result = execute(           # Host 执行工具
            response.tool_call.name,
            response.tool_call.params
        )
        messages.append(tool_result)    # 结果注入上下文
    else:
        return response.text            # 没有工具调用 → 任务完成
```

这个循环就是 Agent 的核心原理——我们后面会展开说。

---

## 四、MCP：工具生态的"USB 接口标准"

### 4.1 没有 MCP 之前的世界

在 MCP 之前，每个 AI 应用要接入外部工具，都需要**自己写适配代码**：

```
没有 MCP 的世界：

  Claude Code  ──自定义集成──→  GitHub API
  Claude Code  ──自定义集成──→  PostgreSQL
  Claude Code  ──自定义集成──→  Slack API

  Cursor       ──自定义集成──→  GitHub API（重新写一遍）
  Cursor       ──自定义集成──→  PostgreSQL（再重新写一遍）

  每个 AI 客户端都要为每个数据源单独写集成代码
  → 重复工作量极大
  → 接口不统一，质量参差不齐
  → 维护成本高
```

### 4.2 MCP 是什么

**MCP（Model Context Protocol）** 是 Anthropic 于 2024 年 11 月提出的**开放标准协议**，定义了 AI 模型如何与外部工具/数据源通信。

类比：**MCP 是 AI 工具的"USB 接口标准"**。

```
有了 MCP：

  MCP Server（GitHub）  ←────────────────────→  Claude Code
  MCP Server（PostgreSQL） ←──────────────────→  Claude Code
  MCP Server（Slack）    ←────────────────────→  Claude Code

  同一个 MCP Server（GitHub）         →  Claude Code
                                      →  Cursor
                                      →  任何 MCP 客户端

  写一次 Server，所有 AI 客户端通用
```

### 4.3 MCP 技术架构

```
┌─────────────────────────────────────────────┐
│             MCP Client                       │
│  （Claude Code / Cursor / 任何 AI 应用）      │
└────────────────┬────────────────────────────┘
                 │  JSON-RPC over stdio / SSE / HTTP
                 ↓
┌─────────────────────────────────────────────┐
│             MCP Server                       │
│   （工具的具体实现，可以是任何语言写的）        │
└────────────────┬────────────────────────────┘
                 │
        ┌────────┼────────┐
        ↓        ↓        ↓
   数据库      API      文件系统
  (PostgreSQL) (GitHub)  (本地)
```

### 4.4 MCP 提供三类能力

| 类型 | 描述 | 示例 |
|------|------|------|
| **Tools** | 可调用的函数（动作） | 查询数据库、创建 GitHub Issue、发送消息 |
| **Resources** | 可读取的数据（内容） | 文档、配置文件、代码库 |
| **Prompts** | 预设提示模板（知识） | 代码审查模板、文档生成模板 |

### 4.5 MCP 配置示例（Claude Code）

```json
// .claude/settings.json
{
  "mcpServers": {
    "postgres": {
      "command": "mcp-server-postgres",
      "args": ["postgresql://localhost/mydb"]
    },
    "github": {
      "command": "mcp-server-github",
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "slack": {
      "command": "mcp-server-slack",
      "env": {
        "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}"
      }
    }
  }
}
```

配置完成后，Claude Code 就能直接查询数据库、操作 GitHub、发 Slack 消息——无需任何自定义代码。

### 4.6 MCP 的本质定位

> **MCP 解决的不是"AI 能调用工具"的问题，而是"如何让工具对所有 AI 通用"的问题。**

它是工具生态的**标准化层**，而不是工具本身。

---

## 五、Skills：比工具更高层的"配方"

### 5.1 工具的局限

假设我要让 AI 完成一个任务："帮我写一篇关于 React Server Components 的技术文章"。

这个任务需要：
1. 搜索相关资料（工具：WebSearch）
2. 读取几个具体文档（工具：WebFetch）
3. 组织内容结构
4. 生成文章
5. 保存到文件（工具：Write）

每次执行这个任务，你都需要在提示词里描述这个流程。**工具解决的是"能做什么"，但没解决"怎么组合"的复用问题。**

### 5.2 Skills 是什么

**Skills（技能包）** 是比工具更高一层的抽象：**结构化的、可复用的任务模板**。

一个 Skill 包含：
- **触发条件**：什么情况下应该用这个 Skill
- **执行流程**：分步骤的工具调用序列
- **失败处理**：工具调用失败时怎么办
- **验证机制**：如何确认任务真的完成了

```markdown
# Skill: 技术文章生成

## 触发条件
当用户请求"写一篇关于 X 的技术文章"时触发。

## 执行流程
1. 用 WebSearch 搜索 "[主题] 技术原理 最新进展"，获取 3-5 个高质量来源
2. 用 WebFetch 读取每个来源，提取核心技术点
3. 按"背景 → 原理 → 实践 → 对比 → 总结"的结构组织内容
4. 生成 2000-3000 字文章，包含代码示例
5. 用 Write 保存为 Markdown 文件

## 渐进式披露（Progressive Disclosure）
- 先输出高层摘要，确认方向后再展开细节
- 遇到技术细节不确定时，标注"需要验证"，不编造信息

## 完成验证
- 文件已保存
- 文章包含至少 1 个有意义的代码示例
- 引用来源真实可访问
```

### 5.3 Skills 的渐进式披露机制

Skills 的一个核心设计是**渐进式披露（Progressive Disclosure）**：

```
传统方式（信息爆炸）：
  每次任务开始，把所有工具描述、所有流程细节全部注入上下文
  → 消耗大量 token
  → 模型被细节淹没，抓不住重点

Skills 的方式（按需展开）：
  第一层：高层摘要（"这是一个文章生成任务，需要搜索→整合→写作"）
  第二层：需要更多细节时，展开搜索步骤的具体参数
  第三层：需要处理异常时，展开错误处理逻辑

  → 节省 token
  → 模型保持清晰的任务意图
```

### 5.4 Skills vs Tools 的本质区别

```
Tools（工具）：
  抽象级别：原子操作
  例子：read_file("path")、web_search("query")
  类比：螺丝刀、锤子

Skills（技能）：
  抽象级别：任务级别的工作流
  例子：技术文章生成、竞品调研报告、代码重构
  类比："如何装一扇门"的操作手册（组合使用螺丝刀+锤子+水平仪）
```

---

## 六、Agent：有了工具的 AI，才叫 Agent

### 6.1 最简定义

```
Agent = Loop（循环）+ Tools（工具）
```

这是理解 Agent 最精准的公式。

一个 Agent 的伪代码：

```python
messages = [system_prompt, user_input]

while True:
    response = llm(messages)           # 模型推理

    if response.has_tool_call:
        result = execute_tool(          # 执行工具
            response.tool_call.name,
            response.tool_call.params
        )
        messages.append(tool_result)   # 结果注入上下文
    else:
        return response.content        # 任务完成，返回结果
```

**Claude Code 的工作原理、Cursor 的工作原理、所有 Coding Agent 的底层原理——都是这个循环。**

### 6.2 Agent 的进化路径

```
简单 Agent（Loop + Bash）
    ↓ + Memory
有记忆的 Agent（CLAUDE.md / Memory Files）
    ↓ + Rules + Hooks
有约束的 Agent（SOUL.md / 权限系统）
    ↓ + Identity
有身份的 Agent（IDENTITY.md / System Prompt）
    ↓ + 多 Agent 协作
Agent 系统（Orchestrator + Subagents）
    ↓ + Heartbeat
自我维护的 Agent（定时任务 + 主动巡检）
```

### 6.3 Agent 的三个核心能力

**能力 1：感知（Perception）**
```
读取文件 → 了解代码库
搜索网络 → 获取外部信息
执行命令 → 观察系统状态
```

**能力 2：推理（Reasoning）**
```
分析感知到的信息
制定下一步行动计划
决定调用哪个工具、带什么参数
```

**能力 3：行动（Action）**
```
写文件、修代码
执行 Shell 命令
调用外部 API
启动子 Agent
```

### 6.4 多 Agent 架构

当单个 Agent 不够用时，多个 Agent 协作：

```
主 Agent（Orchestrator）
    │
    ├── 子 Agent 1：Explore（只读，探索代码库）
    │       工具：Glob, Grep, Read, WebFetch
    │
    ├── 子 Agent 2：Plan（只读，设计方案）
    │       工具：Glob, Grep, Read
    │
    └── 子 Agent 3：Execute（读写，执行任务）
            工具：全部工具
```

**关键设计原则**：
- 子 Agent 在独立的上下文中运行（不污染主 Agent 的上下文）
- 子 Agent 只返回摘要给主 Agent（节省 token）
- 不同角色的子 Agent 有不同的工具权限（最小权限原则）

---

## 七、Harness：谁在"跑"这一切

### 7.1 什么是 Harness

**Harness（运行时框架）** 是让 Agent 得以运行的**基础设施层**。

如果说 Agent 是"大脑"，那 Harness 就是"身体 + 神经系统"——负责协调大脑的决策与外部世界的执行。

```
没有 Harness，Agent 只是一段代码
有了 Harness，Agent 才能真正"活"起来
```

### 7.2 Harness 做了什么

一个完整的 Harness 负责：

```
┌──────────────────────────────────────────────────┐
│                   Harness                          │
│                                                    │
│  1. 消息管理      维护对话历史、处理上下文窗口      │
│  2. 工具调度      拦截 tool_call，路由到对应执行器  │
│  3. 权限检查      验证操作是否被允许               │
│  4. Hook 触发     在特定事件时执行自定义脚本        │
│  5. 子 Agent 管理  启动/监控/回收子 Agent 进程      │
│  6. 错误恢复      工具执行失败时的重试与降级        │
│  7. 流式输出      实时展示推理过程给用户            │
│  8. 会话持久化    将重要信息写入 Memory Files       │
└──────────────────────────────────────────────────┘
```

### 7.3 Claude Code 就是一个 Harness

Claude Code 的工作原理：

```
用户输入
    ↓
Claude Code (Harness)
    ├── 加载 CLAUDE.md（项目上下文）
    ├── 加载 Memory Files（历史记忆）
    ├── 构建系统提示（System Prompt）
    └── 进入 Agentic Loop
            ↓
        调用 Claude API（模型推理）
            ↓
        模型输出 tool_call？
            ├── 是：检查权限 → 执行工具 → 触发 PostToolUse Hook → 结果注入 → 继续
            └── 否：展示输出 → 触发 Stop Hook → 等待用户
```

### 7.4 Harness 的核心特性

**权限模型**（谁能做什么）：
```json
{
  "permissions": {
    "allow": ["Bash(npm run *)", "Bash(git status)"],
    "deny": ["Bash(rm -rf *)", "Bash(git push --force *)"]
  }
}
```

**Hooks 系统**（什么时候自动做什么）：
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit",
      "hooks": [{"type": "command", "command": "eslint {{file}} --fix"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "notify-send '任务完成'"}]
    }]
  }
}
```

**不同 Harness 的比较**：

| Harness | 代表产品 | 特点 |
|---------|---------|------|
| CLI 型 | Claude Code CLI | 终端原生，脚本集成能力强 |
| IDE 型 | VS Code 扩展、Cursor | 与编辑器深度集成 |
| 桌面型 | Claude Desktop | 可视化操作，低技术门槛 |
| 框架型 | OpenClaw、LangChain | 可自托管，高度可定制 |
| 云型 | ArkClaw、WorkBuddy | 7×24 运行，无需本地环境 |

---

## 八、横向对比：6 个概念一张表

| 维度 | Function Call | Tool Use | MCP | Skills | Agent | Harness |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **层次** | 协议层 | 协议层 | 接入层 | 任务层 | 决策层 | 运行层 |
| **是谁定义的** | 开发者（JSON Schema） | 开发者（JSON Schema） | MCP Server 开发者 | Skill 设计者 | 系统设计者 | 框架开发者 |
| **谁在执行** | Host（应用程序） | Host（应用程序） | MCP Client | 模型+工具 | 模型+工具 | Harness 自身 |
| **模型的角色** | 决定调用哪个函数 | 决定调用哪个工具 | 决定调用哪个 MCP 工具 | 按 Skill 模板执行 | 自主规划+执行 | 无感（被 Harness 包裹） |
| **复用粒度** | 单次调用 | 单次调用 | 跨平台通用 | 任务级别 | 项目/系统级别 | 应用级别 |
| **有没有自主性** | 无（执行指令） | 无（执行指令） | 无（标准接口） | 有限（按模板） | 有（自主规划） | 无（基础设施） |

### 关系总结图

```
┌─────────────────────────────────────────────────────────────┐
│                        Harness                               │
│   （Claude Code / OpenClaw / Cursor / 自定义框架）           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                     Agent Loop                        │   │
│  │   用户输入 → 模型推理 → 工具调用 → 结果注入 → 循环   │   │
│  └─────────────────────────┬────────────────────────────┘   │
│                             │ 调用工具                        │
│         ┌───────────────────┼──────────────────────┐        │
│         ↓                   ↓                       ↓        │
│  ┌─────────────┐   ┌────────────────┐   ┌──────────────┐   │
│  │  内置 Tools  │   │   MCP Tools    │   │   Skills     │   │
│  │ (Read/Write/ │   │ (GitHub/PG/   │   │ (任务模板    │   │
│  │  Bash/Grep) │   │  Slack/...)   │   │  = 工具组合) │   │
│  └─────────────┘   └────────────────┘   └──────────────┘   │
│         │                   │                                 │
│    Function Call /     Function Call /                        │
│      Tool Use            Tool Use                            │
│    （底层调用协议）      （底层调用协议）                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 九、适用性与使用场景

### 9.1 Function Call / Tool Use

**你需要它，当：**
- 从零构建 AI 应用，需要让模型与代码逻辑交互
- 已有 API 或函数，想让 AI 决策何时调用
- 需要模型输出结构化数据（而不是纯文本）

**典型场景：**
```
✅ 构建 AI 客服：模型决定查询订单、发起退款、转人工
✅ 智能表单填写：模型解析用户自然语言，填充结构化字段
✅ 数据库查询助手：模型生成 SQL 参数，应用执行查询
```

**不适合：**
```
❌ 你只需要让 AI 写文章或回答问题（不需要工具调用）
❌ 工具很多，想复用于多个 AI 产品（用 MCP）
```

---

### 9.2 MCP

**你需要它，当：**
- 你有数据源/服务，想让**多个 AI 产品**都能接入
- 你在构建工具，想加入"AI 原生"生态（任何支持 MCP 的 AI 都能用）
- 你想以标准化方式暴露内部系统能力

**典型场景：**
```
✅ 企业内部知识库：写一个 MCP Server，接入 Claude Code、Cursor 等所有工具
✅ 数据库访问：mcp-server-postgres，一次编写，多处使用
✅ SaaS API 封装：把 Stripe、Jira、Notion 的 API 封装为 MCP Server
```

**不适合：**
```
❌ 只给一个 AI 应用用的私有工具（直接写 Tool Use 更简单）
❌ 需要复杂状态管理的工具（MCP 本身是无状态协议）
```

---

### 9.3 Skills

**你需要它，当：**
- 有**反复执行的复杂任务**，每次都需要相似的多步骤流程
- 想让 AI 的任务执行更稳定、可预期（而不是每次"创意发挥"）
- 需要在团队内分享和复用 AI 工作流

**典型场景：**
```
✅ 竞品调研：定义一个"竞品分析 Skill"，搜集→分析→生成报告
✅ 代码审查：定义一个"PR Review Skill"，检查安全、性能、规范
✅ 内容生产：定义一个"技术文章 Skill"，保证每次输出格式一致
```

**不适合：**
```
❌ 任务每次都不一样，没有可复用的流程（直接提示词更灵活）
❌ 极简单的单步任务（直接用 Tool 调用即可）
```

---

### 9.4 Agent

**你需要它，当：**
- 任务**需要多步骤、多工具的自主规划**，不能预先硬编码步骤
- 任务结果**不确定**，需要 AI 根据中间结果调整策略
- 需要让 AI 在**无人监督**的情况下完成复杂工程任务

**典型场景：**
```
✅ 大型代码重构：AI 自主分析影响范围，制定迁移计划，逐步执行
✅ Bug 排查：AI 搜索日志、读取代码、定位根因、提出修复方案
✅ 数据管道搭建：AI 设计 Schema、写脚本、测试、修复直到通过
```

**不适合：**
```
❌ 对正确性要求极高的核心业务逻辑（支付、权限）→ 人工审查是必须的
❌ 需要实时响应（< 1s）的场景 → Agent 循环有延迟
❌ 任务非常简单（问答、补全）→ 单次调用就够了
```

---

### 9.5 Harness

**你需要它，当：**
- 你在**构建** AI 产品或内部工具（而不是使用现有产品）
- 需要自定义权限模型、日志、审批流
- 有特殊的安全合规要求（企业内网部署、数据不出境）

**典型场景：**
```
✅ 构建企业内部 AI 助手：自定义权限、接入内网系统、配置审批流
✅ CI/CD 集成：在流水线里运行 Agent，自动化代码审查、文档生成
✅ 定制化 Agent 框架：在 OpenClaw 基础上二次开发，加上内部安全策略
```

**不适合：**
```
❌ 你只是使用现有 AI 工具（Claude Code、Cursor）→ 它们已经内置了 Harness
❌ 需求很简单，直接调用 API 就够了
```

---

## 十、选型决策树

```
我有一个 AI 相关需求
    │
    ├── 只是想让 AI 生成文本/回答问题？
    │       → 直接调用 LLM API，不需要以上任何东西
    │
    ├── 需要 AI 与代码/系统交互？
    │       │
    │       ├── 需求是一次性的，只在当前应用里用？
    │       │       → Function Call / Tool Use（直接定义）
    │       │
    │       └── 工具需要给多个 AI 产品使用？
    │               → MCP Server（一次写好，到处用）
    │
    ├── 有反复执行的复杂多步骤任务？
    │       → Skills（定义任务模板，可复用）
    │
    ├── 任务需要自主规划、多步执行、不确定结果？
    │       → Agent（用现有 Harness：Claude Code、OpenClaw 等）
    │
    └── 需要构建自己的 AI 运行平台？
            → Harness（选开源框架二次开发，或从零构建）
```

---

## 十一、一个实例：把所有概念串起来

**场景**：构建一个"每日竞品情报监控 Agent"

```
┌─────────────────────────────────────────────────────┐
│                    Harness                            │
│              （自托管的 OpenClaw）                    │
│                                                      │
│  HEARTBEAT.md 定义：每日 9:00 自动执行               │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │              Agent Loop                      │    │
│  │                                              │    │
│  │  触发：HEARTBEAT 心跳                         │    │
│  │      ↓                                       │    │
│  │  调用 Skill：「竞品情报收集」                  │    │
│  │      ↓                                       │    │
│  │  Skill 内部依次调用：                         │    │
│  │    ┌──────────────────────────────────────┐  │    │
│  │    │ Tool Use：WebSearch                  │  │    │
│  │    │    Function Call → 搜索竞品新动态     │  │    │
│  │    ├──────────────────────────────────────┤  │    │
│  │    │ Tool Use：WebFetch                   │  │    │
│  │    │    Function Call → 读取具体网页       │  │    │
│  │    ├──────────────────────────────────────┤  │    │
│  │    │ MCP Tool：send_feishu_message        │  │    │
│  │    │    MCP Server → 飞书机器人 API        │  │    │
│  │    └──────────────────────────────────────┘  │    │
│  │      ↓                                       │    │
│  │  Loop 结束，更新 MEMORY.md                   │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  Hook：Stop → 记录执行日志                           │
└─────────────────────────────────────────────────────┘
```

每个概念在这个系统里扮演的角色：

| 概念 | 在这个例子里的角色 |
|------|----------------|
| **Function Call** | 底层协议，WebSearch/WebFetch 的调用格式 |
| **Tool Use** | Claude 与 Harness 交互的机制 |
| **MCP** | 飞书机器人的标准化接入方式 |
| **Skills** | "竞品情报收集"这个可复用的任务流程 |
| **Agent** | 理解目标、规划步骤、调度工具的决策逻辑 |
| **Harness** | OpenClaw 运行时，负责心跳触发、权限管控、日志记录 |

---

## 总结

这 6 个概念，从不同维度解决了"让 AI 从说变成做"的问题：

```
Function Call / Tool Use
    解决：AI 如何表达"我想调用某个功能"

MCP
    解决：工具如何跨 AI 产品标准化复用

Skills
    解决：多步骤复杂任务如何结构化复用

Agent
    解决：AI 如何自主规划和执行多步骤任务

Harness
    解决：AI 运行所需的基础设施（权限、钩子、循环管理）
```

它们**不是竞争关系，而是层次关系**：

> Harness 跑 Agent，Agent 用 Skills，Skills 组合 Tools，Tools 通过 Function Call 实现，MCP 标准化 Tools 的接入。

理解了这张层次图，你就理解了现代 AI Agent 系统的全貌。

---

*本文基于 Claude Code、OpenClaw 等主流 AI Agent 框架的技术文档及工程实践整理，2026 年 3 月。*
