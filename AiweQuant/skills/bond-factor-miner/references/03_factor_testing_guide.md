# 因子检验方法论指引

> 适用技能：bond-factor-miner
> 文档类型：因子检验方法论

---

## 一、检验框架总览

因子检验的目的是从候选因子池中筛选出**统计显著、经济含义清晰、跨时期稳定**的有效预测因子。完整的检验体系包含以下五个层次：

```
┌─────────────────────────────────────────────────────────────┐
│                    因子检验五层体系                           │
├──────────────────────────────────────────────────────────────┤
│ Level 1：IC 分析           相关性检验，评估预测力大小         │
│ Level 2：IC_IR 分析        评估预测力稳定性                   │
│ Level 3：Rank IC 分析      非参数秩相关，更鲁棒               │
│ Level 4：分层分析          验证单调性（高分组是否优于低分组）   │
│ Level 5：稳健性检验         时间外稳定性，防止过拟合           │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、IC 分析（信息系数）

### 2.1 定义

**IC（Information Coefficient，信息系数）** 是因子值与未来收益（或收益率变化）之间的 Pearson 相关系数：

```
IC(t) = Corr(Factor(t), FwdReturn(t))
      = Cov(Factor(t), FwdReturn(t)) / (Std(Factor(t)) × Std(FwdReturn(t)))
```

其中：
- `Factor(t)`：t 时刻的因子值
- `FwdReturn(t)`：t 时刻对应的未来 N 期目标变量变化量

### 2.2 截面 IC vs 时序 IC

| 类型 | 适用场景 | 计算说明 |
|------|----------|----------|
| **截面 IC**（横截面） | 多标的（多只债券/品种）同时存在 | 每期对所有标的计算相关性 |
| **时序 IC**（本技能使用） | 单标的时序预测（如单一30Y收益率） | 计算整体时序相关性或滚动相关性 |

本技能处理单一标的（30Y国债收益率），使用**时序滚动 IC**：

```python
def compute_rolling_ic(factor: pd.Series, fwd_return: pd.Series, window: int = 12) -> pd.Series:
    """计算滚动 Pearson IC（窗口内时序相关）"""
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    rolling_ic = combined.iloc[:, 0].rolling(window).corr(combined.iloc[:, 1])
    return rolling_ic.dropna()
```

### 2.3 IC 评价标准

| |IC| 均值 | 评价 |
|------------|------|
| ≥ 0.10 | 优秀 |
| 0.05 ~ 0.10 | 良好 |
| 0.03 ~ 0.05 | 一般 |
| < 0.03 | 无效 |

> **注意**：利率市场中，机构净买入因子的 IC 绝对值通常在 0.05-0.20 之间，高于股票因子（0.03-0.08），因为利率市场机构集中度高，信号更清晰。

---

## 三、IC_IR（信息比率）

### 3.1 定义

**IC_IR（IC Information Ratio）** 衡量 IC 值的稳定性，类比夏普比率：

```
IC_IR = Mean(IC_series) / Std(IC_series)
```

IC_IR 越高，因子预测力越稳定，越适合纳入量化策略。

### 3.2 评价标准

| IC_IR | 评价 |
|-------|------|
| ≥ 0.5 | 优秀，非常稳定 |
| 0.3 ~ 0.5 | 良好 |
| 0.2 ~ 0.3 | 一般，慎用 |
| < 0.2 | 不稳定，不建议单独使用 |

### 3.3 IC 正向占比

除 IC 均值和 IR，还需计算 IC 为正的时期占比：

```python
ic_pos_pct = (ic_series > 0).mean()
# 期望：如因子预期方向为负相关，则 IC 负向占比 > 55% 为合格
```

---

## 四、Rank IC（秩相关系数）

### 4.1 定义

**Rank IC** 使用 Spearman 秩相关，对异常值更鲁棒：

```python
from scipy.stats import spearmanr

def compute_rank_ic(factor: pd.Series, fwd_return: pd.Series) -> float:
    """计算单期 Rank IC"""
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    corr, _ = spearmanr(combined.iloc[:, 0], combined.iloc[:, 1])
    return corr
```

### 4.2 Rank IC vs Pearson IC 的选择

| 情况 | 推荐 |
|------|------|
| 因子分布接近正态，无明显极端值 | Pearson IC |
| 因子含有极端值，或分布高度偏态 | Rank IC 更鲁棒 |
| 标准做法 | 两者均计算，对比报告 |

> **实践建议**：同时报告 Pearson IC 和 Rank IC。若两者差异 < 0.05，说明极端值影响不大；若差异 > 0.1，说明因子存在极端值问题，需重新检查预处理。

---

## 五、分层分析（Quintile Analysis）

### 5.1 方法说明

将因子值等分为 N 组（通常 5 组），观察各组对应的未来收益率变化均值是否具有单调性：

```
因子值排序：低 ←─────────────────────→ 高
分层标签：  Q1      Q2      Q3      Q4      Q5

期望结果（若因子与收益率负相关）：
Q1 组：未来收益率变化最大（上涨最多，或下降最少）
Q5 组：未来收益率变化最小（上涨最少，或下降最多）
```

### 5.2 实现逻辑

```python
def run_layered_analysis(factor: pd.Series, fwd_return: pd.Series,
                          n_groups: int = 5) -> pd.DataFrame:
    """因子分组分析"""
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    combined.columns = ['factor', 'fwd_return']
    combined['group'] = pd.qcut(combined['factor'], n_groups,
                                labels=[f'Q{i}' for i in range(1, n_groups+1)])
    result = combined.groupby('group')['fwd_return'].agg(
        mean='mean', std='std', count='count',
        sharpe=lambda x: x.mean() / x.std() if x.std() > 0 else 0
    ).reset_index()
    return result
```

### 5.3 单调性检验

```python
from scipy.stats import spearmanr
def test_monotonicity(layer_df: pd.DataFrame) -> float:
    """检验分层均值的单调性（Spearman 相关）"""
    groups = list(range(len(layer_df)))
    means = layer_df['mean'].values
    corr, p_val = spearmanr(groups, means)
    return {'monotonicity_corr': corr, 'p_value': p_val}
```

---

## 六、稳健性检验

### 6.1 目的

防止因子在特定历史时期表现好（例如特定货币政策周期），但跨时期不稳定。

### 6.2 滚动子样本检验

将样本等分为若干子区间，在每个子区间分别计算 IC，检验是否持续有效：

```python
def run_stability_test(factor: pd.Series, fwd_return: pd.Series,
                        n_splits: int = 4) -> pd.DataFrame:
    """将时间序列切分为 n 段，分段计算 IC"""
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    n = len(combined)
    chunk_size = n // n_splits
    results = []
    for i in range(n_splits):
        chunk = combined.iloc[i*chunk_size : (i+1)*chunk_size]
        ic = chunk.iloc[:, 0].corr(chunk.iloc[:, 1])
        results.append({
            'period': f'P{i+1}',
            'start': chunk.index[0],
            'end': chunk.index[-1],
            'ic': round(ic, 4),
            'n': len(chunk)
        })
    return pd.DataFrame(results)
```

### 6.3 稳健性评价标准

| 稳健性标准 | 要求 |
|------------|------|
| IC 方向一致性 | 各子区间 IC 符号一致（均正或均负）→ 方向稳定 |
| IC 绝对值 | 至少 3/4 的子区间 \|IC\| ≥ 0.03 |
| 跨周期表现 | 宽松周期和收紧周期均有正向表现 |

---

## 七、可视化规范

### 7.1 IC 时序图（必须包含）

- 柱状图：每期 IC 值，正值绿色，负值红色
- 叠加水平虚线：IC 均值
- 右侧标注：均值、IR、正向占比统计
- 副图：IC 分布直方图（检验是否接近正态）

### 7.2 分层收益图（必须包含）

- 条形图：各分层组的平均未来收益率变化
- 叠加误差棒（1个标准差）
- 标注：多空组差异（Q5 - Q1）

### 7.3 因子汇总表（必须包含）

每个因子一行，列包含：

| 因子名 | 类别 | IC均值 | \|IC\|均值 | IC_IR | Rank IC | IC正向% | 分层单调性 | 稳健性 | 是否合格 |
|--------|------|--------|-----------|-------|---------|---------|-----------|--------|---------|

合格因子标绿色背景，不合格标红色，潜力因子标黄色。

---

## 八、检验流程 SOP

```
Step 1：数据对齐
  └── factor(t) 与 fwd_return(t) 按日期内连接，去掉 NaN

Step 2：Pearson IC 分析
  ├── 计算整体 IC 均值
  ├── 计算滚动 IC 时序（窗口=12期）
  └── 绘制 IC 时序图 + 分布图

Step 3：Rank IC 分析
  └── 同上，使用 Spearman 秩相关

Step 4：IC_IR 计算
  └── IC_IR = mean(IC_series) / std(IC_series)

Step 5：分层分析
  ├── 5 组等分
  ├── 计算各组平均收益率变化
  └── 绘制分层条形图 + 单调性检验

Step 6：稳健性检验
  ├── 4 等分子样本 IC 计算
  └── 评估 IC 方向一致性

Step 7：汇总评分
  └── 按评价矩阵给出综合评级
```
