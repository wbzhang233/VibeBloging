# HermesAgent 自进化机制：Skill 自学习与自修复架构深度解析

> **作者注**：本文基于 HermesAgent 开源仓库源码（`run_agent.py`、`agent/prompt_builder.py`、`agent/skill_utils.py`、`tools/skill_manager_tool.py`、`tools/skills_guard.py` 等核心文件）逐行分析，重点拆解其与主流 Agent 框架最本质的差异——**越用越强的自进化能力**。所有代码引用均标注行号，可在 [GitHub 仓库](https://github.com/nousresearch/hermes-agent) 验证。

---

## 引言：Agent 进化的缺失环节

过去两年，AI Agent 领域经历了三次明显的跃迁：

1. **被动问答机器人** → 依赖用户主动提问，无工具能力
2. **工具调用 Agent** → 具备单步工具调用，但无记忆跨会话
3. **持久记忆 Agent** → 拥有会话检索记忆，但仍依赖人类手动定义工作流

第三阶段停滞在一个关键瓶颈：**Agent 无法从实践中提炼经验并形成"肌肉记忆"**。

以 Claude Code 为例，每次新会话开始，它对上次处理同类任务的路径、踩过的坑、找到的技巧毫无印象。每次都从零推理，重复同样的试错过程。这对高频重复型任务而言是巨大的浪费。

HermesAgent 提出的解法是：**让 Agent 自己总结经验、自己写操作手册、自己在手册过期时修复它**。这就是 Skill 自学习机制的核心动机。

---

## 第一部分：三种经验积累模式的对比

在 HermesAgent 之前，业界探索过两种路径：

### 路径一：ACE（Agentic Context Engineering）
每次任务完成后，Agent 审查历史记录并提取"Bullets"——非结构化的自然语言经验条目。

**示例 Bullet：**
> "对价格、数量等关键数据，应对比多个权威来源，验证准确性"

**局限**：
- Bullets 格式松散，随上下文增长产生"规则噪声"
- 相似规则之间产生冲突，模型难以优先级排序
- 复杂任务下 Context 膨胀严重，影响推理质量

### 路径二：人工编写 Skill 卡片
将经验结构化为标准化的 Skill 模板，按需加载（懒加载）。

**优势**：Context 利用率高，调用精准
**局限**：Skill 由人编写——Agent 只是"读手册"，不会"写手册"

### 路径三：HermesAgent 的创新
**Agent 自己写手册，自己在手册失效时修手册。**

Skill 不再是静态知识库，而是 Agent 实践经验的动态结晶。

---

## 第二部分：自学习触发机制——双引擎设计

HermesAgent 的自学习能力通过系统提示注入实现。`agent/prompt_builder.py` 中的 `SKILLS_GUIDANCE` 常量（第 164-171 行）向模型注入了两条核心指令：

```python
# agent/prompt_builder.py: 164-171
SKILLS_GUIDANCE = (
    "After completing a complex task (5+ tool calls), fixing a tricky error, "
    "or discovering a non-trivial workflow, save the approach as a "
    "skill with skill_manage so you can reuse it next time.\n"
    "When using a skill and finding it outdated, incomplete, or wrong, "
    "patch it immediately with skill_manage(action='patch') — don't wait to be asked. "
    "Skills that aren't maintained become liabilities."
)
```

两条指令的本质：
1. **创建时机判断**：5+ 工具调用的复杂任务、迭代修正的棘手错误、可复用的非显而易见工作流
2. **即时修复义务**：发现 Skill 过时/不完整/错误时，**必须立即补丁**，不等人催——"被忽视的 Skill 会变成负债"

这两条 GUIDANCE 让模型具备了"自学习与自修复"意识。但意识本身还不够——HermesAgent 用**双引擎机制**保证自学习行为真正发生。

### 引擎一：前台自觉（Proactive Learning）

| 时机 | 触发条件 | 行为 |
|------|---------|------|
| 任务执行中 | 模型自主判断"此方法值得保存" | 主动调用 `skill_manage` 创建 Skill |

这是模型的主动决策：当它意识到刚找到一个非显而易见的有效方法，会停下来把它写成 Skill。

**触发动作**：模型调用 `skill_manage` 后，`run_agent.py` 第 7057 行将内部计数器归零：

```python
# run_agent.py: 7057-7058
elif function_name == "skill_manage":
    self._iters_since_skill = 0
```

### 引擎二：后台巡检（Background Inspection）

当前台没有主动触发时，迭代计数器持续累积。**关键细节：计数器按主循环迭代次数递增，而非按工具调用次数。** 每完成一轮 Agent 推理-执行循环，计数器 +1：

```python
# run_agent.py: 8182-8186
if (self._skill_nudge_interval > 0
        and "skill_manage" in self.valid_tool_names):
    self._iters_since_skill += 1
```

**阈值可通过配置文件调整**（默认 10）：

```python
# run_agent.py: 1236-1239
self._skill_nudge_interval = 10  # 默认值
self._skill_nudge_interval = int(
    skills_config.get("creation_nudge_interval", 10)
)
```

**跨任务累积示例**：
```
任务一（复杂代码审计）：8 次迭代循环 → _iters_since_skill = 8
任务二（简单查询）：    3 次迭代循环 → _iters_since_skill = 11
触发！后台巡检启动
```

注意：**计数器跨任务不重置**（`run_agent.py` 第 7885 行注释明确说明），这意味着即使单个任务没有达到阈值，多次短任务的累积也会触发巡检。

**后台巡检的执行方式**：不是模型本体执行，而是通过 `_spawn_background_review()` 在**独立守护线程**中启动一个完整的 AIAgent 副本：

```python
# run_agent.py: 2195-2294（简化逻辑）
def _spawn_background_review(self, messages_snapshot,
                             review_memory=False, review_skills=False):
    # 创建完整的 AIAgent 副本
    review_agent = AIAgent(
        max_iterations=8,       # 最多 8 轮推理
        quiet_mode=True,        # 静默运行，不输出到终端
    )
    # 共享记忆存储，但防止递归触发
    review_agent._memory_store = self._memory_store
    review_agent._skill_nudge_interval = 0  # 阻止递归巡检

    # 在守护线程中运行
    thread = threading.Thread(target=review_agent.run, daemon=True)
    thread.start()
```

巡检 Agent 使用两套提示模板：

**Skill 专用审查提示** `_SKILL_REVIEW_PROMPT`：
```python
# run_agent.py: 2171-2178
_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating "
    "a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that "
    "required trial and error, or changing course due to experiential "
    "findings along the way, or did the user expect or desire a "
    "different method or outcome?\n\n"
    "If a relevant skill already exists, update it with what you learned. "
    "Otherwise, create a new skill if the approach is reusable.\n"
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)
```

**联合审查提示** `_COMBINED_REVIEW_PROMPT`：当同时需要审查记忆和技能时使用，将两者合并到一次 Agent 调用中，节省推理成本。

**关键洞察**：只有包含绕路、犯错、迭代修正的经验才会被结晶为 Skill——"trial and error"、"changing course due to experiential findings"是审查提示的核心关注点。纯粹顺利的任务反而不会触发 Skill 生成——挫折才是最好的老师。

---

## 第三部分：Skill 管理——六大操作与热补丁机制

### 完整操作体系

`skill_manage` 工具提供**六种操作**（`tools/skill_manager_tool.py` 第 588-646 行）：

| 操作 | 用途 | 关键参数 |
|------|------|---------|
| `create` | 创建新 Skill | `name`, `content`, `category`（可选分类目录） |
| `edit` | 完整重写 SKILL.md | `name`, `content`（全文替换） |
| `patch` | 精准热补丁 | `name`, `old_string`, `new_string`, `replace_all` |
| `delete` | 删除 Skill | `name` |
| `write_file` | 写入辅助文件 | `name`, `file_path`（限 references/templates/scripts/assets/） |
| `remove_file` | 删除辅助文件 | `name`, `file_path` |

**创建时的严格验证链**：
1. 名称校验：`^[a-z0-9][a-z0-9._-]*$`，最长 64 字符
2. Frontmatter 校验：必须包含 `name` + `description` 字段
3. 大小限制：SKILL.md 最大 100K 字符，辅助文件最大 1 MiB
4. 跨目录名称冲突检查
5. **安全扫描**——不通过则自动回滚删除

### 热补丁的模糊匹配引擎

一个 Skill 在创建时是正确的，但环境在变化：API 地址更换、工具版本升级、依赖关系变化。传统系统的 Skill 会静默失效，直到下次人工审核。

HermesAgent 的热补丁不使用简单的精确字符串匹配，而是调用 `fuzzy_find_and_replace` 引擎：

```python
# tools/skill_manager_tool.py: 426-430
from tools.fuzzy_match import fuzzy_find_and_replace

new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
    content, old_string, new_string, replace_all
)
```

这个模糊匹配引擎能处理：
- **空白符归一化**：制表符 vs 空格差异
- **缩进差异**：2 空格 vs 4 空格
- **转义序列**：不同编码格式
- **块锚点匹配**：跨行内容定位

意味着 Agent 不需要精确记住 Skill 文件中每个字符的原貌，只需要提供"大致对应"的内容就能成功补丁。

### 原子写入与安全回滚

所有 Skill 文件修改都使用原子写入（`_atomic_write_text`）：

```python
# tools/skill_manager_tool.py: 256-285
def _atomic_write_text(file_path, content, encoding="utf-8"):
    fd, temp_path = tempfile.mkstemp(dir=str(file_path.parent), ...)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(temp_path, file_path)  # 原子替换
    except Exception:
        os.unlink(temp_path)  # 失败时清理临时文件
        raise
```

**每次修改后都会触发安全扫描**。如果扫描不通过，自动回滚到修改前的内容：

```python
# tools/skill_manager_tool.py: 455-462
original_content = content  # 保存原始内容
_atomic_write_text(target, new_content)

# 安全扫描 — 不通过则回滚
scan_error = _security_scan_skill(skill_dir)
if scan_error:
    _atomic_write_text(target, original_content)
    return {"success": False, "error": scan_error}
```

### 实际案例
一个 `feature-publish` Skill 失效，原因是发布 URL 已更换。Agent 通过搜索发现新地址后：

```python
skill_manage(
    action="patch",
    name="feature-publish",
    old_string="https://old-registry.company.com",
    new_string="https://registry.company.com"
)
```

补丁就地生效，任务**不中断**继续执行。无需重新生成 Skill，无需人工干预。

### 热补丁 vs. 重写的设计选择
Hermes 选择热补丁而非整体重写，是有意为之：

- **保留上下文**：Skill 中其他部分的经验不因一处失效而丢失
- **最小化侵入**：只修改确认有问题的片段，模糊匹配容忍格式偏差
- **可追溯性**：补丁记录本身也是学习历史
- **原子安全**：写入过程崩溃不会留下损坏文件，安全不通过自动回滚

---

## 第四部分：条件激活与安全防护

### Skill 条件激活——四维过滤

并非所有 Skill 在任何时候都可见。`agent/skill_utils.py` 的 `extract_skill_conditions()` 提取**四种条件类型**（第 241-255 行）：

```python
# agent/skill_utils.py: 241-255
def extract_skill_conditions(frontmatter):
    metadata = frontmatter.get("metadata")
    hermes = metadata.get("hermes") or {}
    return {
        "fallback_for_toolsets": hermes.get("fallback_for_toolsets", []),
        "requires_toolsets":     hermes.get("requires_toolsets", []),
        "fallback_for_tools":    hermes.get("fallback_for_tools", []),
        "requires_tools":        hermes.get("requires_tools", []),
    }
```

`prompt_builder.py` 的 `_skill_should_show()` 函数（第 550-578 行）实现过滤逻辑：

**1. 备用 Skill 隐藏（`fallback_for_*`）**

```yaml
# duckduckgo-search Skill 配置
metadata:
  hermes:
    fallback_for_toolsets: [web]   # 主工具集可用时隐藏
    fallback_for_tools: [web-search]  # 主工具可用时隐藏
```

逻辑：主工具/工具集在场时，备用 Skill 自动隐藏，不占用 Context。

**2. 前置依赖检查（`requires_*`）**

```yaml
# deep-research Skill 配置
metadata:
  hermes:
    requires_toolsets: [web]        # 依赖工具集
    requires_tools: [web-fetch]     # 依赖具体工具
```

逻辑：依赖工具/工具集不可用时，Skill 自动隐藏，防止调用失败。

**过滤优先级**：`fallback_for` 检查在前（主工具可用 → 隐藏备用），`requires` 检查在后（依赖缺失 → 隐藏）。

### 安全扫描层——80+ 威胁模式

`tools/skills_guard.py` 实现了生产级安全扫描（928 行），远不止简单的"四类威胁检测"。

#### 10+ 威胁类别、80+ 匹配模式

| 类别 | 代表性模式 | 严重级别 |
|------|-----------|---------|
| **exfiltration（数据泄露）** | `curl/wget` 拼接 `$KEY`/`$TOKEN`、读取 `.ssh`/`.aws`/`.env`、`printenv`/`env\|`、DNS 外泄、Markdown 图片外泄 | critical/high |
| **injection（提示注入）** | `ignore previous instructions`、`system prompt override`、`disregard rules`、HTML 隐藏注释/div、翻译后执行 | critical/high |
| **destructive（破坏性操作）** | `rm -rf /`、`chmod 777`、`mkfs`、数据库 `DROP`/`TRUNCATE` | critical/high |
| **persistence（持久化）** | 修改 `.bashrc`/`.profile`、crontab 注入、systemd 服务创建 | high/medium |
| **network（网络操作）** | 反向 shell（`nc -e`、`bash -i`）、端口转发、SSH 隧道 | critical/high |
| **obfuscation（混淆）** | base64 编码执行、`\x` 十六进制序列、不可见 Unicode 字符 | high/medium |
| **execution（代码执行）** | `eval()`、`exec()`、`os.system()`、`subprocess.call()` | high/medium |
| **traversal（路径穿越）** | `../../` 序列、符号链接滥用 | high |
| **supply_chain（供应链）** | 可疑 `pip install`、`npm install`、不安全的 `curl\|bash` 管道 | high/medium |
| **credential_exposure（凭证暴露）** | 硬编码 API keys、密码字符串、Token 明文 | critical/high |

#### 信任等级与安装策略矩阵

扫描结果为三级：`safe / caution / dangerous`。但最终是否放行，取决于 Skill 来源的**信任等级**：

```python
# tools/skills_guard.py: 41-47
INSTALL_POLICY = {
    #                  safe      caution    dangerous
    "builtin":       ("allow",  "allow",   "allow"),      # 内置：全部放行
    "trusted":       ("allow",  "allow",   "block"),      # 官方认证：dangerous 拦截
    "community":     ("allow",  "block",   "block"),      # 社区：caution 即拦截
    "agent-created": ("allow",  "allow",   "ask"),        # Agent 自建：dangerous 需用户确认
}
```

**"agent-created"是关键等级**：Agent 自主生成的 Skill，扫描结果为 `dangerous` 时不直接拦截，而是**交给用户决定**——这体现了对自进化能力的信任与安全之间的平衡。

#### 结构性检查

除正则匹配外，还执行：
- 文件数量与大小限制
- 二进制文件检测
- 符号链接检测
- **不可见 Unicode 字符检测**（零宽字符、双向文本标记等，常用于视觉欺骗攻击）

---

## 第五部分：Skills 提示缓存——两层加速

Skills 系统在系统提示中只注入名称和摘要（**渐进式披露**），完整内容仅在调用 `skill_view()` 时加载。但即便只是名称和摘要，随着 Skill 数量增长，构建索引的开销也不可忽视。

`prompt_builder.py` 实现了**两层缓存**：

```
┌─ Layer 1: 进程内 LRU 缓存 ─┐    ┌─ Layer 2: 磁盘快照 ─┐
│ OrderedDict, 8 条容量      │ ←→ │ .skills_prompt_snapshot.json │
│ 键: (skills_dir, tools,    │    │ mtime/size manifest 校验    │
│      toolsets)              │    │ 存活跨进程重启              │
└────────────────────────────┘    └───────────────────────────────┘
```

- **Layer 1**：热路径，同一进程内缓存命中直接返回
- **Layer 2**：冷启动加速。每次写入时保存所有 SKILL.md 的 `mtime_ns + size` 指纹。下次启动时如果文件没变，直接复用而不扫描文件系统

**实际效果**：系统积累了上百个 Skill 时，每次 API 调用的 Skills 索引构建仍然是 O(1) 命中缓存，而非 O(n) 遍历文件系统。

---

## 第六部分：与 Claude Code Skills 的本质差异

HermesAgent 的 Skill 机制与 Claude Code 的 Skills 系统在表层上相似，但底层逻辑完全不同：

| 维度 | Claude Code Skills | HermesAgent Skills |
|------|-------------------|-------------------|
| **创建主体** | 人类（开发者手动编写 SKILL.md） | Agent 自主创建 + 后台巡检 |
| **更新机制** | 手动维护 | 热补丁自动修复（模糊匹配引擎） |
| **管理操作** | 手动创建/编辑/删除 | 6 种操作（create/edit/patch/delete/write_file/remove_file） |
| **存储位置** | 项目目录 / `.claude/` | `~/.hermes/skills/`（用户全局）+ 外部目录（`skills.external_dirs`） |
| **触发时机** | 匹配 task description | SKILLS_GUIDANCE 驱动 + 迭代计数器阈值触发 |
| **跨任务学习** | 无 | 有（计数器跨任务累积，跨任务不重置） |
| **安全扫描** | 无（信任用户编写） | 80+ 模式 × 4 信任等级策略矩阵 |
| **Skill 生命周期** | 静态 | 动态（创建→使用→热补丁→淘汰） |
| **条件激活** | 无 | 4 维过滤（fallback_for/requires × toolsets/tools） |
| **提示缓存** | 无（每次扫描） | 两层缓存（进程内 LRU + 磁盘快照） |

**核心差异的本质**：Claude Code Skills 是**预设知识库**，HermesAgent Skills 是**经验演化系统**。前者是工具箱，后者是肌肉记忆。

---

## 第七部分：自进化的边界与局限

理解 HermesAgent 的自进化能力，也需要理解它的边界：

### 1. 自进化依赖模型判断质量
Skill 是否值得保存、何时触发热补丁，最终取决于模型的自我评估。当底层模型能力不足时，可能产生**低质量 Skill 积累**（垃圾进，垃圾出）。不过后台巡检 Agent 被限制为 `max_iterations=8`，这避免了失控式的低质量批量生成。

### 2. 跨用户的 Skill 不共享
当前架构中，Skill 存储在本地 `~/.hermes/skills/`，属于个人实例。虽然可以通过 `skills.external_dirs` 配置共享只读目录，但没有网络同步机制。优秀的 Skill 无法通过网络自动同步到其他用户——这既是隐私保护，也是规模化瓶颈。

### 3. 后台巡检是异步的代价
`review_agent` 在守护线程中异步运行，意味着当前任务不能立即受益于刚刚生成的 Skill。自进化的收益是**滞后的**。不过线程共享 `_memory_store`，记忆层面的更新可以即时生效。

### 4. 安全与自由的张力
`agent-created` 信任等级下，`dangerous` 结果需要用户确认而非直接拦截。这意味着如果用户习惯性地点"允许"，安全防线可能被绕过。安全扫描是正则静态分析，无法检测语义级别的隐蔽威胁。

### 5. 尚未到达 RL 训练环
从 Skill 文件到真正的权重更新，还有一大段路。当前的自进化发生在提示层（Skill 文本），而非模型参数层。真正的 RL 训练环（轨迹收集 → 奖励标注 → 微调训练）仍是长期目标。

---

## 结语：自进化能力改变了什么

HermesAgent 的 Skill 自学习机制代表了 Agent 架构的一个重要演进方向。

从**工具调用**到**经验积累**，从**读手册**到**写手册**，这个跨越重新定义了 Agent 与人类的协作模式：不再是"每次告诉它怎么做"，而是"它从做过的事情中越来越擅长"。

在 Agent 框架的竞争格局中：
- **Claude Code** 在专业编码执行上仍是最强的单次调用工具
- **OpenClaw** 用心跳机制实现了全天候自运转
- **HermesAgent** 的护城河在于**个人化的经验积累**——用得越久，越不可替代

这不是技术噱头，而是 Agent 走向真正"个人化助理"的必要条件。

---

*参考资料：*
- *[HermesAgent GitHub 仓库](https://github.com/nousresearch/hermes-agent)*
- *关键源码文件：`run_agent.py`（11K+ 行）、`agent/prompt_builder.py`、`agent/skill_utils.py`、`tools/skill_manager_tool.py`（761 行）、`tools/skills_guard.py`（928 行）*
