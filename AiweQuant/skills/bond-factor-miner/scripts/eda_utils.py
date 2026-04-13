"""
EDA 工具集：债券因子挖掘数据探索性分析

所有可视化使用 Plotly 实现。
导出函数由 visualization.py 提供，此处直接调用。
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os
from typing import Optional, List, Dict, Tuple


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def export_figure(fig: go.Figure, name: str, output_dir: str) -> Tuple[str, str]:
    """导出图表为 HTML + PNG 两种格式（高清双倍像素）"""
    os.makedirs(output_dir, exist_ok=True)
    html_path = os.path.join(output_dir, f"{name}.html")
    png_path  = os.path.join(output_dir, f"{name}.png")
    fig.write_html(html_path)
    fig.write_image(png_path, width=1200, height=600, scale=2)
    return html_path, png_path


# ─────────────────────────────────────────────
# EDA 图表：1 - 时间序列总览
# ─────────────────────────────────────────────

def plot_time_series_overview(df: pd.DataFrame, title: str = "时间序列总览") -> go.Figure:
    """
    多面板时序图，每列一个子图，共享 x 轴。

    参数
    ----
    df : 以时间为索引的 DataFrame
    title : 图表标题
    """
    cols = df.columns.tolist()
    n    = len(cols)
    fig  = make_subplots(
        rows=n, cols=1,
        shared_xaxes=True,
        subplot_titles=cols,
        vertical_spacing=0.05
    )
    colors = px.colors.qualitative.Plotly
    for i, col in enumerate(cols, 1):
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df[col],
                name=col, mode='lines',
                line=dict(color=colors[i % len(colors)], width=1.5)
            ),
            row=i, col=1
        )
    fig.update_layout(
        title=dict(text=title, x=0.5),
        height=max(300 * n, 600),
        showlegend=False,
        template='plotly_white',
        margin=dict(l=60, r=20, t=60, b=40)
    )
    return fig


# ─────────────────────────────────────────────
# EDA 图表：2 - 相关性热力图
# ─────────────────────────────────────────────

def plot_correlation_heatmap(df: pd.DataFrame, title: str = "变量相关性矩阵（Pearson）") -> go.Figure:
    """Pearson 相关性热力图，显示数值标注。"""
    corr = df.corr().round(3)
    cols = corr.columns.tolist()

    text_vals = [[f"{v:.2f}" for v in row] for row in corr.values]

    fig = go.Figure(data=go.Heatmap(
        z=corr.values,
        x=cols, y=cols,
        colorscale='RdBu_r',
        zmid=0,
        zmin=-1, zmax=1,
        text=text_vals,
        texttemplate="%{text}",
        textfont=dict(size=10),
        hoverongaps=False,
        colorbar=dict(title="相关系数")
    ))
    fig.update_layout(
        title=dict(text=title, x=0.5),
        height=max(400, 80 * len(cols)),
        template='plotly_white',
        xaxis=dict(tickangle=45)
    )
    return fig


# ─────────────────────────────────────────────
# EDA 图表：3 - 目标变量分布
# ─────────────────────────────────────────────

def plot_target_distribution(df: pd.DataFrame, target_col: str) -> go.Figure:
    """目标变量的直方图（左）+ 箱线图（右）。"""
    series = df[target_col].dropna()
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=[f"{target_col} 直方图", f"{target_col} 箱线图"]
    )
    fig.add_trace(
        go.Histogram(x=series, nbinsx=50, name=target_col,
                     marker_color='steelblue', opacity=0.75),
        row=1, col=1
    )
    fig.add_trace(
        go.Box(y=series, name=target_col, boxpoints='outliers',
               marker_color='steelblue'),
        row=1, col=2
    )
    mean_val = series.mean()
    fig.add_vline(x=mean_val, line_dash="dash", line_color="red",
                  annotation_text=f"均值={mean_val:.4f}", row=1, col=1)
    fig.update_layout(
        title=dict(text=f"目标变量 [{target_col}] 分布特征", x=0.5),
        height=500,
        template='plotly_white',
        showlegend=False
    )
    return fig


# ─────────────────────────────────────────────
# EDA 图表：4 - 缺失值分析
# ─────────────────────────────────────────────

def plot_missing_values(df: pd.DataFrame) -> go.Figure:
    """各字段缺失值比例柱状图。"""
    missing     = df.isnull().sum()
    missing_pct = (missing / len(df) * 100).round(2)
    # 按缺失比例降序排列
    missing_pct = missing_pct.sort_values(ascending=False)

    colors = ['#d62728' if v > 20 else '#ff7f0e' if v > 5 else '#2ca02c'
              for v in missing_pct.values]

    fig = go.Figure(go.Bar(
        x=missing_pct.index.tolist(),
        y=missing_pct.values,
        text=[f"{v:.1f}%" for v in missing_pct.values],
        textposition='outside',
        marker_color=colors
    ))
    fig.add_hline(y=5,  line_dash="dash", line_color="#ff7f0e",
                  annotation_text="5% 警戒线")
    fig.add_hline(y=20, line_dash="dash", line_color="#d62728",
                  annotation_text="20% 危险线")
    fig.update_layout(
        title=dict(text="各字段缺失值比例（绿<5%  橙5-20%  红>20%）", x=0.5),
        xaxis_title="字段名",
        yaxis_title="缺失比例（%）",
        yaxis=dict(range=[0, max(missing_pct.max() * 1.2, 25)]),
        template='plotly_white',
        height=450
    )
    return fig


# ─────────────────────────────────────────────
# EDA 图表：5 - 滚动统计
# ─────────────────────────────────────────────

def plot_rolling_stats(df: pd.DataFrame, target_col: str, window: int = 12) -> go.Figure:
    """目标变量滚动均值 + 滚动标准差（置信带）。"""
    s       = df[target_col].dropna()
    roll_m  = s.rolling(window).mean()
    roll_s  = s.rolling(window).std()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=s.index, y=s,
        name='原始值', mode='lines',
        line=dict(color='lightgrey', width=1)
    ))
    fig.add_trace(go.Scatter(
        x=s.index, y=roll_m,
        name=f'{window}期滚动均值', mode='lines',
        line=dict(color='steelblue', width=2)
    ))
    fig.add_trace(go.Scatter(
        x=list(s.index) + list(s.index[::-1]),
        y=list((roll_m + roll_s)) + list((roll_m - roll_s)[::-1]),
        fill='toself', fillcolor='rgba(70,130,180,0.15)',
        line=dict(color='rgba(255,255,255,0)'),
        name=f'±1σ 区间'
    ))
    fig.update_layout(
        title=dict(text=f"[{target_col}] 滚动统计（窗口={window}期）", x=0.5),
        yaxis_title=target_col,
        template='plotly_white',
        height=450,
        legend=dict(x=0.01, y=0.99)
    )
    return fig


# ─────────────────────────────────────────────
# EDA 图表：6 - 双轴联动图（每个底层变量 vs 目标）
# ─────────────────────────────────────────────

def plot_dual_axis_linkage(df: pd.DataFrame, feature_col: str, target_col: str) -> go.Figure:
    """
    双轴时序图：左轴显示底层变量，右轴显示目标收益率。
    用于直观观察两者的联动关系和领先滞后关系。
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Scatter(
        x=df.index, y=df[feature_col],
        name=feature_col, mode='lines',
        line=dict(color='#2ca02c', width=1.5)
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=df.index, y=df[target_col],
        name=target_col, mode='lines',
        line=dict(color='#d62728', width=1.5)
    ), secondary_y=True)

    fig.update_layout(
        title=dict(text=f"{feature_col}（左轴） vs {target_col}（右轴）", x=0.5),
        template='plotly_white',
        height=450,
        legend=dict(x=0.01, y=0.99),
        hovermode='x unified'
    )
    fig.update_yaxes(title_text=feature_col, secondary_y=False, color='#2ca02c')
    fig.update_yaxes(title_text=target_col, secondary_y=True, color='#d62728')
    return fig


# ─────────────────────────────────────────────
# EDA 图表：7 - 散点矩阵
# ─────────────────────────────────────────────

def plot_scatter_matrix(df: pd.DataFrame, max_cols: int = 10) -> go.Figure:
    """
    所有变量两两散点图（变量数 ≤ max_cols 时生成）。
    变量超过上限时仅取目标变量 + 前 max_cols-1 列特征。
    """
    cols = df.columns.tolist()
    if len(cols) > max_cols:
        cols = cols[:max_cols]
        df   = df[cols]

    fig = px.scatter_matrix(
        df.dropna(),
        dimensions=cols,
        title="散点矩阵（所有变量两两关系）",
        opacity=0.4
    )
    fig.update_traces(diagonal_visible=False, marker=dict(size=3))
    fig.update_layout(
        height=max(600, 100 * len(cols)),
        template='plotly_white'
    )
    return fig


# ─────────────────────────────────────────────
# 主入口：run_eda
# ─────────────────────────────────────────────

def run_eda(
    df: pd.DataFrame,
    target_col: str,
    output_dir: str = "output/figures/eda",
    max_scatter_cols: int = 10
) -> Dict[str, Tuple[str, str]]:
    """
    运行完整 EDA 流程，生成并导出所有 7 类图表。

    参数
    ----
    df          : 预处理前的原始 DataFrame（时间索引）
    target_col  : 目标变量列名
    output_dir  : 图表输出目录
    max_scatter_cols : 散点矩阵最大列数

    返回
    ----
    dict: {图表标识: (html路径, png路径)}
    """
    results: Dict[str, Tuple[str, str]] = {}
    feature_cols = [c for c in df.columns if c != target_col]

    # EDA-01：时间序列总览
    fig = plot_time_series_overview(df, title=f"时间序列总览（共 {len(df.columns)} 个变量）")
    results['time_series'] = export_figure(fig, "01_time_series_overview", output_dir)
    print("  [EDA-01] 时间序列总览 ✓")

    # EDA-02：相关性热力图
    fig = plot_correlation_heatmap(df)
    results['correlation'] = export_figure(fig, "02_correlation_heatmap", output_dir)
    print("  [EDA-02] 相关性热力图 ✓")

    # EDA-03：目标变量分布
    fig = plot_target_distribution(df, target_col)
    results['target_dist'] = export_figure(fig, "03_target_distribution", output_dir)
    print("  [EDA-03] 目标变量分布 ✓")

    # EDA-04：缺失值分析
    fig = plot_missing_values(df)
    results['missing'] = export_figure(fig, "04_missing_values", output_dir)
    print("  [EDA-04] 缺失值分析 ✓")

    # EDA-05：滚动统计
    fig = plot_rolling_stats(df, target_col, window=12)
    results['rolling_stats'] = export_figure(fig, "05_rolling_stats", output_dir)
    print("  [EDA-05] 滚动统计 ✓")

    # EDA-06：双轴联动图（每个特征变量）
    for i, col in enumerate(feature_cols, 1):
        fig = plot_dual_axis_linkage(df, col, target_col)
        key = f"dual_axis_{col}"
        results[key] = export_figure(fig, f"06_dual_axis_{i:02d}_{col}", output_dir)
    print(f"  [EDA-06] 双轴联动图 × {len(feature_cols)} ✓")

    # EDA-07：散点矩阵（变量数不超过限制时）
    if len(df.columns) <= max_scatter_cols:
        fig = plot_scatter_matrix(df, max_cols=max_scatter_cols)
        results['scatter_matrix'] = export_figure(fig, "07_scatter_matrix", output_dir)
        print("  [EDA-07] 散点矩阵 ✓")
    else:
        print(f"  [EDA-07] 变量数 {len(df.columns)} > {max_scatter_cols}，跳过散点矩阵")

    print(f"\n✅ EDA 完成，共生成 {len(results)} 张图表 → {output_dir}")
    return results
