# VibeBloging — 项目记忆

> 每次重要对话的核心需求、要点与特性浓缩归档。按时间倒序排列。

---

## 2026-04-13 | 美伊冲突事件时间线附录

**新建文件**：`Strategy/GeoPolitical-FX-Sentiment/appendix_美伊冲突事件时间线.md`

**内容覆盖**（多引擎搜集，Yahoo/NPR/Brave/Bing CN 多源交叉验证）：
- 背景期（2024）：以色列空袭大马士革领事馆→伊朗首次直接打击以色列→以色列首次公开空袭伊朗本土
- 2025 年升级：特朗普极限施压 2.0、马斯喀特核谈判、午夜锤行动（2025-06-22 Operation Midnight Hammer）、十二天战争
- 2026 年主战争：史诗怒火行动（2026-02-28 Operation Epic Fury）、哈梅内伊被斩首、霍尔木兹关闭、穆吉塔巴接任
- 停火与破裂：2026-04-07 两周停火→04-08 伊朗宣布胜利→04-09 封锁恢复→04-11/12 伊斯兰堡谈判破裂→04-12 美国封锁宣布
- 油价数据：基准 $72 → 峰值 $119.45 → 停火后 $94.26 → 当前 $100+

**关键事件修正**：战争实际分两阶段（2025-06 + 2026-02），并非单次冲突

---

## 2026-04-13 | 项目整理与 HermesAgent 自进化博客

**Agent/ 目录整理**：12 篇文章统一编号，三大分组——
- Claude Code 系列（01–03）：技术解析、Harness深度解析、Vibe Coding
- Skills 系列（04–06，集中排列）：CC Skills完全指南、AI工作流Skills指南、业务人员实战指南
- Agent框架系列（07–12）：设计方法论、OpenClaw、国内工具调研、开源框架调研、n8n、豆包

**HermesAgent 新博客**：`04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md`
- 基于 materials/HermesAgent/ 原始资料（TXT + PDF + JPEG）
- 核心内容：三种经验积累模式对比、双引擎触发机制（前台自觉+后台巡检）、热补丁自修复、条件激活与安全防护、与 Claude Code Skills 的本质差异
- 关键结论：Skill = 经验演化系统（非静态知识库），越用越强的护城河

**CLAUDE.md 重写**：全量更新，纳入所有当前目录（含 InsightClaudeCode/、LearningClaudeCode/）

---

## 2026-04-10 | InsightClaudeCode 系列（Claude Code 精密拆解）

**新建目录**：`InsightClaudeCode/`（15个文件：1 README + 7 research docs + 7 HTML visualizations）

**覆盖子系统**：四层架构总览、QueryLoop 执行引擎、工具系统（45+）、多 Agent & Worktree、记忆上下文系统、权限安全矩阵、MCP/Hooks/Skills 扩展层

**设计风格**：与 `HermesAgent/images/` 一致（`#030712` 背景、`#3b82f6` Claude蓝、Space Grotesk + JetBrains Mono、glassmorphism + SVG 动画）

**用户提供额外参考仓库**（尚未纳入内容）：
- github.com/zhangbo2008/claude_code_annotated
- github.com/oboard/claude-code-rev
- github.com/shareAI-lab/learn-claude-code

---

## 2026-04-10 | HermesAgent 博客系列

**新增文件**
- `HermesAgent/01_HermesAgent深度解析.md`
- `HermesAgent/02_三款Agent横向对比_ClaudeCode_OpenClaw_HermesAgent.md`

**博客一：Hermes Agent 深度解析**
- 从痛点切入（跨会话失忆 vs Token 爆炸）
- 单 Agent 持久循环架构：输入→推理→工具→记忆→技能蒸馏→输出
- 四层记忆体系：提示记忆（3575字符限制）/ 会话检索（SQLite+FTS5）/ 技能程序性记忆（懒加载）/ Honcho 用户建模
- 技能自动蒸馏：任务完成后自主评估、提炼、写入 ~/.hermes/skills/
- 网关设计：会话绑定用户ID而非平台，跨终端无缝续聊
- 部署：5美元VPS，Ollama 本地推理近零成本
- Nous Research 背景：MIT开源+区块链去中心化训练+Paradigm 5000万美元A轮

**博客二：三款 Agent 横向对比**（2026-04-10 修订：修正 OpenClaw 起源）
- OpenClaw 正确来源：前身为 Clawdbot，由独立开发者 Peter Steinberger 主导创建，后更名为 OpenClaw，与 Claude Code 源码无任何关联（原错误描述为"社区基于 source map 还原 Claude Code"）
- OpenClaw 核心特性：单 Agent 持久循环 + 心跳机制（每小时自检）、Markdown 记忆系统、自动技能生成、WhatsApp/Discord/Telegram IM 接入、Mac mini/VPS 自托管
- 六维对比：定位/架构/记忆/技能/部署成本/能力矩阵
- 核心结论：Claude Code = 编码执行，OpenClaw = 心跳驱动的全天候个人 AI 助理，Hermes = 深度自主进化的个人管家
- 最优实践：Hermes 作全局中枢统筹调度，Claude Code 承接专业编码执行

---

## 2026-04-10 | 项目 CLAUDE.md 初始化

**操作**：运行 `/init`，分析整个仓库结构，生成 `CLAUDE.md`

**CLAUDE.md 涵盖内容**
- 项目性质（无构建/测试系统，文档优先）
- 目录结构与各模块用途
- 工作约定（memory/log 更新规范、博客编号规则）
- Skills 框架说明（位置、结构、现有四个 Skill）
- 量化领域背景知识（NSIF 公式、时间衰减参数、IC 阈值）

---

## 2026-03-25 | AiweQuant 第二篇博客

**主题**：资讯流驱动的外汇与贵金属量化策略构建实践（独立完整博客）
**文件**：`AiweQuant/02_资讯流外汇贵金属策略构建实践.md`

**新增内容（E+F）**
- E. 策略构建：信号加权合成（IC滚动权重）、开平仓规则（信号阈值+时间止损双触发）、ATR归一化仓位、不设固定止盈
- F. 参数寻优：网格搜索 + 敏感性热力图可视化、Walk-Forward滚动验证、邻域稳定性检验、多目标评分
- 核心经验：敏感性>最优性；λ要与资讯类型绑定；参数更新频率不能太高

**用户实际工程细节**
- 策略构建基于内部回测框架
- 参数寻优：网格搜索 + 参数敏感性可视化分析参数稳健性

---

**主题**：AI Agent 如何赋能资讯流策略研发
**投资标的**：G10 外汇 + XAU/XAG 贵金属
**文件**：`AiweQuant/01_AIAgent赋能资讯流策略研发.md`

**策略构建全流程（用户实际做法）**
- A. 数据分析：时序量分布、分类统计、数据质量基线
- B. LLM结构化提取：keywords、logic_tags、direction/impact/confidence（per asset）、novelty
- C. 因子构建两条路径：
  - 路径一 NSIF（Net Sentiment Intensity Factor）= 方向×强度×置信度×来源权重×时间衰减，按 logic_tag 拆维度
  - 路径二 LLM时态预测：聚类→时间线→第一性原理推演→蒙特卡洛情景采样→期望影响因子
- D. 因子检验：相关性、领先滞后分析、IC/ICIR（>0.05/0.5）、分层回测、时间稳定性

**关键技术细节**
- 时间衰减：硬数据λ大（半衰期1-4h）；地缘政治λ小（半衰期12-72h）；研报最慢（3-7天）
- LLM置信度需做 Platt Scaling 校准（原始评分系统性偏高）
- 路径一适合高频回测；路径二适合重大事件演化预判，两者互补

**博客关键结论**
> "AI Agent 不是替代量化研究员，而是将研究员精力从重复执行解放到创造性假设。"

---

## 2026-03-25 | 项目初始化

**核心需求**
- 编写、归纳存档技术博客，借助 AI 实现"氛围写博客"（vibe blogging）

**目录规划**
- `_project/` — 项目管理文件（memory、log、规范）
- `AiweQuant/` — AI/Agent 在量化投研领域的应用博客

**工作约定**
- 每次重要对话需将关键内容、核心需求、要点和特性浓缩整理到本文件
- log 文件记录操作历史

---
