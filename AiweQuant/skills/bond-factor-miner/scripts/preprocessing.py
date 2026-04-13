"""
数据预处理工具集：债券因子挖掘数据清洗与变换

职责：
  - 数据类型识别
  - 缺失值处理（依据数据类型）
  - 异常值处理（去极值）
  - 时间频率统一
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


# ─────────────────────────────────────────────
# 数据类型识别
# ─────────────────────────────────────────────

def detect_data_type(series: pd.Series) -> str:
    """
    自动识别时序数据的业务类型。

    返回值
    ------
    'flow'   : 流量型（净买入量，可正可负，波动较大）
    'level'  : 存量/水平型（持仓量，始终为正，趋势性强）
    'ratio'  : 比率/利差型（0-1 区间或百分比，相对稳定）
    'price'  : 价格/收益率型（连续，均值回归特性）
    'binary' : 二值型（0/1 信号）
    """
    s = series.dropna()
    if len(s) == 0:
        return 'unknown'

    unique_vals = s.nunique()
    if unique_vals <= 2:
        return 'binary'

    has_negative = (s < 0).any()
    all_positive = (s > 0).all()
    pct_range    = (s.max() - s.min()) / (abs(s.mean()) + 1e-10)
    cv           = s.std() / (abs(s.mean()) + 1e-10)      # 变异系数

    # 比率型：全部在 [-1, 1] 之间，或 [0, 100] 之间
    if (s.min() >= 0 and s.max() <= 100 and s.mean() < 30) or \
       (s.min() >= -1 and s.max() <= 1):
        return 'ratio'

    # 存量型：始终为正，变化平缓
    if all_positive and cv < 0.5 and not has_negative:
        return 'level'

    # 流量型：可正可负，或波动较大
    if has_negative or cv > 0.5:
        return 'flow'

    # 价格/收益率型：正值，中等波动
    return 'price'


# ─────────────────────────────────────────────
# 缺失值处理
# ─────────────────────────────────────────────

def handle_missing_values(
    df: pd.DataFrame,
    dtype_map: Optional[Dict[str, str]] = None,
    max_gap: int = 5
) -> pd.DataFrame:
    """
    依据数据类型选择缺失值填充方法。

    处理逻辑
    --------
    - 流量型 (flow)   : 前向填充（连续缺失 ≤ max_gap 期）；超出不填充
    - 存量型 (level)  : 线性插值
    - 比率型 (ratio)  : 线性插值
    - 价格型 (price)  : 线性插值
    - 其他            : 前向填充

    参数
    ----
    df       : 原始 DataFrame（时间索引）
    dtype_map: {列名: 数据类型} 字典；为 None 时自动识别
    max_gap  : 流量型数据允许的最大连续填充期数
    """
    if dtype_map is None:
        dtype_map = {col: detect_data_type(df[col]) for col in df.columns}

    df_out = df.copy()

    for col in df_out.columns:
        dtype = dtype_map.get(col, 'price')
        s     = df_out[col]

        if dtype == 'flow':
            # 前向填充，但连续缺失超过 max_gap 时不填充
            s_filled = s.copy()
            gap = 0
            for idx in s.index:
                if pd.isna(s_filled[idx]):
                    gap += 1
                    if gap <= max_gap:
                        # 找到最近的有效值进行填充
                        valid_prev = s_filled.loc[:idx].dropna()
                        if len(valid_prev) > 0:
                            s_filled[idx] = valid_prev.iloc[-1]
                else:
                    gap = 0
            df_out[col] = s_filled

        elif dtype in ('level', 'ratio', 'price'):
            df_out[col] = s.interpolate(method='linear', limit_direction='forward')

        else:
            df_out[col] = s.ffill()

    return df_out


# ─────────────────────────────────────────────
# 异常值处理
# ─────────────────────────────────────────────

def winsorize(series: pd.Series, quantile: float = 0.01) -> pd.Series:
    """
    缩尾法去极值（Winsorization）。

    将序列两端各 quantile 比例的值截断至分位数边界。
    quantile=0.01 表示截断 1% 和 99% 分位之外的值。
    """
    lower = series.quantile(quantile)
    upper = series.quantile(1.0 - quantile)
    return series.clip(lower=lower, upper=upper)


def remove_outliers_3sigma(series: pd.Series) -> pd.Series:
    """3σ 法则：超出均值 ±3σ 的值设为 NaN，再线性插值。"""
    mean, std = series.mean(), series.std()
    mask = (series < mean - 3 * std) | (series > mean + 3 * std)
    s_clean = series.copy()
    s_clean[mask] = np.nan
    return s_clean.interpolate(method='linear')


def remove_outliers_iqr(series: pd.Series, k: float = 1.5) -> pd.Series:
    """IQR 法则：Tukey 方法，超出 [Q1-k*IQR, Q3+k*IQR] 的值截断。"""
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr    = q3 - q1
    lower  = q1 - k * iqr
    upper  = q3 + k * iqr
    return series.clip(lower=lower, upper=upper)


# ─────────────────────────────────────────────
# 时间频率统一
# ─────────────────────────────────────────────

def align_time_frequency(df: pd.DataFrame, freq: str = 'W') -> pd.DataFrame:
    """
    将 DataFrame 重采样至目标频率（取期末值）。

    参数
    ----
    df   : 时间索引 DataFrame
    freq : 目标频率，'W'=周频, 'M'=月频, 'Q'=季频

    说明
    ----
    - 对于存量/价格数据，取期末最后一个有效值（last）
    - 对于流量数据，理论上应取期内加总（sum），但本函数统一取 last
      若底层数据已是期末累计值，last 正确；若为期内流量，调用方需自行处理
    """
    # 映射至 pandas 频率字符串
    freq_map = {
        'W': 'W-FRI',  # 周五结束的周频
        'M': 'ME',     # 月末
        'Q': 'QE',     # 季末
        'D': 'D'       # 日频（不重采样，直接返回）
    }
    target_freq = freq_map.get(freq.upper(), freq)
    if freq.upper() == 'D':
        return df
    return df.resample(target_freq).last().dropna(how='all')


# ─────────────────────────────────────────────
# 标准化
# ─────────────────────────────────────────────

def standardize_zscore(series: pd.Series) -> pd.Series:
    """Z-score 标准化（减均值除标准差）。"""
    return (series - series.mean()) / (series.std() + 1e-10)


def normalize_minmax(series: pd.Series) -> pd.Series:
    """Min-Max 归一化到 [0, 1] 区间。"""
    s_min, s_max = series.min(), series.max()
    if s_max == s_min:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - s_min) / (s_max - s_min)


# ─────────────────────────────────────────────
# 预处理流水线：一键完成
# ─────────────────────────────────────────────

def run_preprocessing(
    df: pd.DataFrame,
    target_col: str,
    freq: str = 'W',
    forward_period: int = 4,
    winsorize_quantile: float = 0.01,
    max_missing_gap: int = 5
) -> pd.DataFrame:
    """
    完整预处理流水线：类型识别 → 缺失值 → 异常值 → 频率统一 → 预测目标构造。

    返回
    ----
    预处理后的 DataFrame，包含原始列 + 'target_fwd_change' 列
    """
    # 1. 频率统一
    df_aligned = align_time_frequency(df, freq=freq)

    # 2. 识别数据类型
    dtype_map = {col: detect_data_type(df_aligned[col]) for col in df_aligned.columns}
    print("数据类型识别结果：")
    for col, dtype in dtype_map.items():
        print(f"  {col}: {dtype}")

    # 3. 缺失值处理
    df_clean = handle_missing_values(df_aligned, dtype_map=dtype_map, max_gap=max_missing_gap)

    # 4. 异常值处理（流量型和存量型）
    for col in df_clean.columns:
        dtype = dtype_map.get(col, 'price')
        if col == target_col:
            continue  # 目标变量不做去极值
        if dtype == 'flow':
            df_clean[col] = winsorize(df_clean[col], quantile=winsorize_quantile)
        elif dtype == 'level':
            df_clean[col] = remove_outliers_3sigma(df_clean[col])
        elif dtype == 'ratio':
            df_clean[col] = remove_outliers_iqr(df_clean[col])

    # 5. 构造预测目标：未来 N 期目标变量变化量
    df_clean['target_fwd_change'] = (
        df_clean[target_col].shift(-forward_period) - df_clean[target_col]
    )

    return df_clean, dtype_map
