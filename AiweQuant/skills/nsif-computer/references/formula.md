# NSIF 公式详解与边界处理

## 完整公式

$$\text{NSIF}(t, \text{asset}, \text{tag}) = \frac{\sum_{i \in \mathcal{N}(t,W)} \text{dir}_i \cdot \text{impact}_i \cdot \text{conf}_i \cdot w_{\text{src},i} \cdot e^{-\lambda_{\text{tag}}(t-t_i)}}{\sum_{i \in \mathcal{N}(t,W)} e^{-\lambda_{\text{tag}}(t-t_i)}}$$

**符号说明**：
- $\mathcal{N}(t,W)$：时间窗口 $[t-W, t]$ 内与 `(asset, tag)` 相关的资讯集合
- $\text{dir}_i \in \{-1, 0, +1\}$：多空方向
- $\text{impact}_i \in [0,1]$：影响强度
- $\text{conf}_i \in [0,1]$：校准后的置信度
- $w_{\text{src},i} \in [0.3, 1.0]$：来源权重
- $\lambda_{\text{tag}}$：logic_tag 对应的衰减系数

## 边界条件处理

### 1. 时间窗口内无资讯

```python
if len(news_in_window) == 0:
    return np.nan  # 不填充0，nan表示"无信息"而非"中性"
```

NaN 处理策略：在因子合成时用上一个有效值向前填充（ffill），最长填充 2× 半衰期。

### 2. 全为中性资讯（dir=0）

分子 = 0，分母 > 0，NSIF = 0。这是正确行为，表示市场正在关注但无明确方向。

### 3. 衰减过快导致分母接近0

```python
denominator = sum(exp(-lambda * delta_t))
if denominator < 1e-10:
    return np.nan  # 所有资讯已完全衰减
```

### 4. 情绪基线去均值（推荐）

各标的的 NSIF 存在长期偏置（如黄金长期受地缘因素小幅看多）：

```python
# 计算滚动历史均值作为基线（建议 90~180 天窗口）
baseline = nsif.rolling(window='90D').mean()
nsif_demeaned = nsif - baseline
```

去均值后的 NSIF 表示"超额情绪"，是更稳定的因子。

## 组合 NSIF

将多个 logic_tag 维度的 NSIF 加权合成综合信号：

```python
# 权重：各 tag 对该 asset 的历史 IC 贡献
weights = {
    "EURUSD": {
        "monetary_policy": 0.50,
        "macro_data":      0.30,
        "risk_sentiment":  0.20,
    }
}
composite_nsif = sum(w * nsif[asset][tag] for tag, w in weights[asset].items())
```
