---
name: news-analyzer
description: 将原始金融资讯（新闻、研报、社媒）通过LLM结构化分析，提取关键词、关联逻辑标签、多空方向、影响强度和置信度，输出标准化Schema，用于外汇/贵金属量化策略的因子构建。适用于G10外汇和贵金属（XAU/XAG）资讯流策略研发场景。
---

# NewsAnalyzer Skill

将非结构化金融资讯转化为结构化打分记录，作为 NSIF 因子和叙事追踪的原材料。

## 触发场景

- 需要对新闻/研报/社媒资讯做多空影响分析时
- 构建资讯流因子前的数据预处理
- 批量标注历史资讯用于回测

## 输出 Schema

每条资讯输出以下结构（详见 `references/schema.md`）：

```json
{
  "news_id": "uuid",
  "timestamp": "ISO8601",
  "source": "Reuters",
  "keywords": ["Fed", "rate cut"],
  "logic_tags": ["monetary_policy"],
  "assets": {
    "EURUSD": {"direction": -1, "impact": 0.72, "confidence": 0.85, "reasoning": "..."},
    "XAUUSD": {"direction": -1, "impact": 0.60, "confidence": 0.78, "reasoning": "..."}
  },
  "event_importance": 0.90,
  "novelty": 0.65,
  "narrative_id": null
}
```

## 核心字段说明

| 字段 | 范围 | 说明 |
|------|------|------|
| `direction` | -1 / 0 / +1 | 空头 / 中性 / 多头 |
| `impact` | [0, 1] | 影响强度（逻辑直接性 × 市场敏感度） |
| `confidence` | [0, 1] | LLM 自评置信度（需 Platt Scaling 校准） |
| `event_importance` | [0, 1] | 事件重要性（FOMC > 官员讲话 > 一般新闻） |
| `novelty` | [0, 1] | 新颖度（与近期资讯语义相似度的反值） |

`logic_tags` 枚举：`monetary_policy` / `geopolitics` / `macro_data` / `risk_sentiment` / `energy_commodity` / `fiscal_policy` / `positioning_flow`

## 快速使用

### 单条分析（交互调用）

直接将资讯文本交给 LLM，要求按 Schema 输出 JSON。使用 `references/prompt-engineering.md` 中的 Prompt 模板。

### 批量分析（脚本）

```bash
pip install openai python-dotenv
python scripts/news_analyzer.py --input news.jsonl --output structured.jsonl
```

输入格式：每行一个 `{"id": "...", "timestamp": "...", "source": "...", "content": "..."}`

## 质量过滤规则

分析完成后过滤以下记录：
- `confidence < 0.5` → 丢弃
- `novelty < 0.3` → 降权（×0.5），保留但标记为重复
- 来源可信度权重：机构媒体 1.0 / 财经博主 0.7 / 匿名社媒 0.3

## 参考资料

- `references/schema.md` — 完整 Schema 定义与字段枚举
- `references/prompt-engineering.md` — Prompt 模板与 Few-shot 示例
- `scripts/news_analyzer.py` — 批量处理脚本（OpenAI / 兼容接口）
