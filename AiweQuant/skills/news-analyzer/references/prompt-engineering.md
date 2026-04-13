# NewsAnalyzer Prompt 工程指南

## 核心 System Prompt

```
你是一位专业的宏观对冲基金分析师，专注于G10外汇和贵金属（XAU/XAG）市场。
你的任务是分析金融资讯，提取结构化信息，评估对各交易标的的多空影响。

分析框架：
1. 识别资讯的核心事件或观点
2. 判断关联的宏观逻辑（货币政策/地缘政治/宏观数据等）
3. 评估对各标的的直接和间接影响
4. 评分时考虑市场当前的定价基准（即影响是否已被市场预期）

输出要求：严格 JSON 格式，不输出任何解释文字。
```

## 用户 Prompt 模板

```
分析以下金融资讯，按 Schema 输出结构化分析结果。

资讯信息：
- 来源: {source}
- 时间: {timestamp}
- 内容: {content}

需要分析的标的: {assets}
（如某标的受影响极小，direction=0, impact<0.1 即可）

输出 JSON Schema：
{schema_template}
```

## Few-shot 示例

### 示例1：鹰派央行表态（货币政策）

**输入**：
```
来源: Reuters | 时间: 2026-03-25T14:30Z
内容: Fed Chair Powell said the central bank is "in no rush" to cut rates,
citing persistent inflation risks. Markets now pricing fewer than two cuts in 2026.
```

**输出**：
```json
{
  "keywords": ["Fed", "Powell", "rate cut", "inflation", "hawkish"],
  "logic_tags": ["monetary_policy"],
  "assets": {
    "EURUSD": {"direction": -1, "impact": 0.75, "confidence": 0.88,
               "reasoning": "鹰派Fed强化美元，EUR/USD直接承压"},
    "USDJPY": {"direction": 1,  "impact": 0.70, "confidence": 0.85,
               "reasoning": "美日利差扩大预期支撑USD/JPY走高"},
    "XAUUSD": {"direction": -1, "impact": 0.65, "confidence": 0.82,
               "reasoning": "实际利率上升预期压制黄金"},
    "XAGUSD": {"direction": -1, "impact": 0.50, "confidence": 0.75,
               "reasoning": "跟随黄金承压，但工业需求属性部分对冲"}
  },
  "event_importance": 0.85,
  "novelty": 0.70,
  "has_forward_guidance": true
}
```

### 示例2：地缘风险升级（地缘政治）

**输入**：
```
来源: AP | 时间: 2026-03-25T06:00Z
内容: Escalating tensions in Middle East after drone strikes on oil facilities.
Markets on edge as supply disruption fears grow.
```

**输出**：
```json
{
  "keywords": ["Middle East", "geopolitics", "oil", "supply disruption", "risk-off"],
  "logic_tags": ["geopolitics", "energy_commodity", "risk_sentiment"],
  "assets": {
    "XAUUSD": {"direction": 1,  "impact": 0.80, "confidence": 0.82,
               "reasoning": "地缘风险升级触发避险需求，黄金直接受益"},
    "XAGUSD": {"direction": 1,  "impact": 0.55, "confidence": 0.72,
               "reasoning": "跟随黄金上行，但工业属性限制涨幅"},
    "USDJPY": {"direction": -1, "impact": 0.60, "confidence": 0.78,
               "reasoning": "风险规避情绪推动日元走强"},
    "USDCAD": {"direction": -1, "impact": 0.65, "confidence": 0.75,
               "reasoning": "油价上行利好商品货币加元"}
  },
  "event_importance": 0.75,
  "novelty": 0.85,
  "has_forward_guidance": false
}
```

## 集成采样（不确定性估计）

对重要资讯（`event_importance > 0.7`）做多次采样：

```python
import asyncio

async def ensemble_analyze(news, n_samples=5, temperature=0.7):
    tasks = [llm_analyze(news, temperature=temperature) for _ in range(n_samples)]
    results = await asyncio.gather(*tasks)

    directions = [r['assets'][asset]['direction'] for r in results for asset in r['assets']]
    # 方向一致性低 → 不确定性高
    uncertainty = np.std([r['assets'][asset]['impact'] for r in results])
    mean_confidence = np.mean([r['assets'][asset]['confidence'] for r in results])

    return {
        'direction': round(np.mean(directions)),
        'confidence': mean_confidence * (1 - uncertainty),  # 折扣不确定性
        'uncertainty': uncertainty
    }
```

## 长文研报处理

```
Step 1 — 摘要压缩（≤300字）：
  "请提取以下研报的核心结论、关键预测数据和对外汇/贵金属的方向性建议。"

Step 2 — 结构化分析：
  用压缩后的摘要走正常 NewsAnalyzer 流程
```
