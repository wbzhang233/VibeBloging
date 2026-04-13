# AI Agent 如何赋能资讯流策略研发
## 第一部分：资讯流策略构建全流程

> **投资标的**：G10 外汇 + XAU/XAG 贵金属
> **核心主线**：从非结构化资讯 → LLM 结构化提取 → 量化因子 → 策略信号

---

## Step A：数据层分析

在做任何建模之前，先搞清楚数据本身的形态是硬性前提。资讯流数据并非"干净"的时序数据，其分布特征直接决定后续因子的设计逻辑。

### A.1 时序数量特征

首先统计每个数据源的**资讯量时序分布**：

```python
# 按小时/天统计各来源资讯量
df.groupby(['source', pd.Grouper(key='timestamp', freq='1H')])['id'].count()
```

关键观察点：
- **日内分布**：资讯量是否集中在欧美交易时段？是否在重大数据（NFP、CPI、FOMC）发布前后有明显尖峰？
- **节假日效应**：低流动性时段的资讯是否更多来自低质量来源？
- **异常量检测**：`VolumeSpike = count(1h) / rolling_mean(30d)` — 尖峰往往是事件驱动行情的前兆

### A.2 分类统计特征

对资讯的**主题维度**做分布分析，建立对数据集的整体认知：

| 分析维度 | 目的 |
|----------|------|
| 来源分布（Reuters/Bloomberg/社媒） | 评估不同来源的时效性与可信度权重 |
| 主题标签分布（货币政策/地缘/宏观数据） | 识别当前市场主要叙事 |
| 标的关联分布（哪个货币对被提及最多） | 评估数据集对各标的的覆盖密度 |
| 语言/地区分布 | 识别信息不对称机会（如日文资讯对 USD/JPY 的领先性） |

### A.3 数据质量评估

资讯流数据常见质量问题：

- **重复资讯**：同一事件被多家媒体报道，需做语义去重（MinHash / embedding 相似度）
- **时间戳错误**：部分聚合平台的时间戳是抓取时间而非发布时间，需校正
- **标的关联噪声**：一条新闻可能被错误关联到多个标的，需过滤

> **数据层的核心产出**：每个来源、每个主题维度的**历史分布基线**，后续用于异常检测和信号标准化。

---

## Step B：基于 LLM 的资讯流结构化分析

这是整个流程的核心环节。目标是将每一条非结构化资讯，转化为一条**包含完整语义信息的结构化记录**，作为后续因子构建的原材料。

### B.1 结构化输出 Schema 设计

每条资讯经 LLM 分析后，应输出以下字段：

```json
{
  "news_id": "uuid",
  "timestamp": "2026-03-25T08:30:00Z",
  "source": "Reuters",

  "keywords": ["Fed", "rate cut", "inflation", "labor market"],

  "logic_tags": ["monetary_policy", "macro_data"],

  "assets": {
    "EURUSD": {
      "direction": -1,
      "impact": 0.72,
      "confidence": 0.85,
      "reasoning": "Fed鹰派表态强化美元，EUR/USD承压"
    },
    "XAUUSD": {
      "direction": -1,
      "impact": 0.60,
      "confidence": 0.78,
      "reasoning": "实际利率上升预期压制黄金"
    }
  },

  "event_importance": 0.90,
  "novelty": 0.65
}
```

字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `keywords` | list | 实体与概念关键词，用于后续聚类和因子标签 |
| `logic_tags` | list | 关联逻辑分类：`monetary_policy` / `geopolitics` / `macro_data` / `risk_sentiment` / `technical` |
| `direction` | int | +1（多头影响）/ -1（空头影响）/ 0（中性） |
| `impact` | float [0,1] | 影响强度，综合考虑逻辑链的直接性与市场敏感度 |
| `confidence` | float [0,1] | LLM 对自身判断的置信度，用于后续加权 |
| `event_importance` | float [0,1] | 事件本身的重要性（如 FOMC > 普通官员讲话） |
| `novelty` | float [0,1] | 资讯的新颖度，重复内容降权 |

### B.2 Prompt 工程要点

单纯调用通用 LLM 的结构化抽取效果参差不齐，以下是提升稳定性的关键实践：

**① Few-shot 示例驱动**

为每种 `logic_tag` 提供 2-3 条标注示例，尤其是边界case（如"模糊的官员表态"应打多少置信度）。

**② 强制输出格式约束**

使用 `response_format={"type": "json_object"}` 或 Function Calling，避免 LLM 输出自由文本。

**③ 分层提示策略**

对长文研报，先做**摘要压缩**再做**结构化分析**，控制 token 成本：

```
[长文研报] → Summarize Agent（提取结论段）→ Extract Agent（结构化打分）
```

**④ 置信度校准**

LLM 的 `confidence` 自评存在系统性偏高问题（overconfidence）。可通过历史数据校准：

```
calibrated_confidence = platt_scale(raw_confidence, historical_accuracy)
```

### B.3 资讯质量过滤

结构化分析后，对以下情况做过滤或降权：

- `confidence < 0.5`：LLM 自评不确定，信号噪声大
- `novelty < 0.3`：高度重复资讯，已被市场充分消化
- 来源可信度低（社媒匿名账号 vs 机构官方媒体）：乘以来源权重 `source_weight ∈ [0.3, 1.0]`

> **Step B 的核心产出**：一张包含 `(timestamp, asset, direction, impact, confidence, logic_tag)` 的结构化因子原材料表，后续所有因子都从这张表派生。

---

## Step C：因子构建

基于 Step B 的结构化数据，提供两条因子构建路径——**路径一**是手工量化因子，稳定可回测；**路径二**是 LLM 时态预测，捕捉非线性逻辑。两者可并行使用、相互验证。

---

### 路径一：净情绪强度因子（NSIF）

**NSIF（Net Sentiment Intensity Factor）** 是最核心的量化因子，衡量在某个时间窗口内、某个标的在某个逻辑维度上的综合多空情绪强度。

**基础公式（带时间衰减）**：

$$\text{NSIF}(t,\ \text{asset},\ \text{tag}) = \frac{\displaystyle\sum_{i \in \mathcal{N}} \text{dir}_i \cdot \text{impact}_i \cdot \text{conf}_i \cdot w_{\text{src},i} \cdot e^{-\lambda(t - t_i)}}{\displaystyle\sum_{i \in \mathcal{N}} e^{-\lambda(t - t_i)}}$$

其中：
- $\text{dir}_i \in \{-1, 0, +1\}$：多空方向
- $\text{impact}_i \in [0,1]$：影响强度
- $\text{conf}_i \in [0,1]$：置信度
- $w_{\text{src},i} \in [0.3, 1.0]$：来源可信度权重
- $\lambda$：时间衰减系数（见下文）
- $\mathcal{N}$：时间窗口内的资讯集合

**时间衰减系数的选取**

不同类型的资讯被市场 price-in 的速度差异显著，需针对性设置衰减速度：

| 资讯类型 | 典型半衰期 | λ 参考值 | 说明 |
|----------|-----------|---------|------|
| 硬数据（NFP、CPI、央行决议） | 1–4 小时 | 0.17–0.69 | 市场反应极快，信号衰减迅速 |
| 官员讲话（非正式） | 4–24 小时 | 0.03–0.17 | 解读需时间发酵 |
| 地缘政治事件 | 12–72 小时 | 0.01–0.06 | 演化型风险，持续时间长 |
| 机构研报 / 宏观分析 | 3–7 天 | 0.004–0.01 | 中长期方向性，衰减慢 |

实践中可用**自适应衰减**：根据该资讯发布后价格的实际反应速度，动态校正 λ。

**多维度 NSIF 矩阵**

将 NSIF 按 `logic_tag` 拆分，得到多维度因子矩阵：

```
NSIF_monetary_policy(t, EURUSD)
NSIF_geopolitics(t, XAUUSD)
NSIF_risk_sentiment(t, USDJPY)
NSIF_macro_data(t, GBPUSD)
...
```

这种拆分的意义在于：同一时间点，货币政策信号可能看多美元，而地缘风险信号同时推高黄金——综合 NSIF 会相互抵消，分维度 NSIF 则能清晰捕捉各自的驱动逻辑。

---

### 路径二：LLM 时态预测因子

路径一本质是对历史情绪的统计汇总，而**路径二**尝试让 LLM 基于事件发展逻辑，对**未来时态走向**做出预测性判断。

**整体流程**：

```
结构化资讯 → 主题聚类 → 时间线整理 → LLM第一性原理推演 → 蒙特卡洛情景采样 → 概率加权预测因子
```

**① 主题聚类与时间线整理**

将近期资讯按 `logic_tag` 和 `keywords` 做聚类，识别当前市场的**主要叙事线索（Narrative Threads）**：

```python
# 基于 embedding 做语义聚类
embeddings = embed_model.encode(news_list['summary'])
clusters = HDBSCAN(min_cluster_size=5).fit(embeddings)

# 每个 cluster 内按时间排序，形成事件演化时间线
for cluster_id in unique_clusters:
    timeline = news_df[news_df.cluster == cluster_id].sort_values('timestamp')
```

聚类后，每个 cluster 代表一条独立的叙事线索，例如：
- Cluster A：美联储降息预期的演化
- Cluster B：中东地缘冲突的升级
- Cluster C：美国就业数据的连续超预期

**② LLM 第一性原理推演**

将每条时间线的最新状态输入 LLM，要求从逻辑链出发预测下一步走向：

```
System Prompt:
你是一位资深宏观对冲基金经理，擅长从第一性原理推演宏观事件对外汇和贵金属的影响。
请基于以下事件时间线，分析事态的可能演化方向，并给出对 {asset} 的方向性判断。

时间线：
{timeline_summary}

要求输出：
1. 当前叙事的关键驱动因子
2. 3种可能的情景（乐观/基准/悲观）及其概率
3. 每种情景下对 {asset} 的方向和幅度预测
4. 该叙事在未来 {horizon} 内被 price-in 的预期时间
```

**③ 蒙特卡洛情景采样**

LLM 输出的多情景预测本质上是一个概率分布，可用蒙特卡洛方法将其转化为连续的预测因子：

```python
scenarios = {
    'bullish':   {'prob': 0.25, 'impact': +0.8},
    'base':      {'prob': 0.55, 'impact': -0.3},
    'bearish':   {'prob': 0.20, 'impact': -0.9},
}

# 采样 N 次，计算期望影响
N = 10000
samples = np.random.choice(
    [s['impact'] for s in scenarios.values()],
    p=[s['prob'] for s in scenarios.values()],
    size=N
)

expected_impact = samples.mean()      # 期望影响方向
impact_std = samples.std()            # 不确定性（可用于仓位管理）
var_95 = np.percentile(samples, 5)    # 下行风险
```

**输出因子**：

```
LLM_Predicted_Impact(t, asset, narrative_id) = expected_impact
LLM_Uncertainty(t, asset, narrative_id) = impact_std
```

**路径一 vs 路径二 对比**

| 维度 | 路径一（NSIF） | 路径二（LLM预测） |
|------|---------------|-----------------|
| 计算方式 | 统计加权 | 推理生成 |
| 依赖条件 | 历史数据充足 | 事件逻辑清晰 |
| 适用场景 | 常规情绪趋势跟踪 | 重大事件演化预判 |
| 可回测性 | 强，参数明确 | 弱，LLM 输出非确定 |
| 信号频率 | 高频（小时级） | 低频（日级或事件驱动） |
| 互补关系 | 路径一验证路径二的方向；路径二为路径一提供择时参考 | |

---

## Step D：因子检验

构建好的因子必须经过严格的统计检验，避免过拟合和伪因子。以下是针对资讯情绪类因子的检验框架。

### D.1 相关性分析

**目标**：确认因子与未来收益之间存在统计上显著的关联。

```python
# 计算 NSIF 与未来 N 小时收益的 Pearson/Spearman 相关系数
for horizon in [1, 4, 8, 24]:  # 小时
    future_return = price.pct_change(horizon).shift(-horizon)
    corr = stats.spearmanr(nsif.dropna(), future_return.dropna())
    print(f"Horizon={horizon}h: corr={corr.statistic:.3f}, p={corr.pvalue:.4f}")
```

外汇情绪因子的相关性通常不高（0.05~0.15），但统计显著即有价值。

### D.2 领先滞后分析（Lead-Lag Analysis）

**目标**：确认因子是"领先"还是"滞后"于价格变动，避免引入未来信息。

```python
# Cross-correlation 分析
lags = range(-12, 13)  # -12h 到 +12h
cross_corr = [nsif.corr(future_return.shift(lag)) for lag in lags]

# 期望：正 lag（因子领先价格）时相关性最高
# 如果负 lag 最大，说明因子是滞后指标（价格已跑在前面了）
```

这一步对资讯因子尤其重要——因为资讯发布后市场可能在几分钟内就完成定价，因子的有效预测窗口需要精确刻画。

### D.3 IC / ICIR 检验

**IC（Information Coefficient）**：因子值与下期收益的截面相关性。
**ICIR = mean(IC) / std(IC)**：因子稳定性的核心指标。

```python
# 针对多个资产计算截面 IC（如多个货币对在同一时刻的因子值 vs 收益）
def calc_ic(factor_df, return_df, horizon=24):
    ic_series = []
    for t in factor_df.index:
        f = factor_df.loc[t]
        r = return_df.shift(-horizon).loc[t]
        ic = f.corr(r, method='spearman')
        ic_series.append(ic)
    ic = pd.Series(ic_series, index=factor_df.index)
    return ic.mean(), ic.std(), ic.mean() / ic.std()  # mean_IC, std_IC, ICIR

# 行业经验参考值
# |mean_IC| > 0.05 且 ICIR > 0.5 为可用因子
```

### D.4 分层回测

将因子值分成 N 组（通常 5 组），检验**多空分组收益的单调性**：

```python
# 按 NSIF 分五组，统计各组的平均未来收益
factor_quintiles = pd.qcut(nsif, q=5, labels=['Q1','Q2','Q3','Q4','Q5'])
grouped_returns = return_df.groupby(factor_quintiles).mean()

# 理想结果：Q5（最强多头情绪）> Q4 > Q3 > Q2 > Q1（最强空头情绪）
# 多空组合收益（Q5 - Q1）是核心检验指标
```

分层回测还应检验：
- 不同**市场环境**（趋势市 vs 震荡市）下的因子表现分化
- 不同**数据来源**（机构 vs 社媒）的因子有效性差异
- 不同**logic_tag** 维度的因子各自贡献

### D.5 时间稳定性检验

避免因子只在特定时期有效（即过拟合到历史市场制度）：

```python
# 按年/季度滚动计算 ICIR，观察稳定性
rolling_icir = ic_series.rolling(252).apply(lambda x: x.mean() / x.std())
```

若 ICIR 在某段历史期间大幅为负，需分析是否因市场制度切换导致，并设计 Regime 识别机制。

---

## 小结：全流程数据流向

```
[原始资讯流]
     │
     ▼ Step A
[时序特征分析] → 建立数据基线，识别异常量
     │
     ▼ Step B
[LLM 结构化提取] → (timestamp, asset, direction, impact, confidence, logic_tag)
     │
     ├──────────────────────────────────────────┐
     ▼ Step C-路径一                             ▼ Step C-路径二
[NSIF 量化因子]                           [LLM 时态预测因子]
时间衰减加权统计                          聚类+时间线+蒙特卡洛
     │                                           │
     └──────────────────┬───────────────────────┘
                        ▼ Step D
              [因子检验：相关性/领先滞后/ICIR/分层回测]
                        │
                        ▼
              [通过检验的有效因子 → Step E 策略构建]
```

---

*（下一节：策略构建与参数寻优）*

*作者：VibeBloging | 标签：AI Agent、量化投研、资讯流策略、NLP、NSIF、外汇、贵金属*
