---
name: nsif-computer
description: 计算净情绪强度因子（NSIF，Net Sentiment Intensity Factor）。基于结构化资讯流（NewsAnalyzer输出），按标的和逻辑维度（logic_tag）分别计算带时间衰减的多空情绪强度，输出多维NSIF矩阵，用于外汇/贵金属量化策略信号生成。
---

# NSIFComputer Skill

从 NewsAnalyzer 的结构化输出计算 NSIF 多维因子矩阵，是资讯流量化因子的核心计算环节。

## 触发场景

- 需要将结构化资讯记录聚合为时序因子时
- 实时计算当前多空情绪强度用于信号生成
- 批量回算历史 NSIF 用于因子检验和回测

## 核心公式

$$\text{NSIF}(t, \text{asset}, \text{tag}) = \frac{\sum_i \text{dir}_i \cdot \text{impact}_i \cdot \text{conf}_i \cdot w_{\text{src},i} \cdot e^{-\lambda_{\text{tag}}(t-t_i)}}{\sum_i e^{-\lambda_{\text{tag}}(t-t_i)}}$$

输出范围：`[-1, +1]`，正值偏多、负值偏空。

## 时间衰减系数（λ）快速参考

| logic_tag | 半衰期 | λ 参考值 |
|-----------|--------|---------|
| `macro_data`（NFP/CPI/FOMC） | 1–4 小时 | 0.17–0.69 |
| `monetary_policy`（官员讲话） | 4–24 小时 | 0.03–0.17 |
| `geopolitics` | 12–72 小时 | 0.01–0.06 |
| `energy_commodity` | 6–48 小时 | 0.01–0.12 |
| 机构研报 | 3–7 天 | 0.004–0.01 |

详细参数配置见 `references/decay-params.md`。

## 输出格式

```python
# NSIF 多维矩阵（xarray Dataset 或 DataFrame MultiIndex）
nsif[asset][logic_tag][timestamp] -> float  # ∈ [-1, +1]

# 示例：
nsif["EURUSD"]["monetary_policy"]["2026-03-25T10:00"] = -0.62
nsif["XAUUSD"]["geopolitics"]["2026-03-25T10:00"]    = +0.48
```

## 快速使用

### Python API

```python
from scripts.nsif_computer import NSIFComputer

computer = NSIFComputer(lambda_config="references/decay-params.json")
nsif_matrix = computer.compute(
    structured_df,           # NewsAnalyzer 输出的结构化 DataFrame
    assets=["EURUSD", "XAUUSD", "USDJPY"],
    tags=["monetary_policy", "geopolitics", "macro_data"],
    window_hours=72,         # 回溯时间窗口
    timestamp=pd.Timestamp.now()
)
```

### CLI 批量计算

```bash
python scripts/nsif_computer.py \
  --input structured.jsonl \
  --assets EURUSD,XAUUSD,USDJPY,GBPUSD \
  --tags monetary_policy,geopolitics,macro_data,risk_sentiment \
  --freq 1H \
  --output nsif_matrix.parquet
```

## 关键设计决策

- **分维度计算**：不同 `logic_tag` 使用不同 λ，避免硬数据和地缘叙事相互折中
- **归一化分母**：分母为衰减权重之和，确保 NSIF 在稀疏资讯时段也有稳定基准
- **来源权重 `w_src`**：机构媒体 1.0 / 财经博主 0.7 / 匿名社媒 0.3（可配置）
- **情绪基线去均值**：建议在最终使用前减去各标的各 tag 的长期历史均值

## 参考资料

- `references/formula.md` — 完整公式推导与边界条件处理
- `references/decay-params.md` — 各 logic_tag 的 λ 参数配置与调参建议
- `scripts/nsif_computer.py` — Python 实现（含实时流式更新模式）
