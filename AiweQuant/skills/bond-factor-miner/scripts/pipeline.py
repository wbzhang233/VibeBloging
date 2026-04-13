"""
流水线执行模块：bond-factor-miner 各步骤的完整实现

SKILL.md 中每个 Step 只需调用本文件对应的顶层函数。
函数签名 → 返回值 对应关系：

  init_project(...)          → (config, df)
  run_eda(config, df)        → eda_results
  run_preprocessing(config, df)
                             → df_aligned
  run_factor_engineering(config, df_aligned)
                             → (factors_df, factor_meta)
  run_factor_testing(config, factors_df, df_aligned, factor_meta)
                             → (factor_results, summary_df)
  run_report(config, df, df_aligned, eda_results,
             factor_meta, factor_results, summary_df)
                             → md_path
"""

import os
import re
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

# 确保项目根目录在 sys.path 中
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────
# Step A：项目初始化
# ─────────────────────────────────────────────

def init_project(
    data_path: str,
    target_col: str,
    bottom_data_desc: str,
    target_desc: str,
    forward_period: int = 4,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    Step A：创建目录结构、加载数据、自动推断 date_col 和 freq，返回 (config, df)。

    参数
    ----
    data_path        : 数据文件路径（CSV 或 Excel）
    target_col       : 待预测标的列名
    bottom_data_desc : 底层数据说明（各字段业务含义），来自用户输入
    target_desc      : 待预测标的说明，来自用户输入
    forward_period   : 预测期（期数），默认 4 期

    返回
    ----
    config : 本次运行配置字典（同时写入 logs/run_config.json）
    df     : 以时间为索引的原始 DataFrame
    """
    # ── 1. 创建目录结构
    for d in [
        "data/raw", "data/processed",
        "output/figures/eda", "output/figures/factors",
        "output/factors", "output/reports", "logs"
    ]:
        os.makedirs(d, exist_ok=True)

    # ── 2. 预览列名，推断时间列
    _reader_preview = (pd.read_csv if data_path.lower().endswith('.csv')
                       else pd.read_excel)
    df_preview = _reader_preview(data_path, nrows=3)

    date_col = None
    for col in df_preview.columns:
        if re.search(r'date|time|日期|时间', col, re.IGNORECASE):
            date_col = col
            break
        try:
            parsed = pd.to_datetime(df_preview[col], errors='coerce')
            if parsed.notna().all():
                date_col = col
                break
        except Exception:
            pass
    if date_col is None:
        date_col = df_preview.columns[0]

    print(f"[Step A] 自动识别时间列：{date_col}")

    # ── 3. 完整加载数据
    _reader = (pd.read_csv if data_path.lower().endswith('.csv')
               else pd.read_excel)
    df = _reader(data_path, parse_dates=[date_col], index_col=date_col)
    df = df.sort_index()

    # ── 4. 推断数据频率
    inferred = pd.infer_freq(df.index)
    freq = inferred if inferred else 'W'
    print(f"[Step A] 自动检测数据频率：{freq}（infer_freq={inferred}）")
    print(f"[Step A] 数据维度：{df.shape}，"
          f"时间范围：{df.index.min().date()} ~ {df.index.max().date()}")
    print(f"[Step A] 目标列：{target_col}，预测期：{forward_period} 期")

    # ── 5. 汇总配置
    config: Dict[str, Any] = {
        "run_time":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_path":        data_path,
        "target_col":       target_col,
        "date_col":         date_col,
        "freq":             freq,
        "forward_period":   forward_period,
        "output_dir":       "output/",
        "bottom_data_desc": bottom_data_desc,
        "target_desc":      target_desc,
    }
    with open("logs/run_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print("[Step A] ✅ 完成：配置已写入 logs/run_config.json")
    return config, df


# ─────────────────────────────────────────────
# Step B：数据加载与探索性分析（EDA）
# ─────────────────────────────────────────────

def run_eda(
    config: Dict[str, Any],
    df: pd.DataFrame,
) -> Dict[str, Tuple[str, str]]:
    """
    Step B：对原始数据执行完整 EDA，生成 7 类 Plotly 图表并导出 HTML + PNG。

    生成图表：时序总览 / 相关性热力图 / 目标变量分布 / 缺失值分析 /
              滚动统计 / 双轴联动图（每特征列一张）/ 散点矩阵（变量≤10时）

    返回
    ----
    eda_results : {图表标识: (html_path, png_path)}
    """
    from scripts.eda_utils import run_eda as _run_eda

    print(f"[Step B] 数据描述统计：\n{df.describe().round(4)}")
    print(f"[Step B] 缺失值情况：\n{df.isnull().sum()}")

    eda_results = _run_eda(
        df,
        target_col=config['target_col'],
        output_dir="output/figures/eda"
    )
    print(f"[Step B] ✅ 完成：共生成 {len(eda_results)} 张图表 → output/figures/eda/")
    return eda_results


# ─────────────────────────────────────────────
# Step C：数据预处理
# ─────────────────────────────────────────────

def run_preprocessing(
    config: Dict[str, Any],
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Step C：数据类型识别 → 缺失值处理 → 去极值 → 频率统一 → 构造预测目标列。

    预处理决策（详见 references/01_business_background.md）：
      flow  → 前向填充（≤5期） + 1% 缩尾
      level → 线性插值 + 3σ 法则
      ratio → 线性插值 + IQR 法则
      price → 线性插值，不去极值

    新增列 target_fwd_change = Yield(t + N) - Yield(t)

    返回
    ----
    df_aligned : 预处理后的 DataFrame，含 target_fwd_change 列
    """
    from scripts.preprocessing import (
        detect_data_type, handle_missing_values,
        winsorize, remove_outliers_3sigma, remove_outliers_iqr,
        align_time_frequency,
    )

    # 1. 识别数据类型
    dtype_map = {col: detect_data_type(df[col]) for col in df.columns}
    print("[Step C] 数据类型识别：")
    for col, dtype in dtype_map.items():
        print(f"  {col}: {dtype}")

    # 2. 缺失值处理
    df_clean = handle_missing_values(df, dtype_map=dtype_map, max_gap=5)

    # 3. 异常值处理（目标列不做去极值）
    target = config['target_col']
    for col in df_clean.columns:
        if col == target:
            continue
        dt = dtype_map.get(col, 'price')
        if dt == 'flow':
            df_clean[col] = winsorize(df_clean[col], quantile=0.01)
        elif dt == 'level':
            df_clean[col] = remove_outliers_3sigma(df_clean[col])
        elif dt == 'ratio':
            df_clean[col] = remove_outliers_iqr(df_clean[col])

    # 4. 统一时间频率
    df_aligned = align_time_frequency(df_clean, freq=config['freq'])

    # 5. 构造预测目标
    fwd = config['forward_period']
    df_aligned['target_fwd_change'] = (
        df_aligned[target].shift(-fwd) - df_aligned[target]
    )

    # 6. 保存
    df_aligned.to_csv("data/processed/data_clean.csv")
    n_valid = int(df_aligned.dropna().shape[0])
    print(f"[Step C] ✅ 完成：有效样本 {n_valid} 条，"
          f"数据已保存至 data/processed/data_clean.csv")
    return df_aligned


# ─────────────────────────────────────────────
# Step D：特征工程与因子构建
# ─────────────────────────────────────────────

def run_factor_engineering(
    config: Dict[str, Any],
    df_aligned: pd.DataFrame,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Step D：调用 BondFactorBuilder 构建全部候选因子，保存因子数据和元数据。

    因子分类（详见 references/02_factor_taxonomy.md）：
      机构行为类（6 种衍生）+ 技术面类（4 种）

    返回
    ----
    factors_df  : 候选因子 DataFrame（时间索引）
    factor_meta : {因子代码: {category, name_cn, formula, description, ...}}
    """
    from scripts.factor_engineering import BondFactorBuilder

    builder    = BondFactorBuilder(df_aligned, target_col=config['target_col'])
    factors_df = builder.build_all_factors()
    factor_meta = builder.get_factor_metadata()

    factors_df.to_csv("output/factors/all_factors.csv")
    with open("output/factors/factor_metadata.json", "w", encoding="utf-8") as f:
        json.dump(factor_meta, f, ensure_ascii=False, indent=2)

    print(f"[Step D] ✅ 完成：共构建 {len(factors_df.columns)} 个因子")
    for name in factors_df.columns:
        cat = factor_meta.get(name, {}).get('category', '-')
        print(f"  [{cat}] {name}")
    return factors_df, factor_meta


# ─────────────────────────────────────────────
# Step E：因子检验与可视化
# ─────────────────────────────────────────────

def run_factor_testing(
    config: Dict[str, Any],
    factors_df: pd.DataFrame,
    df_aligned: pd.DataFrame,
    factor_meta: Dict[str, Any],
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    Step E：对所有候选因子执行五层检验，生成图表，输出汇总表。

    检验内容（详见 references/03_factor_testing_guide.md）：
      1. 滚动 Pearson IC（窗口=12期）
      2. 滚动 Rank IC（Spearman）
      3. IC_IR = mean(IC) / std(IC)
      4. 因子分层分析（5 组，检验单调性）
      5. 子区间稳健性检验（4 等分）

    每因子生成两张图：IC 时序图 + 分层收益图（HTML + PNG）

    合格因子标准：|IC|≥0.05 且 IC_IR≥0.3 且方向性明确

    返回
    ----
    factor_results : {因子名: {ic_series, rank_ic_series, ic_stats,
                               layer_returns, stability}}
    summary_df     : 全量因子汇总 DataFrame（含综合评级）
    """
    from scripts.factor_testing import (
        compute_rolling_ic, compute_rank_ic_series, compute_ic_ir,
        compute_ic_stats, run_layered_analysis, run_stability_test,
        evaluate_stability, qualify_factor, test_monotonicity,
        build_factor_summary,
    )
    from scripts.visualization import (
        plot_ic_series, plot_factor_layered_returns,
        plot_factor_summary_table, plot_ic_comparison, export_figure,
    )

    forward_return = df_aligned['target_fwd_change'].dropna()
    factor_results: Dict[str, Any] = {}

    for fname in factors_df.columns:
        f_raw = factors_df[fname].dropna()
        f_vals, r_vals = f_raw.align(forward_return, join='inner')
        f_vals = f_vals.dropna()
        r_vals = r_vals.loc[f_vals.index]

        ic_series      = compute_rolling_ic(f_vals, r_vals, window=12)
        rank_ic_series = compute_rank_ic_series(f_vals, r_vals, window=12)
        ic_stats       = compute_ic_stats(ic_series)
        layer_returns  = run_layered_analysis(f_vals, r_vals, n_groups=5)
        stability      = run_stability_test(f_vals, r_vals, n_splits=4)

        factor_results[fname] = {
            'ic_series':      ic_series,
            'rank_ic_series': rank_ic_series,
            'ic_stats':       ic_stats,
            'layer_returns':  layer_returns,
            'stability':      stability,
        }

        # 生成图表
        fig_ic    = plot_ic_series(ic_series, rank_ic_series, fname)
        export_figure(fig_ic, f"factor_{fname}_ic", "output/figures/factors")

        fig_layer = plot_factor_layered_returns(layer_returns, fname)
        export_figure(fig_layer, f"factor_{fname}_layered", "output/figures/factors")

        print(f"  [{fname}] IC={ic_stats['mean_ic']:.4f}  "
              f"IR={ic_stats['ic_ir']:.3f}")

    # 汇总表 + 图
    summary_df = build_factor_summary(factor_results, factor_meta)

    fig_summary = plot_factor_summary_table(summary_df)
    export_figure(fig_summary, "00_factor_summary_table", "output/figures/factors")

    fig_compare = plot_ic_comparison(summary_df)
    export_figure(fig_compare, "01_ic_comparison", "output/figures/factors")

    summary_df.to_csv("output/factors/factor_summary.csv", encoding="utf-8-sig")

    n_ok  = int((summary_df['综合评级'] == '✅ 合格').sum())
    n_pot = int((summary_df['综合评级'] == '⭐ 潜力').sum())
    print(f"[Step E] ✅ 完成：合格={n_ok}  潜力={n_pot}  "
          f"不合格={len(summary_df)-n_ok-n_pot}")
    return factor_results, summary_df


# ─────────────────────────────────────────────
# Step F：报告生成
# ─────────────────────────────────────────────

def run_report(
    config: Dict[str, Any],
    df: pd.DataFrame,
    df_aligned: pd.DataFrame,
    eda_results: Dict[str, Any],
    factor_meta: Dict[str, Any],
    factor_results: Dict[str, Any],
    summary_df: pd.DataFrame,
    output_path: str = "output/reports/bond_factor_report.md",
) -> str:
    """
    Step F：调用 report_generator 生成完整 Markdown 研究报告。

    报告内容规范：详见 references/04_report_specification.md
    每个候选因子在第五章和第六章各有独立小节。

    返回
    ----
    md_path : 生成的报告文件路径
    """
    from scripts.report_generator import generate_md_report

    report_data = {
        "config":         config,
        "df_raw":         df,
        "df_processed":   df_aligned,
        "eda_results":    eda_results,
        "factor_meta":    factor_meta,
        "factor_results": factor_results,
        "summary_df":     summary_df,
        "figures_dir":    "output/figures",
    }
    md_path = generate_md_report(report_data, output_path)
    print(f"[Step F] ✅ 完成")
    print(f"         报告 → {md_path}")
    print(f"         图表 → output/figures/")
    print(f"         因子 → output/factors/")
    return md_path
