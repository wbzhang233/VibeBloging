# LLM 事态预测 Prompt 模板

## 标准预测 Prompt

```
System:
你是一位资深宏观对冲基金经理，擅长从第一性原理推演宏观事件对外汇和贵金属的影响。
请基于事件时间线，分析事态的可能演化方向，输出结构化 JSON。

User:
## 叙事主题
{narrative_label}

## 事件时间线（最近{n}条，时间顺序）
{timeline_summary}

## 当前市场背景
- 分析时间: {current_time}
- 目标标的: {asset}
- 当前价格: {current_price}
- 近24h涨跌: {price_change_24h}%

## 输出要求
请输出以下 JSON 结构（不含其他文字）：
{
  "key_drivers": ["string"],           // 当前叙事的2-3个核心驱动因子
  "scenarios": [
    {
      "name": "bullish|base|bearish",
      "probability": float,            // 三种情景概率之和=1
      "impact_direction": -1|0|1,
      "impact_magnitude": float,       // 0-1，预期价格影响幅度
      "trigger": "string",             // 该情景的触发条件
      "description": "string"
    }
  ],
  "price_in_horizon_hours": int,       // 预计被市场完全定价的时间
  "key_risk": "string",               // 最大不确定性来源
  "confidence": float                  // 整体预测置信度 0-1
}
```

## 输出示例

```json
{
  "key_drivers": [
    "美联储鹰派立场超预期",
    "通胀数据连续高于预期",
    "就业市场持续强劲"
  ],
  "scenarios": [
    {
      "name": "bearish",
      "probability": 0.55,
      "impact_direction": -1,
      "impact_magnitude": 0.7,
      "trigger": "下次CPI数据继续超预期，市场推迟降息定价",
      "description": "美元继续走强，EUR/USD测试1.05支撑"
    },
    {
      "name": "base",
      "probability": 0.30,
      "impact_direction": 0,
      "impact_magnitude": 0.2,
      "trigger": "经济数据符合预期，市场观望",
      "description": "EUR/USD 维持区间震荡"
    },
    {
      "name": "bullish",
      "probability": 0.15,
      "impact_direction": 1,
      "impact_magnitude": 0.5,
      "trigger": "非农或CPI大幅不及预期，降息预期回升",
      "description": "美元快速回落，EUR/USD反弹至1.09+"
    }
  ],
  "price_in_horizon_hours": 48,
  "key_risk": "地缘政治突发事件可能打断当前叙事逻辑",
  "confidence": 0.72
}
```

## 蒙特卡洛采样

```python
import numpy as np

def monte_carlo_impact(scenarios: list[dict], n_samples: int = 10000) -> dict:
    probs      = [s["probability"] for s in scenarios]
    directions = [s["impact_direction"] for s in scenarios]
    magnitudes = [s["impact_magnitude"] for s in scenarios]

    idx = np.random.choice(len(scenarios), size=n_samples, p=probs)
    samples = np.array([directions[i] * magnitudes[i] for i in idx])

    return {
        "expected_impact": float(samples.mean()),
        "uncertainty":     float(samples.std()),
        "var_95":          float(np.percentile(samples, 5)),
        "upside_95":       float(np.percentile(samples, 95)),
    }
```
