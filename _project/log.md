# VibeBloging — 操作日志

| 时间 | 操作 | 备注 |
|------|------|------|
| 2026-03-25 | 项目初始化 | 创建 README.md、_project/memory.md、_project/log.md、AiweQuant/ |
| 2026-03-25 | AiweQuant 第一篇博客 | 01_AIAgent赋能资讯流策略研发.md，G10外汇+贵金属资讯流策略 |
| 2026-03-25 | 博客第一部分细化 | 补充 Step A-D 详细流程：LLM结构化抽取Schema、NSIF公式、时态预测、因子检验框架 |
| 2026-03-25 | 新建第二篇博客 | 02_资讯流外汇贵金属策略构建实践.md，完整A-F六步框架，补充E策略构建+F参数寻优 |
| 2026-03-25 | 第二篇博客大幅扩充 | 数据分析补全5类方法；C因子扩展至9类；F参数寻优补充Optuna/QuantStats/vectorbt等开源框架 |
| 2026-03-25 | 博客补充可视化+Agent章节 | 新增Mermaid流程图/数据流图/思维导图；G章节：10类Skills定义+双模态Agent架构+人机协同节点 |
| 2026-03-30 | 新建 Skills 完全指南 | Agent/claude-code-skills-complete-guide.md；覆盖定义/原理/创建方法/写作范式/常见误区/业务流程Skill化指南（含粒度判断框架和三类业务模板） |
| 2026-03-30 | Skills 指南补充第八章 | 新增"用 Skill-Creator Agent 创建技能"章节：HITL原则/角色分工/提问指南/五阶段对话框架/完整对话示例/卡点解法/生命周期管理 |
| 2026-03-30 | 新建去平台化版 Skills 指南 | Agent/ai-workflow-skills-guide.md；基于 claude-code-skills-complete-guide.md，淡化 Claude Code 绑定，改为通用 AI 工作流 Skill 设计范式，适合面向业务人员推广 |
| 2026-03-30 | 新建债券因子挖掘 Skill | AiweQuant/skills/bond-factor-miner/；面向资产负债管理部司库量化策略研究，含 SKILL.md + 3个知识库文档 + 6个Python脚本；完整覆盖 EDA→预处理→因子构建→因子检验→报告生成全流程，Plotly可视化，输出 .md+.docx 双格式报告 |
| 2026-04-10 | 初始化 CLAUDE.md | 运行 /init 分析仓库结构，生成根目录 CLAUDE.md；涵盖项目性质、目录说明、工作约定、Skills 框架、量化领域背景知识 |
| 2026-04-10 | 更新 _project/memory.md & log.md | 补录本次对话记录 |
| 2026-04-10 | 新建 HermesAgent 深度解析博客 | HermesAgent/01_HermesAgent深度解析.md；覆盖架构/四层记忆/技能蒸馏/网关/部署/Nous Research背景 |
| 2026-04-10 | 新建三款Agent横向对比博客 | HermesAgent/02_三款Agent横向对比_ClaudeCode_OpenClaw_HermesAgent.md；六维对比+能力矩阵+选型建议 |
| 2026-04-10 | 更新 _project/memory.md & log.md | 补录 HermesAgent 博客系列记录 |
| 2026-04-10 | 修订 02_三款Agent横向对比博客 | 修正 OpenClaw 起源：前身为 Clawdbot，独立开发者 Peter Steinberger 主导，非 Claude Code 衍生；重写架构/记忆/技能/部署/选型建议等全部 OpenClaw 相关内容 |
| 2026-04-10 | 新建 InsightClaudeCode 系列 | InsightClaudeCode/；7个 research 文档 + 7个 HTML 可视化（全景蓝图/QueryLoop/工具流水线/多Agent-Worktree/记忆系统/权限矩阵/MCP-Hooks-Skills）；深色赛博朋克风格，与 HermesAgent/images/ 一致 |
| 2026-04-10 | 新建 HermesAgent/images/ 可视化图表系列 | 共5个 HTML 架构图：00全景对比/01_ClaudeCode多Agent架构/02_OpenClaw心跳架构/03_HermesAgent记忆进化架构/04_三框架记忆系统对比；深色赛博朋克风格，含 SVG 动画流、glassmorphism、CSS 3D 效果；博客末尾已添加图表索引 |
| 2026-04-13 | 整理 Agent/ 目录博客编号 | 12 篇文章统一重命名添加数字前缀；Skills 系列（04-06）集中排列；三大分组：Claude Code系列(01-03) / Skills系列(04-06) / Agent框架系列(07-12) |
| 2026-04-13 | 新建 HermesAgent 自进化机制博客 | HermesAgent/04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md；基于 materials/HermesAgent 原始资料；覆盖双引擎触发、热补丁自修复、条件激活与安全防护 |
| 2026-04-13 | 重写 CLAUDE.md | 全量更新目录说明，纳入 InsightClaudeCode/、LearningClaudeCode/、Agent/ 编号体系；修复所有 Markdown lint 告警 |
