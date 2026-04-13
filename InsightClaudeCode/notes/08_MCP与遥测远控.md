# MCP 与遥测远控 — 深度研究笔记

> 来源: src/services/mcp/types.ts + docs/zh/01-遥测 + docs/zh/04-远程控制

---

## MCP（Model Context Protocol）架构

### 协议层

```
Claude Code (MCP Client)
  │
  │ JSON-RPC 2.0
  ▼
Transport Layer（传输层）:
  ├── stdio      → 子进程通信（本地工具）
  ├── sse        → Server-Sent Events（本地SSE服务器）
  ├── sse-ide    → IDE集成专用SSE
  ├── http       → HTTP请求（远程服务）
  ├── ws         → WebSocket（双向实时）
  └── sdk        → Anthropic SDK集成（特殊）
  │
  ▼
MCP Server（外部能力提供商）
  │
  ▼
三种能力类型:
  ├── Tools     → 可调用函数（模型主动调用）
  ├── Resources → URI寻址的可读数据
  └── Prompts   → 可参数化的提示模板
```

### 配置作用域（ConfigScope）

```typescript
enum ConfigScope {
  local      = 'local',      // 本机专属，不共享
  user       = 'user',       // 用户级 (~/.claude/)
  project    = 'project',    // 项目级 (.claude/)，可提交git
  dynamic    = 'dynamic',    // 运行时动态添加
  enterprise = 'enterprise', // 企业级管控
  claudeai   = 'claudeai',   // claude.ai 平台
  managed    = 'managed',    // 远程托管配置
}
```

### OAuth / XAA（跨应用访问）

```typescript
McpOAuthConfigSchema:
  - XAA (Cross-App Access): 允许不同应用间的MCP访问
  - OAuth 2.0 标准认证流程
  - McpAuthTool 工具处理认证
```

### 能力路由（CapabilityRoute）

```
tool_name 前缀判断:
  "mcp__server__tool"  → MCP工具（路由到对应Server）
  "bash"               → 本地工具
  "agent"              → 子代理
  "task_create"        → 任务系统
```

---

## 遥测系统（双管道）

### 第一方遥测（1P）

```
Claude Code → OpenTelemetry → api.anthropic.com

特点:
  - 200 events/batch，10s flush 周期
  - 第一方遥测无法被用户禁用（直接API用户）
  - OTEL_LOG_TOOL_DETAILS=1 启用完整工具输入日志
  - 仓库URL通过 SHA256 哈希后上报

数据包含:
  - 工具使用统计
  - 会话元数据
  - 性能指标
  - 错误事件
```

### 第三方遥测（3P）

```
Claude Code → Datadog

特点:
  - 64种批准事件类型
  - 只发送已审核的特定事件
  - 不包含对话内容

数据包含:
  - 64种预定义事件（功能使用、错误类型等）
```

### 环境指纹

```
上报内容（部分哈希处理）:
  - 操作系统类型/版本
  - Node.js版本
  - 终端类型
  - 仓库URL（SHA256哈希）
  - 工作目录哈希
```

---

## 远程控制基础设施

### 远程设置轮询

```
每小时轮询一次: /api/claude_code/settings

流程:
  1. GET /api/claude_code/settings
  2. 最多重试5次
  3. 如果用户拒绝新设置:
     gracefulShutdownSync(1)  ← 优雅退出
```

### GrowthBook 功能开关（Kill Switches）

```typescript
// 紧急kill switches（可远程触发）
bypassPermissionsKillswitch  → 绕过权限检查（紧急关闭）
autoModeCircuitBreaker       → 自动模式断路器
fastMode                     → 快速模式（penguin mode）
sinkKillswitch               → tengu_frond_boric（流量沉底）
voiceMode                    → tengu_amber_quartz_disabled（语音关闭）
```

### 模型覆盖

```
tengu_ant_model_override → 远程强制切换模型版本
  可用于紧急降级或A/B测试
```

---

## Feature Gates 完整列表（Statsig + GrowthBook）

```
Statsig (功能门控):
  COORDINATOR_MODE          → Coordinator/Worker双模架构
  BASH_CLASSIFIER           → Bash危险性ML分类器
  TRANSCRIPT_CLASSIFIER     → 对话内容分类器
  HISTORY_SNIP              → snipCompact压缩策略
  REACTIVE_COMPACT          → reactiveCompact压缩策略
  CONTEXT_COLLAPSE          → contextCollapse极端压缩
  EXPERIMENTAL_SKILL_SEARCH → Skill语义搜索引擎
  TEMPLATES                 → AutoDream/PromptSuggestion/JobClassifier
  BG_SESSIONS               → 后台持久会话
  tengu_scratch             → scratchpadDir共享知识目录
  EXTRACT_MEMORIES          → 自动记忆提取
  TEAMMEM                   → 团队共享Memory
  KAIROS                    → Brief工具支持（任务简报）
  KAIROS_BRIEF              → Brief工具别名

GrowthBook (远程配置):
  bypassPermissionsKillswitch  → 权限绕过（紧急）
  autoModeCircuitBreaker       → 自动模式断路器
  fastMode                     → 快速模式
  sinkKillswitch               → 流量沉底
  voiceMode                    → 语音模式禁用
  tengu_ant_model_override     → 模型版本覆盖
```

---

## MCP 能力层次（s19a 框架）

```
Layer 1: Connection（连接层）
  - 建立 JSON-RPC 通信信道
  - 处理认证（OAuth/XAA）

Layer 2: Capability（能力层）
  - 工具注册：Tools
  - 资源注册：Resources
  - 提示注册：Prompts

Layer 3: Context（上下文层）
  - 工具上下文注入到 ToolUseContext.mcp_clients
  - 工具调用路由：mcp__server__tool → 对应客户端

Layer 4: Lifecycle（生命周期层）
  - 启动时建立连接
  - 会话结束时清理
  - 动态添加/移除（dynamic scope）
```

---

## Budget Tracking（预算追踪）

```typescript
QueryEngineConfig.maxBudgetUsd   → USD上限（可选）
QueryEngineConfig.taskBudget     → BudgetTracker实例

getCurrentTurnTokenBudget()      → 获取当前轮次token预算
createBudgetTracker()            → 创建预算跟踪器

预算耗尽时:
  → 模型提示预算不足
  → 可能中止当前任务
  → 用户收到通知
```

---

## SessionStorage（会话持久化）

```typescript
recordTranscript()         → 记录完整对话记录
flushSessionStorage()      → 刷新到磁盘
recordContentReplacement() → 记录内容替换操作（压缩时）

存储路径:
  .claude/transcripts/{session-id}.jsonl
```
