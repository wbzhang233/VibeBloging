# 舆情驱动高频外汇与贵金属策略方案
## 地缘政治风险情景下的商业银行资金营运中心

> **策略定位**：信息驱动（News-Driven）+ 情感量化（Sentiment-Quantified）
> **标的**：G7 外汇（EUR/USD、GBP/USD、USD/JPY、USD/CAD、USD/CHF）+ XAU/USD、XAG/USD
> **数据源**：路透社新闻（Reuters Newswire）+ LLM 情感分析
> **频率**：高频（分钟级信号，日内持仓，最长 4 小时）

---

## 一、策略总体框架

```
┌─────────────────────────────────────────────────────────────────┐
│                   路透社新闻流（实时推送）                         │
│         Reuters API / RMDS / Refinitiv Datascope                │
└─────────────────────┬───────────────────────────────────────────┘
                      │ 原始新闻文本（标题 + 正文 + 元数据）
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│               LLM 情感分析引擎（Claude API / GPT-4o）            │
│  输出：direction / intensity / confidence / logic_tag / urgency │
└─────────────────────┬───────────────────────────────────────────┘
                      │ 结构化情感向量
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                   NSIF 因子计算引擎                               │
│   NSIF = direction × intensity × confidence × source_weight     │
│            × time_decay(λ) × geo_amplifier                      │
└─────────────────────┬───────────────────────────────────────────┘
                      │ 各资产 NSIF 时序
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                   信号合成与过滤模块                              │
│   NSIF 阈值过滤 → 动量确认 → 波动率过滤 → 相关性一致性           │
└─────────────────────┬───────────────────────────────────────────┘
                      │ 交易信号（资产、方向、强度、紧迫度）
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│               执行管理层（Execution Manager）                     │
│   仓位计算（Kelly / 波动率调整）→ 订单生成 → 风控检查 → 报单     │
└─────────────────────┬───────────────────────────────────────────┘
                      │ 成交回报
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│               监控与止损模块（Risk Watcher）                      │
│   动态止损（ATR × 1.5）+ 时间止损（4h）+ 总敞口上限              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、LLM 情感分析模块设计

### 2.1 新闻分类体系

每条路透社新闻经 LLM 处理后输出以下结构：

```json
{
  "headline": "Iran fires ballistic missiles at US naval assets in Persian Gulf",
  "logic_tag": "geopolitical_escalation",
  "direction": -0.85,
  "intensity": 0.92,
  "confidence": 0.88,
  "urgency": "critical",
  "affected_assets": ["XAU", "USD/JPY", "EUR/USD", "OIL"],
  "expected_moves": {
    "XAU": "strong_positive",
    "USD/JPY": "negative",
    "EUR/USD": "negative",
    "USD/CHF": "negative"
  },
  "half_life_hours": 4.0
}
```

### 2.2 Logic Tag 分类表

| logic_tag | 含义 | 典型新闻类型 | 半衰期 |
|-----------|------|------------|--------|
| `geopolitical_escalation` | 地缘升级 | 军事冲突、导弹发射、制裁升级 | 2-6 小时 |
| `geopolitical_deescalation` | 地缘降温 | 停火谈判、外交接触、协议签署 | 4-12 小时 |
| `energy_supply_shock` | 能源供给冲击 | 油田被袭、管道中断、霍尔木兹风险 | 4-8 小时 |
| `central_bank_signal` | 央行信号 | Fedspeak、ECB 会议纪要、BoJ 声明 | 24-48 小时 |
| `inflation_data` | 通胀数据 | CPI/PCE/PPI 发布 | 12-24 小时 |
| `trade_war_escalation` | 贸易摩擦 | 关税公告、制裁令、出口管制 | 6-24 小时 |
| `risk_off_flight` | 普遍避险 | 金融市场大跌、系统性风险信号 | 1-4 小时 |
| `commodity_demand_shock` | 大宗需求冲击 | 中国经济数据意外、工业需求报告 | 6-12 小时 |

### 2.3 情感强度校准

LLM 原始置信度分数系统性偏高（均值约 0.75+），需进行 **Platt Scaling 校准**：

```
calibrated_confidence = sigmoid(a × raw_score + b)
```
参数 (a, b) 通过历史新闻-价格响应对进行逻辑回归训练。

---

## 三、NSIF 因子构建

### 3.1 NSIF 公式

$$\text{NSIF}_{t}^{\text{asset}} = \sum_{i \in \text{news}(t)} d_i \times I_i \times C_i^{\text{cal}} \times W_{\text{src}} \times e^{-\lambda_{tag} \cdot (t - t_i)}$$

**各项定义**：

| 符号 | 含义 | 取值范围 |
|------|------|---------|
| $d_i$ | 方向（正面/负面） | [-1, +1] |
| $I_i$ | 强度 | [0, 1] |
| $C_i^{\text{cal}}$ | 校准后置信度 | [0, 1] |
| $W_{\text{src}}$ | 来源权重 | 路透社头条=1.0，快讯=0.8，分析文章=0.6 |
| $\lambda_{tag}$ | 衰减率（按 logic_tag） | 见下表 |
| $e^{-\lambda \cdot \Delta t}$ | 时间衰减 | 随时间指数递减 |

**时间衰减参数 λ**（half-life = ln(2)/λ）：

| logic_tag | 半衰期 | λ |
|-----------|--------|---|
| `geopolitical_escalation` | 4 小时 | 0.1733 |
| `energy_supply_shock` | 6 小时 | 0.1155 |
| `central_bank_signal` | 36 小时 | 0.0193 |
| `inflation_data` | 18 小时 | 0.0385 |
| `risk_off_flight` | 2 小时 | 0.3466 |

### 3.2 地缘政治放大器（Geo Amplifier）

在地缘政治极端风险期（美伊战争），引入放大系数：

```python
def geo_amplifier(logic_tag, geo_risk_level):
    """
    geo_risk_level: 0=正常, 1=升级, 2=危机
    """
    if logic_tag in ('geopolitical_escalation', 'energy_supply_shock'):
        return 1.0 + 0.5 * geo_risk_level  # 最高 2.0x 放大
    return 1.0
```

### 3.3 跨资产传导映射

每个 logic_tag 对应的标准资产反应矩阵：

| logic_tag | XAU | XAG | EUR/USD | USD/JPY | USD/CHF | USD/CAD | AUD/USD |
|-----------|-----|-----|---------|---------|---------|---------|---------|
| `geopolitical_escalation` | ++++ | +++ | -- | -- | --- | 0/+ | -- |
| `geopolitical_deescalation` | ---- | --- | ++ | ++ | +++ | 0 | ++ |
| `energy_supply_shock` | ++ | + | -- | - | -- | ++ | - |
| `central_bank_signal(hawk)` | -- | -- | 取决于央行 | 取决于央行 | - | 0 | - |
| `risk_off_flight` | +++ | ++ | -- | --- | --- | - | --- |

---

## 四、信号生成规则

### 4.1 三层信号过滤

**Layer 1：NSIF 阈值**
```
|NSIF| > θ_entry（默认 0.35）→ 生成候选信号
|NSIF| > θ_strong（默认 0.65）→ 生成强信号（提高仓位）
```

**Layer 2：动量确认**
```
若信号方向与最近 5 分钟价格动量一致（同向） → 信号确认
否则 → 信号降级（仓位减半）或等待 2 分钟再判断
```

**Layer 3：波动率过滤**
```
若当前 1 分钟 ATR > 历史 ATR(20) × 3.0 → 暂停开新仓（极端波动回避）
若当前市场深度（bid-ask spread）> 正常 × 5.0 → 暂停开仓（流动性枯竭）
```

### 4.2 地缘政治事件快速响应协议

```
新闻发布 → 50ms 内完成 LLM 分析（异步）
                  ↓
          urgency = "critical"?
                  ↓ Yes
   立即执行以下标准套保包（Pre-approved Playbook）：
   ┌─────────────────────────────────────────────┐
   │ 资产       方向  仓位   止损     目标        │
   │ XAU/USD    多     30%   -1.5%   +3.0%      │
   │ USD/JPY    空     20%   +1.0%   -2.0%      │
   │ USD/CHF    空     15%   +0.8%   -1.5%      │
   │ EUR/USD    空     15%   +0.8%   -1.5%      │
   └─────────────────────────────────────────────┘
   30分钟后：根据后续新闻和价格行动决定是否继续持仓
```

### 4.3 情景信号矩阵

| 情景 | 触发新闻特征 | 主要交易 | 辅助交易 |
|------|------------|---------|---------|
| 霍尔木兹封锁风险 | "Hormuz", "Iran closes", "naval blockade" | 多黄金 + 多原油 | 空 EUR/USD + 空 AUD/USD |
| 以色列空袭伊朗 | "Israel strikes Iran", "air attack" | 多黄金（速度优先）| 空 USD/JPY |
| 美伊谈判接触 | "diplomatic talks", "ceasefire", "negotiations" | 空黄金（短期） | 多 EUR/USD |
| Fed 鹰派意外 | "rate hike", "hawkish surprise", "inflation above" | 空黄金 + 多 USD | 空 EUR/USD |
| 油价暴涨 | "oil spike", "supply disruption", "OPEC cut" | 多 USD/CAD | 多黄金 |

---

## 五、仓位管理与风控体系

### 5.1 仓位计算（波动率调整 Kelly）

```python
def position_size(nsif_score, atr_current, atr_baseline, max_pct=0.30):
    """
    Kelly + 波动率调整仓位
    nsif_score: NSIF 绝对值 [0, 1]
    atr_current: 当前 ATR
    atr_baseline: 历史 ATR 基准
    """
    # Kelly 分数（保守版，1/4 Kelly）
    kelly_f = min(nsif_score * 0.5, max_pct)

    # 波动率调整：波动率越高，仓位越小
    vol_adj = min(atr_baseline / atr_current, 1.0)

    return kelly_f * vol_adj
```

### 5.2 止损规则

| 止损类型 | 触发条件 | 操作 |
|---------|---------|------|
| 时间止损 | 开仓后 4 小时未触达目标 | 强制平仓 |
| ATR 止损 | 价格逆向移动 > 1.5 × ATR | 立即平仓 |
| NSIF 反转 | NSIF 方向翻转且 |NSIF| > 0.5 | 立即平仓并考虑反向 |
| 流动性止损 | bid-ask spread > 5× 正常 | 暂停 + 人工介入 |
| 总敞口止损 | 单货币组合亏损 > 1% 净资产 | 全部平仓，暂停策略 |

### 5.3 风控参数推荐设置

```yaml
risk_config:
  # 仓位限制
  max_position_pct_per_asset: 0.30     # 单资产最大 30% 可用资金
  max_total_position_pct: 0.80         # 总持仓上限 80%
  max_correlated_exposure: 0.50        # 高相关资产合并敞口上限 50%

  # 止损设置
  stop_loss_atr_multiplier: 1.5
  max_holding_hours: 4
  daily_loss_limit_pct: 0.02          # 日亏损上限 2%

  # NSIF 信号阈值
  nsif_entry_threshold: 0.35
  nsif_strong_threshold: 0.65

  # 波动率过滤
  atr_spike_filter: 3.0               # 当前 ATR > 基准 3 倍则暂停
  spread_spike_filter: 5.0            # 买卖价差 > 正常 5 倍则暂停

  # 地缘政治模式
  geo_risk_level: 1                   # 0=正常, 1=升级, 2=危机（手动设置）
  critical_playbook_enabled: true     # 启用快速响应套保包
```

---

## 六、策略评估框架

### 6.1 回测方法论

针对地缘政治事件驱动策略的特殊性，**传统回测存在严重缺陷**：
- 历史事件稀少（每年 10-30 次 Tier-1 事件），样本量不足
- 未来事件的信息结构与历史不同
- 流动性条件在真实危机中显著不同于历史

**推荐的验证方法**：

1. **事件研究回测（Event Study Backtest）**
   - 收集 2020-2025 年所有地缘政治 Tier-1 事件（约 50-80 个）
   - 计算每次事件后 1h/2h/4h 的价格反应
   - 验证新闻 NSIF 信号与价格反应的方向一致性（目标：>65%）

2. **蒙特卡洛路径模拟**
   - 基于情景概率生成 1,000 个市场路径
   - 测试策略在不同油价/地缘政治路径下的表现

3. **Paper Trading（模拟交易验证）**
   - 在实盘前至少模拟交易 30 天
   - 监控信号生成频率、命中率、盈亏比

### 6.2 关键评估指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 信号方向准确率 | >62% | 优于随机水平，地缘政治事件约 65-70% |
| 平均盈亏比（P&L Ratio） | >1.8 | 止盈设置是止损的 2 倍 |
| 信息系数（IC） | >0.08 | NSIF 与 T+30min 价格变化相关性 |
| 最大回撤 | <5% | 日内策略 |
| 夏普比率（年化） | >1.5 | 扣除交易成本后 |
| 平均持仓时间 | 45-120 分钟 | 高频但非超高频 |

---

## 七、实施路线图

### Phase 1：数据基础（第 1-2 周）
- [ ] 接通路透社 Newswire API（RMDS 或 Refinitiv Elektron）
- [ ] 搭建历史新闻数据库（PostgreSQL + TimescaleDB）
- [ ] 获取对应时段的分钟级 FX/Gold OHLCV 数据
- [ ] 构建历史事件标注集（手工标注 100 条事件用于校准）

### Phase 2：LLM 分析引擎（第 2-4 周）
- [ ] 设计分析 Prompt，调用 Claude API 完成结构化提取
- [ ] 实施 Platt Scaling 置信度校准
- [ ] 批量处理历史新闻，构建情感时序数据集
- [ ] 验证 LLM 输出质量（与人工标注对比，目标 Kappa > 0.7）

### Phase 3：因子研究（第 3-5 周）
- [ ] 计算历史 NSIF 因子序列
- [ ] 进行 IC 分析（NSIF vs T+15/30/60min 价格变化）
- [ ] 分 logic_tag 进行分层测试
- [ ] 确定最优半衰期参数

### Phase 4：策略开发与回测（第 5-8 周）
- [ ] 实现信号生成逻辑
- [ ] 事件研究回测（2020-2025 重要事件）
- [ ] 参数优化（防止过拟合：Walk-Forward Analysis）
- [ ] 压力测试（霍尔木兹封锁情景）

### Phase 5：模拟与上线（第 8-12 周）
- [ ] 接入模拟交易环境（Refinitiv TREP / Bloomberg EMSX）
- [ ] 30 天模拟交易监控
- [ ] 风控委员会审批
- [ ] 小额实盘上线（最大持仓 5% 可用资金）
- [ ] 逐步扩大规模

---

## 八、与银行现有体系的集成

### 8.1 数据流集成

```
路透社 RMDS/Elektron API → Kafka 消息队列 → 策略引擎（Python）
                                                    │
                                                    ├→ 内部交易系统（TMS）
                                                    ├→ 风控系统（MUREX / SUMMIT）
                                                    └→ 监控仪表盘（Grafana / Tableau）
```

### 8.2 与套保业务的协同

- 当地缘政治风险信号达到"critical"级别时，策略引擎自动推送"建议增加黄金对冲"通知至资金营运负责人
- 所有信号和交易记录存入审计日志，满足监管要求（MiFID II / 银保监合规）
- 每日生成策略运行报告，包括信号列表、持仓明细、当日盈亏

---

> **免责声明**：本方案为内部研究文件，所有参数需根据实际回测结果和风险委员会要求进行调整。在正式上线前必须完成风控审批流程，所有方向性交易须在批准的投机限额内进行。
