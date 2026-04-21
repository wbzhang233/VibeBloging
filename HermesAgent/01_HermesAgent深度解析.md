# Hermes Agent 深度解析：一个会自己"长大"的 AI 管家

> "准备放弃龙虾转爱马仕了，龙虾记忆太差了，爱马仕无论怎么重开，过多久都能记住，太香了！"

这是一条在开发者社区广泛流传的评论。短短几个月，Hermes Agent 从 2025 年 2 月开源到斩获近 4 万 GitHub Stars，吸引了谷歌高级 AI 产品经理公开点赞，并引发了大规模的"从龙虾到爱马仕"迁移热潮。

它究竟解决了什么问题？

---

## 一、它在解决一个真实痛点

传统 AI 对话工具有一个根本性缺陷：**每次重启，等于失忆**。你昨天和 AI 讲清楚的工作习惯、偏好、项目背景，今天要从头解释。你上周让它帮你整理的工作流，下周又得重新教一遍。

更糟的是，那些试图"记住一切"的 Agent，往往走向另一个极端：把所有对话都塞进上下文，Token 成本随使用时间线性飙升，直到用不起为止。

Hermes Agent 的回答是：**既然记不住，不如让它自己学会"什么值得记"**。

这不是一个记录工具的改进，而是一种不同的产品哲学——把记忆的判断权，从人转移到 Agent 自身。

---

## 二、架构核心：单 Agent 持久循环

要理解 Hermes，需要先理解它与当下主流 Agent 架构的根本差异。

当前大多数 AI Agent 框架（包括 Claude Code 的官方架构）走的是**多 Agent 编排**路线：一个主协调器（Coordinator）负责任务拆解，多个子 Agent 并行执行，结果汇总后交付。这套架构对复杂工程任务效率极高，但有一个先天弱点——**"发生了什么"很难在会话间留存**。

Hermes 回归了更简单的设计：**单 Agent 持久循环（Single-Agent Persistent Loop）**。

没有编排层，没有多 Agent 集群。核心是一个 **11,000+ 行的 `AIAgent` 类**（`run_agent.py`），所有任务都走同一条链路：

```
输入 → 推理 → 工具使用 → 记忆更新 → 技能蒸馏 → 结果输出
```

**API 兼容层**：Hermes 使用 OpenAI 兼容 API 接口，这意味着它可以无缝切换后端模型——OpenAI GPT、Anthropic Claude、本地 Ollama、甚至通过 OpenRouter 接入任何模型。不绑定任何特定模型供应商。

**模型感知提示优化**：`agent/prompt_builder.py` 会根据当前模型自动注入针对性指导。例如 GPT/Codex 模型会收到 `TOOL_USE_ENFORCEMENT_GUIDANCE`（强制工具使用指导）和 `OPENAI_MODEL_EXECUTION_GUIDANCE`（执行纪律指导），Gemini/Gemma 模型会收到 `GOOGLE_MODEL_OPERATIONAL_GUIDANCE`。这保证了无论使用哪个后端模型，Agent 的工具调用质量都有保障。

真正的区别在于**任务结束之后会发生什么**。Hermes 不会就此停止——它会回头评估这次任务处理得好不好，值不值得保留为一个可复用的工作流。后台巡检在**守护线程**中运行，不阻塞用户交互。

这种设计的代价是：放弃了多 Agent 并行的执行效率，换来了长期使用的"越用越顺手"。

---

## 三、记忆系统：MemoryManager 统一编排

Hermes 最被称道的设计是其记忆体系。它解决的核心问题是：**如何在不推高 Token 成本的前提下，让 Agent 真正记住你。**

`agent/memory_manager.py` 中的 `MemoryManager` 类统一编排所有记忆层——**内置提供者 + 至多一个外部插件提供者**。每个提供者独立运行，失败不相互阻塞。

### 第一层：提示记忆（Prompt Memory）

对应文件 `MEMORY.md` 和 `USER.md`，每次会话开始时自动加载，常驻在上下文中。

关键约束：**两份文件合计只允许 3,575 个字符**。

这个限制是刻意设计的。逼迫系统只保留真正重要、值得长期记住的信息，而不是无节制地堆积。`prompt_builder.py` 中的 `MEMORY_GUIDANCE` 明确指示：

> *"Prioritize what reduces future user steering — the most valuable memory is one that prevents the user from having to correct or remind you again."*

**用户偏好和反复纠正比任务细节更值得记忆**——这是 Hermes 记忆系统的第一性原理。

### 第二层：会话检索（Session Search）

所有历史会话写入 SQLite，通过 FTS5 全文索引建立检索能力。`prompt_builder.py` 中的 `SESSION_SEARCH_GUIDANCE` 指示 Agent：

> *"When the user references something from a past conversation or you suspect relevant cross-session context exists, use session_search to recall it before asking them to repeat themselves."*

Agent **只在判断当前任务与历史相关时才主动检索**，而不是默认把所有旧内容塞回窗口。检索结果还会先经过 LLM 摘要，只保留与当前任务相关的部分，再进入上下文。

### 第三层：技能程序性记忆（Skills Procedural Memory）

存储的不是"发生了什么"，而是"这件事该怎么做"。

`prompt_builder.py` 的 `build_skills_system_prompt()` 实现了**渐进式披露**架构：

- 默认只加载技能的**名称和摘要**（描述截断到 60 字符）
- 完整内容仅在调用 `skill_view()` 时才读入
- **两层缓存加速**：进程内 LRU + 磁盘快照（mtime/size 指纹校验）

这意味着即便系统积累了上百个技能，每次调用的 Token 成本也不会因此线性上涨。

### 第四层：Honcho 用户建模层

跨会话被动追踪用户的偏好、沟通风格和知识背景，逐步建立个性化的用户模型。不需要用户主动告知，随着使用时间积累自然形成。

`MemoryManager` 的关键设计：
- **只允许一个外部记忆提供者**：防止工具 Schema 膨胀和后端冲突
- **上下文隔离**：记忆内容通过 `<memory-context>` 标签包裹，防止模型将召回内容误认为新的用户输入
- **生命周期钩子**：`on_turn_start` → `prefetch_all` → 处理 → `sync_all` → `on_pre_compress`，完整的记忆同步链路

> **架构师 Mr. Ånand 的评价**："正是这种分层结构真正承担了大部分关键工作。'发生了什么'和'该怎么做'不会混在一起，完整上下文也只会在需要时才加载。这就是它能在不推高 Token 成本的情况下实现扩展的原因。"

---

## 四、技能蒸馏：能力的自主进化

Hermes 的 Skill 系统与其他 Agent 框架最大的不同，在于**技能不需要人工编写**。

`prompt_builder.py` 中的 `SKILLS_GUIDANCE` 指示 Agent：

> *"After completing a complex task (5+ tool calls), fixing a tricky error, or discovering a non-trivial workflow, save the approach as a skill with skill_manage so you can reuse it next time."*

完成一项任务后，Hermes 会自动评估：这套处理流程值得保留吗？如果值得  
，它会把有效的方法提炼出来，写成可复用的 SKILL.md 文件，存入 `~/.hermes/skills/`。

下次遇到类似任务，不用重走流程，直接调用已沉淀的工作流。

**双引擎保障**：
- **引擎一（前台自觉）**：Agent 在执行中主动判断"此方法值得保存"
- **引擎二（后台巡检）**：迭代计数器跨任务累积，达到阈值（默认 10）后自动在守护线程中启动审查 Agent（`max_iterations=8`），分析对话历史提取可结晶经验

技能还具备**自修复能力**：Agent 发现 Skill 过时时，使用模糊匹配引擎就地热补丁，不中断当前任务。

**安全防护**：`tools/skills_guard.py` 实现了 80+ 安全威胁模式检测，结合 4 级信任策略矩阵（builtin/trusted/community/agent-created），确保 Agent 自主创建的 Skill 不包含危险内容。

一个真实案例：有开发者用 Hermes 花 2.5 小时做出了《百战天虫》克隆游戏。整个过程中，Hermes 用了持久 shell 模式、并行子 Agent、`/rollback` 文件系统检查点、CDP 实时 Chrome 调试——完成后，Agent 还**自己把物理引擎逻辑整理成了一个可复用的 skill 插件**。

这是人工驱动的 Skill 系统做不到的。

> 关于技能自学习和热补丁的完整机制分析，参见本系列 [04_HermesAgent 自进化机制](./04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md)。

---

## 五、网关设计：12+ 平台，统一身份

很多 Agent 声称"跨平台"，但切换到另一个终端后上下文依然丢失，因为会话绑定的是具体平台或终端，而非用户。

Hermes 的网关系统解决了这个问题：**会话绑定用户 ID，而非平台**。

`prompt_builder.py` 中的 `PLATFORM_HINTS` 字典定义了 **12 种平台**的专属行为指导：

| 平台类别 | 支持平台 | 特殊能力 |
|---------|---------|---------|
| 即时通讯 | WhatsApp、Telegram、Signal、Discord、Slack | 原生媒体附件（`MEDIA:/path`） |
| 中文生态 | WeChat（微信）、WeCom（企业微信）、QQ | Markdown 支持，企业级文件传输 |
| 其他 | Email、SMS、BlueBubbles（iMessage） | 格式适配（纯文本 vs Markdown） |
| 自动化 | CLI、Cron | 无人值守执行模式 |

在 Telegram 上开启的对话，切换到终端继续，不会丢失任何上下文。再切到微信，依然连续。

网关负责五件事：消息传递、会话路由、内容交付、配对、定时触发。这五件事都在同一个循环里完成，而不是拼凑的外挂模块。

**环境感知**：系统还能检测 WSL 环境并自动注入路径映射指导（`/mnt/c/` = C: 盘），确保工具操作在正确的文件系统路径上执行。

定时自动化任务也作为一级任务集成进来：用户安排定时任务 → 系统解析指令存入 `cron/` 目录 → 到点由网关触发 → Agent 带着完整记忆和技能执行 → 结果推送至指定平台。全程无需人工介入。

---

## 六、安全架构：多层纵深防御

Hermes 不仅扫描 Skill，还在系统提示注入层面做了安全防护。

**上下文文件注入扫描**（`prompt_builder.py`）：

当项目中存在 `.hermes.md`、`HERMES.md`、`.cursorrules` 等上下文文件时，系统会在加载前扫描 10 种提示注入模式：

- `ignore previous instructions`（忽略先前指令）
- `do not tell the user`（对用户隐瞒信息）
- `system prompt override`（系统提示覆盖）
- HTML 隐藏注释/隐藏 div 注入
- `curl` 窃取环境变量中的密钥
- 不可见 Unicode 字符（零宽字符、双向标记等）

发现威胁时，文件内容被替换为 `[BLOCKED: ... contained potential prompt injection]`，而非静默加载。

**Skill 安全层**：80+ 正则模式 × 4 信任等级策略矩阵（详见 04 篇）。

这种多层防御保证了：即使用户在不可信项目中运行 Hermes，Agent 也不会被恶意上下文文件劫持。

---

## 七、部署与成本

**自托管，5 美元 VPS 即可跑起来。**

Hermes 可与 Ollama 深度集成，实现完全本地推理，成本几乎为零。系统提示大多稳定，支持提示缓存，大幅降低后续调用成本。

有用户在 Mac M3 上通过 LM Studio 本地运行 Qwen 3.5-35B，以 OpenRouter 作为备用，Hermes 24 小时持续运行。另一位用户把 Hermes 装在一台始终在线的 Mac mini 上，通过预共享密钥 SSH 访问 Ubuntu 服务器，同时可以从 MacBook SSH 连入，或通过 Telegram 操作——完全不需要多节点部署。

**数据全程本地，无第三方流转，隐私可控。**

---

## 八、Nous Research：开源 AI 的"异类"

Hermes Agent 背后的公司是 Nous Research，一家真正的技术异类。

它由一群通过 Discord、GitHub、Twitter 结识的志愿者在 2022 年组建，2023 年正式成立，四位创始人背景覆盖加密行业、亚马逊生成式 AI、Stability AI。公司目前约 30 人，目标是打造可与 OpenAI、DeepSeek 抗衡的开源 AI 模型。

Hermes 系列模型在 HuggingFace 上的下载量已超 **5000 万次**。团队发表过被 Meta 和 DeepSeek 采用的 YaRN 论文（已被 109 篇学术论文引用）。

去年，Nous Research 完成了一笔特殊的融资：由加密原生风投 Paradigm 领投的 **5000 万美元 A 轮**，估值逼近 10 亿美元。Paradigm 的联合创始人之一，正是 Coinbase 联合创始人 Fred Ehrsam。

为什么一家 AI 公司接受加密风投？因为他们想解决一个根本问题——**大模型训练不能依赖某一家大型企业的心情**。他们在探索用区块链去中心化算力激励机制，实现跨数据中心的全球 GPU 协同训练，任何人都可以贡献闲置算力参与。

> "如果那张 GPU 在加拿大、墨西哥或者其他任何国家，我们就需要一种无需许可的支付方式。加密货币目前就是最好的解决方案。我们只是把加密技术用在它真正适合的地方——解决怎么做出一种真正为所有人服务的开源 AI。" — CEO Jeffrey Quesnelle

---

## 九、适合谁用？

Hermes 不是一个"做完就关"的工具，更像是一套需要持续运行和维护的**个人 AI 基础设施**。

**最适合以下场景：**

- 需要一个 24h 在线、跨 12+ 平台、重启不丢记忆的个人 AI 助理
- 有长期重复性任务，希望 Agent 自主学习并沉淀工作流
- 追求极致成本控制，愿意用本地模型（Ollama）或低成本 API（OpenRouter）
- 需要整合 Gmail、日历、Todoist、Obsidian 等多工具的个人工作流
- 需要在微信/企业微信/QQ/Telegram 等中文生态平台使用 AI 助理

**不适合以下场景：**

- 专业级编码开发与大型工程化项目（这里 Claude Code 仍有不可替代的优势）
- 短生命周期的临时任务
- 多人团队协作、需要角色隔离的场景

---

## 结语

Hermes Agent 的核心价值，不在于它比其他 Agent "功能更多"，而在于它提供了一种**不同的人机关系**：不是你每次调用一个工具，而是你在培养一个越来越了解你的助理。

这种差异，需要时间才能体现。但一旦体现出来，就很难回头。

> 参考资料：
> - [Hermes Agent GitHub](https://github.com/nousresearch/hermes-agent)
> - [Inside Hermes Agent - Mr. Ånand](https://mranand.substack.com/p/inside-hermes-agent-how-a-self-improving)
> - [Nous Research Fortune 报道](https://fortune.com/crypto/2025/04/25/paradigm-nous-research-crypto-ai-venture-capital-deepseek-openai-blockchain/)
> - 关键源码：`run_agent.py`（11K+ 行）、`agent/prompt_builder.py`（1,043 行）、`agent/memory_manager.py`（362 行）、`agent/skill_utils.py`（465 行）
