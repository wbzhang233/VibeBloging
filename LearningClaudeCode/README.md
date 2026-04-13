# InsightClaudeCode — Claude Code 精密拆解与可视化

> 系列创建日期：2026-04-10
> 信息截止：2026-03
> 风格：深色赛博朋克 + CSS 3D + SVG 动画流（与 HermesAgent/images/ 保持一致）

---

## 系列简介

本系列对 Claude Code 进行工程级深度拆解，覆盖所有核心子系统。每个子系统对应一篇结构化的 research 文档（技术脚本）和一个自包含的可视化 HTML（交互图表）。

---

## 快速导航

### research/ — 技术文档

| 文件 | 主题 | 核心内容 |
|------|------|---------|
| [01_架构总览.md](research/01_架构总览.md) | 四层体系架构 | 组件清单、层级职责、启动序列 |
| [02_QueryLoop详解.md](research/02_QueryLoop详解.md) | 执行引擎 | 伪代码、状态机、上下文压缩 |
| [03_工具系统.md](research/03_工具系统.md) | 45+工具全景 | 分类清单、执行管道、Bash模式 |
| [04_多Agent与Worktree.md](research/04_多Agent与Worktree.md) | 多 Agent 编排 | 协调机制、worktree 隔离、SendMessage |
| [05_记忆与上下文.md](research/05_记忆与上下文.md) | 记忆系统 | 四层记忆、Prompt Cache、压缩策略 |
| [06_权限安全.md](research/06_权限安全.md) | 权限安全模型 | 四级层级、高危拦截、Plan Mode |
| [07_MCP_Hooks_Skills.md](research/07_MCP_Hooks_Skills.md) | 扩展层三件套 | MCP 协议、Hooks 事件点、Skills 懒加载 |

### images/ — 可视化图表

| 文件 | 标题 | 内容摘要 |
|------|------|---------|
| [00_全景架构蓝图.html](images/00_全景架构蓝图.html) | 全景架构蓝图 | 四层架构竖向堆叠，3D 透视，启动时序 |
| [01_QueryLoop执行引擎.html](images/01_QueryLoop执行引擎.html) | QueryLoop 执行引擎 | 环形 Loop 动画，伪代码同步高亮 |
| [02_工具执行流水线.html](images/02_工具执行流水线.html) | 工具执行流水线 | 45+工具全景，管道动画，调用量气泡图 |
| [03_多Agent_Worktree编排.html](images/03_多Agent_Worktree编排.html) | 多 Agent & Worktree 编排 | 并行子代理，worktree 隔离，摘要汇聚 |
| [04_记忆上下文系统.html](images/04_记忆上下文系统.html) | 记忆上下文系统 | 四层同心圆，容量槽，目录树 |
| [05_权限安全矩阵.html](images/05_权限安全矩阵.html) | 权限安全矩阵 | 同心矩形，高危拦截，热力图 |
| [06_MCP_Hooks_Skills扩展层.html](images/06_MCP_Hooks_Skills扩展层.html) | MCP / Hooks / Skills 扩展层 | 三栏并列，JSON-RPC，懒加载金字塔 |

---

## 推荐阅读路径

### 初次了解 Claude Code
```
00_全景架构蓝图 → 01_架构总览 → 01_QueryLoop执行引擎
```

### 深入工具与 Agent
```
02_工具执行流水线 → 03_工具系统 → 03_多Agent_Worktree编排 → 04_多Agent与Worktree
```

### 理解扩展与安全
```
05_权限安全矩阵 → 06_权限安全 → 06_MCP_Hooks_Skills扩展层 → 07_MCP_Hooks_Skills
```

### 上下文与记忆管理
```
04_记忆上下文系统 → 05_记忆与上下文
```

---

## 信息来源

- `Agent/claudecode-technical-analysis.md` — 四层架构、工具系统、命令体系、Context 管理
- `Agent/function-call-mcp-tools-skills-agent-harness.md` — Tool Use 协议、Harness 架构、Multi-Agent、Skills 框架
- `HermesAgent/CC与HermesAgent对比/ClaudeCode与HermesAgent的对比_5.txt` — 内存系统、网关设计、会话绑定、技能生成
