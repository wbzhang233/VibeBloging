# 叙事生命周期管理

## 状态机定义

```
emerging → active → fading → closed
```

| 状态 | 触发条件 | 含义 |
|------|---------|------|
| `emerging` | 新聚类出现，news_count < 10 | 叙事刚开始形成 |
| `active` | news_count >= 10 且 24h内有新资讯 | 市场正在积极讨论 |
| `fading` | 48h 内无新资讯，但 age < max_age | 热度下降中 |
| `closed` | age > max_age 或手动关闭 | 叙事已被市场消化 |

## 生命周期参数（可配置）

```python
LIFECYCLE_CONFIG = {
    "emerging_threshold":   10,    # 资讯数量达到此值升为 active
    "fading_gap_hours":     48,    # 超过此时间无新资讯进入 fading
    "max_age_days":         30,    # 超过此时间强制关闭
    "min_age_to_close_days": 3,    # 新叙事至少存活天数（避免误关闭）
}
```

## 叙事动量得分计算

```python
def calc_momentum(sentiment_series: pd.Series) -> float:
    """
    叙事动量 = 短期情绪均值 - 长期情绪均值
    正值：叙事升温（趋势跟随信号）
    快速从正转负：叙事反转（均值回归信号）
    """
    short = sentiment_series.rolling("24H").mean().iloc[-1]
    long  = sentiment_series.rolling("72H").mean().iloc[-1]
    if pd.isna(short) or pd.isna(long):
        return 0.0
    return float(short - long)
```

## 时间线摘要生成（供 LLM 事态预测使用）

```python
def build_timeline_summary(timeline: list[dict], max_entries: int = 10) -> str:
    """生成供 LLM 推演的叙事时间线文本"""
    recent = sorted(timeline, key=lambda x: x["timestamp"])[-max_entries:]
    lines = []
    for r in recent:
        ts = r["timestamp"][:16]  # YYYY-MM-DD HH:MM
        src = r.get("source", "Unknown")
        summary = r.get("content_summary", "")[:150]
        direction_str = {1: "↑多头", -1: "↓空头", 0: "→中性"}.get(
            r.get("main_direction", 0), "?"
        )
        lines.append(f"[{ts}] {src} {direction_str}: {summary}")
    return "\n".join(lines)
```

## 叙事冲突检测

当同一时间段内同一标的出现两条方向相反的强叙事，触发矛盾告警：

```python
def detect_conflict(narratives: list[dict], asset: str, threshold: float = 0.4) -> bool:
    """检测是否存在叙事方向冲突"""
    active = [n for n in narratives if n["status"] == "active"
              and asset in n.get("assets_impacted", [])]
    sentiments = [n["sentiment_trend"] for n in active if abs(n["sentiment_trend"]) > threshold]
    if not sentiments:
        return False
    return max(sentiments) > threshold and min(sentiments) < -threshold
```

叙事冲突时的策略建议：
- 减少该标的仓位
- 等待叙事方向明朗化
- 提高开仓置信度阈值
