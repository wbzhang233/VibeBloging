---
name: narrative-tracker
description: 追踪金融市场中的宏观叙事演化。对结构化资讯流（NewsAnalyzer输出）进行语义聚类，识别当前活跃叙事线索，维护每条叙事的时间线和情绪动量得分，用于LLM事态预测和叙事动量因子计算。适用于外汇/贵金属宏观叙事驱动策略。
---

# NarrativeTracker Skill

识别市场中正在发展的宏观叙事，追踪叙事强度的演化，为事态预测和叙事动量因子提供基础。

## 触发场景

- 需要识别当前市场主要叙事线索时（"市场在 pricing 什么？"）
- 计算叙事动量因子（Narrative Momentum）前的聚类预处理
- 为 LLM 事态预测准备时间线输入
- 监控重大叙事的生命周期状态（新兴 / 活跃 / 衰退 / 终结）

## 核心概念

**叙事（Narrative）**：围绕同一宏观主题的一组资讯，共同构成市场对某个事件或趋势的解读框架。

例：`fed_rate_path_2026q1` — 关于美联储2026年Q1降息路径的所有相关资讯。

## 叙事生命周期

```
新兴 (Emerging) → 活跃 (Active) → 衰退 (Fading) → 终结 (Closed)
    ↑ 聚类出现      ↑ 持续获得新资讯   ↑ 资讯减少       ↑ 超过最大生存期
```

## 输出格式

```python
# 活跃叙事列表
narratives = [
  {
    "narrative_id": "fed_rate_path_2026q1",
    "label": "美联储降息路径预期",
    "logic_tags": ["monetary_policy"],
    "assets_impacted": ["EURUSD", "XAUUSD", "USDJPY"],
    "status": "active",
    "created_at": "2026-03-10T08:00",
    "last_updated": "2026-03-25T14:30",
    "news_count": 142,
    "momentum_score": 0.43,    # 短期均值 - 长期均值，正值=升温
    "sentiment_trend": -0.31,  # 当前叙事情绪方向（负=利空美元）
    "timeline_summary": "..."  # 供 LLM 事态预测使用的时间线摘要
  }
]
```

## 快速使用

### 初始化与更新

```python
from scripts.narrative_tracker import NarrativeTracker

tracker = NarrativeTracker(
    embedding_model="all-MiniLM-L6-v2",  # 或任意 sentence-transformers 模型
    min_cluster_size=5,
    max_narrative_age_days=30,
    momentum_short_window="24H",
    momentum_long_window="72H",
)

# 增量更新（传入最新一批结构化资讯）
tracker.update(new_structured_records)

# 获取当前活跃叙事
active_narratives = tracker.get_active_narratives(min_news_count=3)

# 获取某标的相关叙事的动量得分
momentum = tracker.get_momentum("EURUSD")  # -> float
```

### CLI 批量模式

```bash
python scripts/narrative_tracker.py \
  --input structured.jsonl \
  --output narratives.jsonl \
  --state tracker_state.pkl       # 持久化聚类状态，支持增量更新
```

## 叙事动量因子计算

```python
# 动量 = 短期情绪均值 - 长期情绪均值（类 MACD 双均线差）
short_ma = narrative_sentiment.rolling("24H").mean()
long_ma  = narrative_sentiment.rolling("72H").mean()
momentum = short_ma - long_ma
# 正值 → 叙事升温（趋势跟随信号）
# 快速从正转负 → 叙事反转（均值回归信号）
```

## 与 LLM 事态预测的衔接

1. 调用 `tracker.get_active_narratives()` 获取活跃叙事列表
2. 选取 `momentum_score` 最高或 `news_count` 最多的叙事
3. 将 `timeline_summary` 传入 LLM Prompt 进行事态推演
4. 结果写回叙事记录的 `scenario_prediction` 字段

详细 Prompt 模板见 `references/scenario-prompt.md`。

## 参考资料

- `references/clustering.md` — HDBSCAN 聚类参数调优与增量更新策略
- `references/lifecycle.md` — 叙事生命周期管理规则与状态转移
- `references/scenario-prompt.md` — LLM 事态预测 Prompt 模板
- `scripts/narrative_tracker.py` — Python 实现
