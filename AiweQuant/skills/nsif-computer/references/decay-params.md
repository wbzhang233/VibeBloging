# NSIF 衰减参数配置

## 标准 λ 参数表

```json
{
  "macro_data": {
    "description": "硬数据：NFP、CPI、GDP、PMI",
    "half_life_hours": 2,
    "lambda": 0.347,
    "window_hours": 12,
    "notes": "市场反应极快，1-4小时内完成定价"
  },
  "monetary_policy": {
    "description": "货币政策：FOMC声明、官员讲话、会议纪要",
    "half_life_hours": 12,
    "lambda": 0.058,
    "window_hours": 72,
    "notes": "分为两类：FOMC决议(半衰期4h)、普通官员讲话(半衰期24h)"
  },
  "geopolitics": {
    "description": "地缘政治：冲突、制裁、外交事件",
    "half_life_hours": 36,
    "lambda": 0.019,
    "window_hours": 168,
    "notes": "演化型风险，持续时间长，需监控叙事是否升级"
  },
  "risk_sentiment": {
    "description": "风险情绪：VIX、股市波动、避险流动",
    "half_life_hours": 8,
    "lambda": 0.087,
    "window_hours": 48,
    "notes": "情绪快速变化，但大幅风险事件衰减较慢"
  },
  "energy_commodity": {
    "description": "能源大宗：油价、LNG、大宗商品",
    "half_life_hours": 24,
    "lambda": 0.029,
    "window_hours": 96,
    "notes": "影响CAD、NOK、XAG，节奏介于宏观数据和地缘之间"
  },
  "fiscal_policy": {
    "description": "财政政策：债务上限、财政刺激、预算",
    "half_life_hours": 48,
    "lambda": 0.014,
    "window_hours": 168,
    "notes": "影响缓慢累积，多为中长期信号"
  },
  "positioning_flow": {
    "description": "持仓与资金流：COT报告、ETF流动、机构持仓",
    "half_life_hours": 72,
    "lambda": 0.010,
    "window_hours": 240,
    "notes": "低频但高质量，通常领先价格1-3天"
  },
  "research_report": {
    "description": "机构研报：投行晨报、策略报告、主题研究",
    "half_life_hours": 120,
    "lambda": 0.006,
    "window_hours": 360,
    "notes": "方向性强，衰减慢，适合中期策略"
  }
}
```

## 自适应 λ 调整

当某条资讯发布后价格出现显著反应，可用实际反应速度校正 λ：

```python
def estimate_adaptive_lambda(price_series, news_timestamp, half_life_default):
    """根据价格反应速度估算自适应λ"""
    # 资讯发布后价格累积变动量
    returns_after = price_series[news_timestamp:news_timestamp + pd.Timedelta('24H')]
    cumret = returns_after.cumsum().abs()
    # 找到达到最终值50%的时间点（即实际价格半衰期）
    final_val = cumret.iloc[-1]
    half_time = cumret[cumret >= final_val * 0.5].index[0]
    actual_half_life = (half_time - news_timestamp).total_seconds() / 3600
    return np.log(2) / max(actual_half_life, 0.5)  # 至少0.5小时
```

## 前瞻性指引的特殊处理

含 `has_forward_guidance=true` 的资讯使用 `monetary_policy` 的 **3倍半衰期**：

```python
if record.get("has_forward_guidance"):
    effective_lambda = lambda_config["monetary_policy"]["lambda"] / 3
```
