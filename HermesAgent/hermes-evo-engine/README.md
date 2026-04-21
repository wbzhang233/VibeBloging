# HermesAgent Self-Evolution Engine

> 基于 [AgentScope](https://github.com/agentscope-ai/agentscope) + FastAPI + TDSQL 的自进化智能体系统，
> 实现 Skill 自学习、热补丁自修复、条件激活与安全防护机制。

本项目是 [HermesAgent 自进化机制](../04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md) 博客文章的完整代码实现，参照 [HermesAgent 开源仓库](https://github.com/nousresearch/hermes-agent) 源码架构设计。

---

## 技术栈

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 语言 | Python | 3.11+ | 核心语言 |
| Web 框架 | FastAPI | ≥0.115.0 | REST API + Swagger UI |
| 智能体框架 | AgentScope | ≥0.1.0 | ReActAgent + Toolkit |
| 数据库 | TDSQL (MySQL兼容) | 8.0+ | 元数据持久化、补丁历史 |
| 缓存 | Redis | ≥7.0 | 迭代计数器、任务队列 |
| ORM | SQLAlchemy (Async) | ≥2.0 | 异步数据库操作 |
| DB 驱动 | aiomysql | ≥0.2.0 | TDSQL/MySQL 异步驱动 |
| 配置 | Pydantic Settings | ≥2.7.0 | 环境变量注入 |
| 容器 | Docker + Compose | — | 本地开发环境 |
| 编排 | Kubernetes + Kustomize | — | 生产部署 |
| 多集群 | Submariner | — | 跨集群 Service 发现 |
| 测试 | Pytest + pytest-asyncio | — | 单元/集成测试 |

---

## 核心架构

```
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI REST API                          │
│   /skills(6操作)  /agents  /review  /metrics  /health         │
└──────────────┬──────────────────────┬───────────────────────┘
               │                      │
    ┌──────────▼──────────┐    ┌──────▼───────┐
    │    Skill Manager    │    │  Agent Pool   │
    │  6种操作 + 原子写入   │    │  并发任务执行   │
    │  模糊匹配热补丁      │    │              │
    │  Frontmatter校验    │    │              │
    └──────────┬──────────┘    └──────┬───────┘
               │                      │
    ┌──────────▼──────────────────────▼──────┐
    │         Dual Engine Learner             │
    │                                         │
    │  Engine 1: 前台自觉                      │
    │    Agent 主动创建 Skill → 计数器归零       │
    │                                         │
    │  Engine 2: 后台巡检 (threading.Thread)    │
    │    迭代计数器按循环迭代累积（非工具调用）     │
    │    跨任务不重置 → 达阈值触发               │
    │    ReviewAgent (max_iterations=8)        │
    │    _COMBINED_REVIEW_PROMPT 联合审查       │
    └─────────────┬───────────────────────────┘
                  │
    ┌─────────────▼────────────────────────────┐
    │         Safety & Activation               │
    │                                           │
    │  安全扫描: 76+ 模式 / 10 类别             │
    │  信任等级: builtin/trusted/community/      │
    │           agent-created                   │
    │  INSTALL_POLICY 策略矩阵                  │
    │                                           │
    │  条件激活: 4 维过滤                        │
    │  fallback_for_toolsets / requires_toolsets │
    │  fallback_for_tools / requires_tools      │
    └─────────────┬───────────────────────────┘
                  │
    ┌─────────────▼───────────┐
    │  AgentScope               │
    │  ReActAgent + Toolkit     │
    │  + skill_manage 工具      │
    │  + SKILLS_GUIDANCE 注入   │
    └───────────────────────────┘
```

---

## 核心概念

### 1. 双引擎自学习

**Engine 1 — 前台自觉 (Proactive Learning)**

Agent 在执行任务过程中，发现非显而易见的有效方法时，主动调用 `skill_manage(action='create')` 创建 Skill。此时迭代计数器归零。

**Engine 2 — 后台巡检 (Background Inspection)**

每完成一次 Agent **循环迭代**（非工具调用），计数器递增。计数器**跨任务不重置**：

```
任务1（复杂代码审计）：8 次循环迭代 → _iters_since_skill = 8
任务2（简单查询）：    3 次循环迭代 → _iters_since_skill = 11
触发！后台巡检启动（阈值默认 10，可配置）
```

巡检在 **`threading.Thread(daemon=True)`** 中运行，使用独立 ReviewAgent（`max_iterations=8`，`quiet_mode=True`）。支持两种审查模式：

- `_SKILL_REVIEW_PROMPT`：纯技能审查
- `_COMBINED_REVIEW_PROMPT`：记忆+技能联合审查

**关键洞察**：只有包含绕路、犯错、迭代修正的经验才会被结晶为 Skill——**挫折才是最好的老师**。

### 2. Skill 管理——六大操作

| 操作 | 用途 | 关键特性 |
|------|------|---------|
| `create` | 创建新 Skill | 支持 `category` 分类目录 |
| `edit` | 完整重写 SKILL.md | 全文替换 |
| `patch` | 精准热补丁 | **模糊匹配引擎**（容忍空白/缩进差异） |
| `delete` | 删除 Skill | 清理空分类目录 |
| `write_file` | 写入辅助文件 | 限 references/templates/scripts/assets/ |
| `remove_file` | 删除辅助文件 | 同上 |

**安全保障**：
- 所有写入使用**原子操作**（tempfile + `os.replace()`）
- 每次修改后自动**安全扫描**，不通过则回滚
- Frontmatter 校验（必须包含 `name` + `description`）
- 大小限制：SKILL.md ≤ 100K 字符，辅助文件 ≤ 1 MiB

### 3. 条件激活——四维过滤

| 规则 | 示例 | 行为 |
|------|------|------|
| `fallback_for_toolsets: [web]` | duckduckgo-search | 主工具集可用时隐藏备用 |
| `fallback_for_tools: [web-search]` | duckduckgo-search | 主工具可用时隐藏备用 |
| `requires_toolsets: [web]` | deep-research | 依赖工具集缺失时隐藏 |
| `requires_tools: [web-fetch]` | deep-research | 依赖工具缺失时隐藏 |

### 4. 安全扫描——76+ 模式 × 10 类别

| 类别 | 代表性模式 | 严重级别 |
|------|-----------|---------|
| credential_exposure | 硬编码 API keys、密码 | critical |
| exfiltration | curl/wget 泄露环境变量、DNS 外泄 | critical/high |
| injection | ignore previous instructions、role hijack | critical/high |
| destructive | rm -rf /、chmod 777、DROP TABLE | critical |
| execution | eval()、exec()、os.system() | high |
| persistence | .bashrc 修改、crontab 注入 | high |
| network | 反向 shell、端口转发 | critical |
| obfuscation | base64 编码执行、不可见 Unicode | high/medium |
| traversal | ../../ 路径穿越 | high |
| supply_chain | 可疑 pip/npm install | medium |

**信任等级策略矩阵**：

```python
INSTALL_POLICY = {
    #                  safe      caution    dangerous
    "builtin":       ("allow",  "allow",   "allow"),
    "trusted":       ("allow",  "allow",   "block"),
    "community":     ("allow",  "block",   "block"),
    "agent-created": ("allow",  "allow",   "ask"),
}
```

**结构性检查**：文件数量/大小限制、二进制文件检测、符号链接检测、不可见 Unicode 字符检测。

---

## 快速开始

### 前置要求

- Python 3.11+
- Docker & Docker Compose（本地开发）
- kubectl + kustomize（K8s 部署）

### 方式一：Docker Compose（推荐本地开发）

```bash
cd hermes-evo-engine

# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key

# 2. 启动服务（API + TDSQL + Redis）
docker-compose up -d

# 3. 访问 Swagger UI
open http://localhost:8000/docs
```

### 方式二：本地直接运行

```bash
cd hermes-evo-engine

# 1. 安装依赖
pip install -e ".[dev]"

# 2. 确保 TDSQL/MySQL 和 Redis 已启动
# 3. 配置 .env

# 4. 启动 API
uvicorn hermes_evo.api.app:app --reload --host 0.0.0.0 --port 8000
```

### 方式三：Kubernetes 部署

```bash
# 开发环境（单副本，最小资源）
kubectl apply -k k8s/overlays/dev/

# 生产环境（多副本，HPA，PDB）
kubectl apply -k k8s/overlays/production/

# 多集群联邦
# 1. 控制面集群
kubectl apply -f k8s/federation/control-plane.yaml
# 2. Worker 集群
kubectl apply -f k8s/federation/worker-cluster-join.yaml
```

---

## API 参考

完整 Postman 集合：[`docs/hermes-evo-api.postman_collection.json`](docs/hermes-evo-api.postman_collection.json)（可直接导入 Postman）

### Skills — 6 种操作

```bash
# 创建 Skill（支持分类目录）
curl -X POST http://localhost:8000/skills \
  -H "Content-Type: application/json" \
  -d '{
    "name": "git-rebase-workflow",
    "description": "Safe git rebase workflow with conflict resolution",
    "content": "---\nname: git-rebase-workflow\ndescription: Safe rebase\n---\nStep 1: git fetch...",
    "tags": ["git", "workflow"],
    "category": "devops"
  }'

# 列出 Skill（带过滤）
curl "http://localhost:8000/skills?status=active&tag=git&safety_level=safe"

# 热补丁（模糊匹配）
curl -X PATCH http://localhost:8000/skills/{skill_id} \
  -H "Content-Type: application/json" \
  -d '{
    "old_string": "git rebase origin/main",
    "new_string": "git rebase --autosquash origin/main",
    "reason": "Added autosquash for cleaner history"
  }'

# 废弃 Skill（软删除）
curl -X DELETE http://localhost:8000/skills/{skill_id}
```

### Agents — 任务执行

```bash
# 提交任务（异步）
curl -X POST http://localhost:8000/agents/execute \
  -H "Content-Type: application/json" \
  -d '{"instruction": "Analyze the auth module", "context": {"lang": "python"}}'

# 查询 Agent 池状态
curl http://localhost:8000/agents/status

# 获取任务结果
curl http://localhost:8000/agents/tasks/{task_id}
```

### Review — 后台巡检

```bash
# 手动触发巡检
curl -X POST http://localhost:8000/review/trigger \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "agent-1", "conversation_history": [...]}'

# 查看巡检历史
curl "http://localhost:8000/review/history?limit=20"
```

### Metrics — 系统指标

```bash
curl http://localhost:8000/metrics
```

---

## K8s 多集群架构

```
Control Plane Cluster              Worker Cluster(s)
┌───────────────────┐              ┌─────────────────┐
│ API Gateway (HPA) │              │ Worker Agent ×N  │
│   2-8 replicas    │              │   2-20 replicas  │
│                   │              │                  │
│ Skill Manager     │◄────────────►│ (连接控制面       │
│   1 replica       │  Submariner   │  Redis + TDSQL) │
│                   │  ServiceExport│                  │
│ Review Agent      │              └─────────────────┘
│   1 replica       │
│                   │              ┌─────────────────┐
│ TDSQL (PVC)       │              │ Worker Agent ×N  │
│ Redis (AOF)       │◄────────────►│ (另一个集群)      │
└───────────────────┘              └─────────────────┘
```

**Pod 角色分工**：

| Pod | 副本数 | 职责 | 特点 |
|-----|--------|------|------|
| API Gateway | 2-8 (HPA) | 接收请求，路由到各服务 | 无状态，水平扩展 |
| Skill Manager | 1 (Singleton) | Skill 存储与管理 | 有状态，PVC 持久化 |
| Review Agent | 1 | 后台巡检（Engine 2 执行体） | LLM 密集型 |
| Worker Agents | 2-20 (HPA) | 执行 Agent 任务 | 无状态，按需扩缩 |
| TDSQL | 1 (StatefulSet) | 元数据持久化 | 20Gi PVC，MySQL 兼容 |
| Redis | 1 | 迭代计数器 + 任务队列 | AOF 持久化 |

**多集群通信**：使用 [Submariner](https://submariner.io/) 的 ServiceExport/ServiceImport 实现跨集群 Service 发现。

---

## 项目结构

```
hermes-evo-engine/
├── src/hermes_evo/
│   ├── config.py                  # Pydantic Settings（HERMES_ 前缀）
│   ├── models/                    # Pydantic 数据模型
│   │   ├── skill.py               # SkillMetadata + 4维条件 + category
│   │   ├── agent.py               # AgentTask, ExecutionRecord
│   │   └── review.py              # ReviewResult, LearningCandidate
│   ├── core/                      # ★ 核心业务逻辑
│   │   ├── skill_manager.py       # 6种操作 + 模糊匹配 + 原子写入
│   │   ├── skill_store.py         # 双写持久化（TDSQL + 文件系统）
│   │   ├── dual_engine.py         # ★ 双引擎（含 threading + COMBINED_REVIEW）
│   │   ├── review_agent.py        # ★ 后台巡检 Agent（max_iterations=8）
│   │   ├── conditional_activation.py  # 4维条件过滤
│   │   ├── safety_scanner.py      # 76+ 模式 × 10 类别 × 4 信任等级
│   │   └── iteration_tracker.py   # Redis 跨任务计数器
│   ├── agents/                    # AgentScope 集成
│   │   ├── hermes_react_agent.py  # ★ 自进化 ReActAgent
│   │   ├── skill_tools.py         # SKILLS_GUIDANCE + skill_manage
│   │   ├── worker_agent.py        # Worker 任务执行
│   │   └── agent_pool.py          # Agent 并发池
│   ├── api/                       # FastAPI REST API
│   │   ├── app.py                 # 应用工厂 + lifespan
│   │   ├── schemas.py             # 请求/响应 Schema
│   │   ├── dependencies.py        # 依赖注入
│   │   └── routers/               # skills, agents, review, metrics
│   └── infra/                     # 基础设施
│       ├── database.py            # Async SQLAlchemy + aiomysql
│       └── redis_client.py        # Redis 连接
├── docs/                          # 文档
│   ├── 需求分析设计文档.md          # 完整需求/架构设计
│   └── hermes-evo-api.postman_collection.json  # API 集合
├── k8s/                           # Kubernetes 部署
│   ├── base/                      # Kustomize base（含 TDSQL）
│   ├── overlays/                  # dev / staging / production
│   └── federation/                # 多集群联邦
├── tests/                         # 测试套件
├── Dockerfile                     # 多阶段构建
├── docker-compose.yml             # TDSQL + Redis + API
└── pyproject.toml                 # aiomysql + agentscope + fastapi
```

---

## 配置参考

所有配置通过环境变量注入，前缀 `HERMES_`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HERMES_MODEL_NAME` | `qwen-max` | LLM 模型名 |
| `HERMES_MODEL_API_KEY` | — | LLM API Key |
| `HERMES_DATABASE_URL` | `mysql+aiomysql://hermes:hermes@localhost:3306/hermes` | TDSQL 连接串 |
| `HERMES_REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `HERMES_REVIEW_THRESHOLD` | `10` | 后台巡检触发阈值（循环迭代数） |
| `HERMES_MAX_AGENT_ITERS` | `20` | 单任务最大推理迭代 |
| `HERMES_AGENT_POOL_SIZE` | `5` | Agent 并发池大小 |
| `HERMES_SAFETY_SCAN_ENABLED` | `true` | 安全扫描开关 |
| `HERMES_SKILL_STORE_PATH` | `./skill_store` | Skill 文件存储路径 |
| `HERMES_LOG_LEVEL` | `INFO` | 日志级别 |

---

## 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部测试
pytest tests/ -v

# 运行特定模块
pytest tests/test_safety_scanner.py -v      # 76+ 安全模式测试
pytest tests/test_conditional_activation.py -v  # 4维条件激活
pytest tests/test_dual_engine.py -v         # 双引擎 + 计数器逻辑
pytest tests/test_skill_manager.py -v       # 6种操作 + 热补丁
pytest tests/test_api_skills.py -v          # API 集成测试

# 带覆盖率
pytest tests/ --cov=hermes_evo --cov-report=term-missing
```

---

## 设计决策

### 为什么选择 AgentScope？

| 特性 | AgentScope | LangGraph | CrewAI |
|------|-----------|-----------|--------|
| ReActAgent 内置 | 是 | 否 | 否 |
| Toolkit 工具注册 | 原生支持 | 需适配 | 有限 |
| 异步原生 | 全链路 async | 部分 | 否 |
| MCP 集成 | 支持 | 支持 | 否 |
| 生产部署 | K8s/Docker | 未定义 | 未定义 |
| 阿里云生态 | 深度集成 | 无 | 无 |

### 为什么 TDSQL 而非 PostgreSQL？

- **腾讯云原生**：TDSQL 是腾讯自研分布式 SQL 引擎，兼容 MySQL 协议
- **水平扩展**：支持自动分片，适合大规模 Skill 存储场景
- **生态兼容**：使用标准 `aiomysql` 驱动，迁移成本低
- **双写兼容**：JSON 列类型存储补丁历史，与文件系统 YAML 格式互补

### 为什么双写（TDSQL + 文件系统）？

- **TDSQL**：结构化查询、过滤、统计、JSON 存储补丁历史
- **文件系统**：人类可读、Git 版本控制、YAML frontmatter 与 SKILL.md 格式兼容

### 为什么 Redis 存储迭代计数器？

- 跨 Pod 共享（多个 Worker Agent 共享同一 Agent 的计数器）
- 跨重启持久化（AOF 模式）
- 原子递增操作（INCR）
- 自带 TTL 防止孤立计数器泄漏（7 天过期）

---

## 与源码的对应关系

本项目的核心设计均参照 HermesAgent 开源仓库源码实现：

| 本项目模块 | 对应源码文件 | 行数 |
|-----------|------------|------|
| `core/dual_engine.py` | `run_agent.py` (计数器 + 后台审查) | 11K+ |
| `core/review_agent.py` | `run_agent.py` (_SKILL_REVIEW_PROMPT) | — |
| `core/skill_manager.py` | `tools/skill_manager_tool.py` | 761 |
| `core/safety_scanner.py` | `tools/skills_guard.py` | 928 |
| `core/conditional_activation.py` | `agent/skill_utils.py` + `prompt_builder.py` | 465 + 1043 |
| `agents/skill_tools.py` | `agent/prompt_builder.py` (SKILLS_GUIDANCE) | — |

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [需求分析设计文档](docs/需求分析设计文档.md) | 完整需求分析、架构设计、数据模型、部署方案 |
| [Postman API 集合](docs/hermes-evo-api.postman_collection.json) | 12 个接口，可直接导入 Postman |
| [04_自进化机制](../04_HermesAgent自进化机制：Skill自学习与自修复架构深度解析.md) | 双引擎学习、热补丁、安全扫描深度解析 |
| [01_深度解析](../01_HermesAgent深度解析.md) | 单 Agent 持久循环、记忆架构、网关设计 |

---

## License

MIT
