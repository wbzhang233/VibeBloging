"""
因子检验工具集：IC 分析、分层回测、稳健性检验

职责：
  - 计算 Pearson IC 和 Rank IC（时序滚动版本）
  - 计算 IC_IR
  - 因子分层分析（Quintile Analysis）
  - 稳健性检验（子区间 IC）
  - 汇总评分与合格判定

检验方法论详见：references/03_factor_testing_guide.md
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, Any, List, Optional, Tuple


# ─────────────────────────────────────────────
# IC 分析
# ─────────────────────────────────────────────

def compute_single_ic(factor: pd.Series, fwd_return: pd.Series) -> float:
    """
    计算单期全样本 Pearson IC（Pearson 线性相关系数）。
    两个序列先内连接、去 NaN。
    """
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    if len(combined) < 5:
        return np.nan
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))


def compute_single_rank_ic(factor: pd.Series, fwd_return: pd.Series) -> float:
    """计算单期全样本 Spearman Rank IC。"""
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    if len(combined) < 5:
        return np.nan
    corr, _ = stats.spearmanr(combined.iloc[:, 0], combined.iloc[:, 1])
    return float(corr)


def compute_rolling_ic(
    factor: pd.Series,
    fwd_return: pd.Series,
    window: int = 12
) -> pd.Series:
    """
    计算滚动 Pearson IC（以时间窗口内的时序相关性）。

    返回值：对齐的 IC 序列（长度 = len(factor) - window + 1 - NaN 数量）
    """
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    combined.columns = ['factor', 'fwd_return']
    rolling_ic = combined['factor'].rolling(window).corr(combined['fwd_return'])
    return rolling_ic.dropna().rename(f"ic_{factor.name}")


def compute_rank_ic_series(
    factor: pd.Series,
    fwd_return: pd.Series,
    window: int = 12
) -> pd.Series:
    """
    计算滚动 Rank IC（Spearman 秩相关，滚动窗口版本）。
    """
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    combined.columns = ['factor', 'fwd_return']

    rank_ics = []
    dates    = []
    for i in range(window - 1, len(combined)):
        chunk = combined.iloc[i - window + 1: i + 1]
        corr, _ = stats.spearmanr(chunk['factor'], chunk['fwd_return'])
        rank_ics.append(corr)
        dates.append(combined.index[i])

    return pd.Series(rank_ics, index=dates, name=f"rank_ic_{factor.name}")


# ─────────────────────────────────────────────
# IC_IR（信息比率）
# ─────────────────────────────────────────────

def compute_ic_ir(ic_series: pd.Series) -> float:
    """
    计算 IC 信息比率（IC_IR = 均值 / 标准差）。
    若标准差为 0，返回 0。
    """
    s = ic_series.dropna()
    if s.std() == 0 or len(s) < 3:
        return 0.0
    return float(s.mean() / s.std())


def compute_ic_stats(ic_series: pd.Series) -> Dict[str, float]:
    """计算 IC 系列的全部统计指标。"""
    s = ic_series.dropna()
    t_stat, p_val = stats.ttest_1samp(s, 0) if len(s) >= 5 else (np.nan, np.nan)
    return {
        'mean_ic':    round(float(s.mean()), 6),
        'abs_ic':     round(float(s.abs().mean()), 6),
        'std_ic':     round(float(s.std()), 6),
        'ic_ir':      round(compute_ic_ir(s), 4),
        'ic_pos_pct': round(float((s > 0).mean()), 4),
        'ic_t_stat':  round(float(t_stat) if not np.isnan(t_stat) else 0, 4),
        'ic_p_value': round(float(p_val) if not np.isnan(p_val) else 1, 4),
        'n_obs':      len(s),
    }


# ─────────────────────────────────────────────
# 分层分析
# ─────────────────────────────────────────────

def run_layered_analysis(
    factor: pd.Series,
    fwd_return: pd.Series,
    n_groups: int = 5
) -> pd.DataFrame:
    """
    因子分组（Quintile）分析：
    按因子值分为 n_groups 组，计算各组的未来收益率变化统计。

    返回 DataFrame，列：group, mean, std, count, sharpe
    """
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    combined.columns = ['factor', 'fwd_return']

    # 等频分组（可能存在边界重复值，用 duplicates='drop'）
    try:
        combined['group'] = pd.qcut(
            combined['factor'], n_groups,
            labels=[f'Q{i}' for i in range(1, n_groups + 1)],
            duplicates='drop'
        )
    except ValueError:
        # 分位数边界相同时降级处理
        combined['group'] = pd.cut(
            combined['factor'], n_groups,
            labels=[f'Q{i}' for i in range(1, n_groups + 1)]
        )

    def sharpe_ratio(x):
        return float(x.mean() / x.std()) if x.std() > 0 else 0.0

    result = (
        combined.groupby('group', observed=True)['fwd_return']
        .agg(
            mean='mean',
            std='std',
            count='count',
            sharpe=sharpe_ratio
        )
        .reset_index()
    )
    result = result.sort_values('group')
    result['mean']   = result['mean'].round(6)
    result['std']    = result['std'].round(6)
    result['sharpe'] = result['sharpe'].round(4)
    return result


def test_monotonicity(layer_df: pd.DataFrame) -> Dict[str, float]:
    """
    检验分层均值的单调性（Spearman 相关系数）。
    返回：{monotonicity_corr, p_value, is_monotone}
    """
    means  = layer_df['mean'].values
    groups = list(range(len(means)))
    corr, p_val = stats.spearmanr(groups, means)
    return {
        'monotonicity_corr': round(float(corr), 4),
        'p_value':           round(float(p_val), 4),
        'is_monotone':       abs(corr) >= 0.6 and p_val <= 0.2
    }


# ─────────────────────────────────────────────
# 稳健性检验（子区间 IC）
# ─────────────────────────────────────────────

def run_stability_test(
    factor: pd.Series,
    fwd_return: pd.Series,
    n_splits: int = 4
) -> pd.DataFrame:
    """
    将时间序列等分为 n_splits 段，分段计算 Pearson IC。
    返回 DataFrame：period, start, end, ic, n
    """
    combined = pd.concat([factor, fwd_return], axis=1).dropna()
    combined.columns = ['factor', 'fwd_return']
    n          = len(combined)
    chunk_size = max(n // n_splits, 5)

    results = []
    for i in range(n_splits):
        start_idx = i * chunk_size
        end_idx   = (i + 1) * chunk_size if i < n_splits - 1 else n
        chunk     = combined.iloc[start_idx:end_idx]
        if len(chunk) < 5:
            continue
        ic = float(chunk['factor'].corr(chunk['fwd_return']))
        results.append({
            'period': f'P{i+1}',
            'start':  str(chunk.index[0])[:10],
            'end':    str(chunk.index[-1])[:10],
            'ic':     round(ic, 4),
            'n':      len(chunk)
        })

    df = pd.DataFrame(results)

    # 计算方向一致性
    if len(df) > 0:
        direction = np.sign(df['ic'].dropna())
        consistent = (direction == direction.iloc[0]).all()
        df.attrs['direction_consistent'] = bool(consistent)
        df.attrs['n_positive']           = int((df['ic'] > 0).sum())
        df.attrs['n_negative']           = int((df['ic'] < 0).sum())

    return df


def evaluate_stability(stability_df: pd.DataFrame) -> str:
    """
    根据子区间 IC 结果给出稳健性评级。
    返回：'✅ 稳健' / '⚠️ 一般' / '❌ 不稳健'
    """
    if len(stability_df) == 0:
        return '❌ 不稳健'

    ics          = stability_df['ic'].dropna()
    direction    = np.sign(ics)
    all_same_dir = (direction == direction.iloc[0]).all()
    n_valid      = int((ics.abs() >= 0.03).sum())
    ratio_valid  = n_valid / len(ics)

    if all_same_dir and ratio_valid >= 0.75:
        return '✅ 稳健'
    elif all_same_dir or ratio_valid >= 0.5:
        return '⚠️ 一般'
    else:
        return '❌ 不稳健'


# ─────────────────────────────────────────────
# 因子合格判定
# ─────────────────────────────────────────────

def qualify_factor(
    ic_stats: Dict[str, float],
    mono_test: Dict[str, float],
    stability_label: str
) -> str:
    """
    综合 IC、IR、单调性、稳健性，给出因子合格评级。

    返回：'✅ 合格' / '⭐ 潜力' / '❌ 不合格'
    """
    abs_ic = ic_stats.get('abs_ic', 0)
    ic_ir  = ic_stats.get('ic_ir', 0)
    pos    = ic_stats.get('ic_pos_pct', 0.5)

    direction_ok = pos >= 0.55 or pos <= 0.45
    ic_ok        = abs_ic >= 0.05
    ir_ok        = abs(ic_ir) >= 0.3
    mono_ok      = mono_test.get('is_monotone', False)
    stable_ok    = '✅' in stability_label

    score = sum([ic_ok, ir_ok, direction_ok, mono_ok, stable_ok])

    if score >= 4:
        return '✅ 合格'
    elif score >= 2:
        return '⭐ 潜力'
    else:
        return '❌ 不合格'


# ─────────────────────────────────────────────
# 因子汇总表构建
# ─────────────────────────────────────────────

def build_factor_summary(
    factor_results: Dict[str, Any],
    factor_meta: Dict[str, Dict[str, Any]]
) -> pd.DataFrame:
    """
    汇总所有因子的检验结果，生成报告用汇总表。

    参数
    ----
    factor_results : {因子名: {'ic_series', 'rank_ic_series', 'ic_stats',
                               'layer_returns', 'stability'}}
    factor_meta    : {因子名: {'category', 'name_cn', ...}} （来自 factor_engineering）

    返回
    ----
    DataFrame：每行一个因子，包含所有评价指标
    """
    rows = []
    for fname, res in factor_results.items():
        meta     = factor_meta.get(fname, {})
        ic_stats = res.get('ic_stats', {})
        layer    = res.get('layer_returns', pd.DataFrame())
        stab     = res.get('stability',    pd.DataFrame())

        rank_ic_val = float(res['rank_ic_series'].mean()) if \
                      res.get('rank_ic_series') is not None and \
                      len(res['rank_ic_series']) > 0 else np.nan

        mono_test   = test_monotonicity(layer) if len(layer) > 0 else \
                      {'monotonicity_corr': np.nan, 'is_monotone': False}
        stab_label  = evaluate_stability(stab) if len(stab) > 0 else '❌ 不稳健'
        qualified   = qualify_factor(ic_stats, mono_test, stab_label)

        # 多空差异
        ls_diff = np.nan
        if len(layer) >= 2 and 'mean' in layer.columns:
            ls_diff = round(layer['mean'].iloc[-1] - layer['mean'].iloc[0], 6)

        rows.append({
            '因子代码':   fname,
            '因子名称':   meta.get('name_cn', fname),
            '类别':       meta.get('category', '-'),
            'IC均值':     round(ic_stats.get('mean_ic', np.nan), 4),
            '|IC|均值':   round(ic_stats.get('abs_ic', np.nan), 4),
            'IC_IR':      round(ic_stats.get('ic_ir', np.nan), 4),
            'IC正向占比': f"{ic_stats.get('ic_pos_pct', 0)*100:.1f}%",
            'Rank_IC':    round(rank_ic_val, 4) if not np.isnan(rank_ic_val) else '-',
            '多空收益差': round(ls_diff, 4) if not np.isnan(ls_diff) else '-',
            '单调性':     '✓' if mono_test.get('is_monotone') else '✗',
            '稳健性':     stab_label,
            '综合评级':   qualified,
        })

    df = pd.DataFrame(rows)
    # 按绝对 IC 降序排列
    if '|IC|均值' in df.columns:
        df = df.sort_values('|IC|均值', ascending=False)
    return df.reset_index(drop=True)
