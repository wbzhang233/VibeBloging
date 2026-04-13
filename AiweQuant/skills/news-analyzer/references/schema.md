# NewsAnalyzer Schema 完整定义

## 完整 JSON Schema

```json
{
  "news_id": "string (UUID)",
  "timestamp": "string (ISO8601, 资讯发布时间，非抓取时间)",
  "source": "string (Reuters / Bloomberg / FT / WSJ / SeekingAlpha / X / Other)",
  "source_type": "institutional | media | social",
  "content_summary": "string (原文摘要，≤500字)",
  "keywords": ["string"],
  "logic_tags": ["string"],
  "assets": {
    "<ASSET>": {
      "direction": "integer (-1 | 0 | +1)",
      "impact": "float [0, 1]",
      "confidence": "float [0, 1]",
      "reasoning": "string (一句话解释逻辑链)"
    }
  },
  "event_importance": "float [0, 1]",
  "novelty": "float [0, 1]",
  "narrative_id": "string | null",
  "has_forward_guidance": "boolean"
}
```

## 字段枚举值

### `logic_tags`

| 标签 | 典型资讯 | 主要影响标的 |
|------|----------|------------|
| `monetary_policy` | 央行决议、官员讲话、利率路径预期 | 全部G10货币 |
| `macro_data` | GDP、CPI、NFP、PMI、零售销售 | 相关货币对 |
| `geopolitics` | 地缘冲突、制裁、外交事件 | XAU/XAG、JPY、CHF |
| `risk_sentiment` | VIX、股市波动、市场避险 | JPY、CHF、XAU |
| `energy_commodity` | 油价、大宗商品价格 | CAD、NOK、XAG |
| `fiscal_policy` | 财政刺激、债务上限、预算 | USD相关 |
| `positioning_flow` | 机构持仓报告、资金流向 | 全部标的 |

### `event_importance` 评分标准

| 分值 | 事件类型 |
|------|---------|
| 0.9–1.0 | FOMC决议、非农就业、CPI（美国） |
| 0.7–0.9 | 其他G10央行决议、GDP初值 |
| 0.5–0.7 | Fed/ECB主席讲话、PMI |
| 0.3–0.5 | 地区联储官员讲话、次要经济数据 |
| 0.1–0.3 | 分析师观点、媒体评论 |

### 支持的 `assets`

G10外汇：`EURUSD` `GBPUSD` `USDJPY` `USDCHF` `AUDUSD` `NZDUSD` `USDCAD` `USDNOK` `USDSEK`
贵金属：`XAUUSD` `XAGUSD`
指数（可选）：`DXY` `USDINDEX`

## 置信度校准说明

LLM 原始输出的 `confidence` 系统性偏高，建议：
1. 收集历史打标记录（方向预测 vs 实际价格方向）
2. 使用 Platt Scaling 或 Isotonic Regression 校准
3. 集成采样（同一资讯采样5次，用方差作为不确定性估计）

```python
from sklearn.calibration import calibration_curve
# 或直接用逻辑回归对原始分做校准
from sklearn.linear_model import LogisticRegression
calibrator = LogisticRegression().fit(raw_conf.reshape(-1,1), correct_labels)
calibrated = calibrator.predict_proba(raw_conf.reshape(-1,1))[:,1]
```
