"""
可视化工具集：债券因子研究专用 Plotly 图表

职责：提供因子检验阶段所有图表，以及通用的 export_figure 函数。
所有图表均导出 HTML（交互式）+ PNG（高清，用于报告嵌入）。
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────
# 通用导出函数
# ─────────────────────────────────────────────

def export_figure(fig: go.Figure, name: str, output_dir: str) -> Tuple[str, str]:
    """
    导出 Plotly 图表为 HTML 和 PNG 双格式。

    参数
    ----
    fig        : Plotly Figure 对象
    name       : 文件名（不含后缀）
    output_dir : 输出目录（不存在则自动创建）

    返回
    ----
    (html_path, png_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    html_path = os.path.join(output_dir, f"{name}.html")
    png_path  = os.path.join(output_dir, f"{name}.png")
    fig.write_html(html_path)
    fig.write_image(png_path, width=1200, height=600, scale=2)
    return html_path, png_path


# ─────────────────────────────────────────────
# 因子图表：IC 时序图
# ─────────────────────────────────────────────

def plot_ic_series(
    ic_series: pd.Series,
    rank_ic_series: Optional[pd.Series],
    factor_name: str
) -> go.Figure:
    """
    绘制因子 IC 时序图 + IC 分布直方图（2 行布局）。

    上图：Pearson IC 柱状图（正绿负红）+ 均值虚线 + Rank IC 折线
    下图：IC 分布直方图（检验是否接近正态）
    """
    mean_ic     = ic_series.mean()
    ic_ir       = mean_ic / ic_series.std() if ic_series.std() > 0 else 0
    pos_pct     = (ic_series > 0).mean() * 100

    bar_colors  = ['#2ca02c' if v >= 0 else '#d62728' for v in ic_series.values]

    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=[
            f"{factor_name}  IC 时序（Pearson）",
            "IC 分布直方图"
        ],
        row_heights=[0.65, 0.35],
        vertical_spacing=0.1
    )

    # 上图：IC 柱状图
    fig.add_trace(go.Bar(
        x=ic_series.index, y=ic_series.values,
        name='Pearson IC', marker_color=bar_colors, opacity=0.8
    ), row=1, col=1)

    # 均值虚线
    fig.add_hline(y=mean_ic, line_dash="dash", line_color="royalblue",
                  annotation_text=f"均值 {mean_ic:.4f}", row=1, col=1)
    fig.add_hline(y=0, line_dash="solid", line_color="grey",
                  line_width=0.5, row=1, col=1)

    # 叠加 Rank IC 折线
    if rank_ic_series is not None:
        fig.add_trace(go.Scatter(
            x=rank_ic_series.index, y=rank_ic_series.values,
            name='Rank IC', mode='lines',
            line=dict(color='orange', width=1.5, dash='dot')
        ), row=1, col=1)

    # 下图：IC 分布
    fig.add_trace(go.Histogram(
        x=ic_series.values, nbinsx=25,
        name='IC 分布', marker_color='steelblue', opacity=0.7
    ), row=2, col=1)
    fig.add_vline(x=mean_ic, line_dash="dash", line_color="royalblue",
                  row=2, col=1)
    fig.add_vline(x=0, line_dash="solid", line_color="grey",
                  line_width=0.8, row=2, col=1)

    # 统计摘要注释
    summary_text = (
        f"IC均值={mean_ic:.4f} | IC_IR={ic_ir:.3f} | "
        f"正向占比={pos_pct:.1f}%"
    )
    fig.add_annotation(
        xref='paper', yref='paper', x=0.5, y=1.02,
        text=summary_text, showarrow=False,
        font=dict(size=11, color='dimgray'),
        xanchor='center'
    )

    fig.update_layout(
        title=dict(text=f"[{factor_name}] 因子 IC 分析", x=0.5),
        height=650, template='plotly_white',
        showlegend=True,
        legend=dict(x=0.01, y=0.97)
    )
    return fig


# ─────────────────────────────────────────────
# 因子图表：分层收益图
# ─────────────────────────────────────────────

def plot_factor_layered_returns(
    layer_df: pd.DataFrame,
    factor_name: str
) -> go.Figure:
    """
    因子分层（Quintile）分析图。

    layer_df 须包含列：group, mean, std, count
    """
    groups  = layer_df['group'].tolist()
    means   = layer_df['mean'].tolist()
    stds    = layer_df['std'].tolist()
    counts  = layer_df['count'].tolist()

    # 颜色：Q1 最深绿（因子低分组），Q5 最深红（因子高分组）
    palette = ['#1a7a1a', '#5aab5a', '#aaaaaa', '#d06060', '#a81a1a']
    colors  = (palette * 10)[:len(groups)]

    fig = go.Figure()

    # 柱状图
    fig.add_trace(go.Bar(
        x=groups, y=means,
        error_y=dict(type='data', array=stds, visible=True),
        name='各组平均收益率变化',
        marker_color=colors,
        text=[f"{v:.4f}" for v in means],
        textposition='outside'
    ))

    # 多空差异注释
    if len(means) >= 2:
        ls_diff = means[-1] - means[0]
        fig.add_annotation(
            x=groups[-1], y=means[-1],
            text=f"多空差: {ls_diff:+.4f}",
            showarrow=True, arrowhead=2,
            font=dict(size=11, color='black'),
            ay=-30
        )

    # 零轴
    fig.add_hline(y=0, line_dash="solid", line_color="grey", line_width=0.8)

    fig.update_layout(
        title=dict(text=f"[{factor_name}] 因子分层分析（5 分组）", x=0.5),
        xaxis_title="因子分组（Q1=低分 → Q5=高分）",
        yaxis_title="未来 N 期目标变量平均变化",
        template='plotly_white',
        height=480,
        showlegend=False
    )
    return fig


# ─────────────────────────────────────────────
# 因子图表：汇总表
# ─────────────────────────────────────────────

def plot_factor_summary_table(summary_df: pd.DataFrame) -> go.Figure:
    """
    将因子检验汇总 DataFrame 渲染为可视化表格（Plotly Table）。

    summary_df 须包含：factor_name, category, mean_ic, abs_ic,
                       ic_ir, mean_rank_ic, ic_pos_pct, is_qualified
    """
    # 行背景颜色
    bg_colors = []
    for _, row in summary_df.iterrows():
        q = row.get('is_qualified', '')
        if q == '✅ 合格':
            bg_colors.append('#d4edda')
        elif q == '⭐ 潜力':
            bg_colors.append('#fff3cd')
        else:
            bg_colors.append('#f8d7da')

    col_order  = [c for c in summary_df.columns]
    cell_vals  = [summary_df[c].tolist() for c in col_order]
    cell_colors = [bg_colors] * len(col_order)

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=col_order,
            fill_color='#003366',
            font=dict(color='white', size=12),
            align='center',
            height=32
        ),
        cells=dict(
            values=cell_vals,
            fill_color=cell_colors,
            align='center',
            font=dict(size=11),
            height=28
        )
    )])
    fig.update_layout(
        title=dict(text="因子检验结果汇总表", x=0.5),
        height=max(300, 45 * (len(summary_df) + 2)),
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig


# ─────────────────────────────────────────────
# 因子图表：稳健性子区间 IC 柱状图
# ─────────────────────────────────────────────

def plot_stability_ic(stability_df: pd.DataFrame, factor_name: str) -> go.Figure:
    """绘制子区间 IC 柱状图，评估跨时期稳定性。"""
    periods = stability_df['period'].tolist()
    ics     = stability_df['ic'].tolist()
    colors  = ['#2ca02c' if v >= 0 else '#d62728' for v in ics]

    fig = go.Figure(go.Bar(
        x=periods, y=ics,
        marker_color=colors,
        text=[f"{v:.4f}" for v in ics],
        textposition='outside'
    ))
    fig.add_hline(y=0, line_dash="solid", line_color="grey", line_width=0.8)

    # 标注时间范围
    if 'start' in stability_df.columns:
        for i, row in stability_df.iterrows():
            fig.add_annotation(
                x=row['period'],
                y=min(ics) - 0.02,
                text=f"{str(row['start'])[:7]}~{str(row['end'])[:7]}",
                showarrow=False,
                font=dict(size=9, color='dimgray'),
                xanchor='center'
            )

    fig.update_layout(
        title=dict(text=f"[{factor_name}] 稳健性检验（子区间 IC）", x=0.5),
        xaxis_title="子区间",
        yaxis_title="IC 值",
        template='plotly_white',
        height=430
    )
    return fig


# ─────────────────────────────────────────────
# 综合图表：所有因子 IC 均值对比
# ─────────────────────────────────────────────

def plot_ic_comparison(summary_df: pd.DataFrame) -> go.Figure:
    """水平条形图：所有因子的 IC 均值对比（按绝对值降序）。"""
    df = summary_df.copy().sort_values('abs_ic', ascending=True)
    colors = ['#2ca02c' if v >= 0 else '#d62728' for v in df['mean_ic']]

    fig = go.Figure(go.Bar(
        x=df['mean_ic'],
        y=df['factor_name'],
        orientation='h',
        marker_color=colors,
        text=[f"{v:.4f}" for v in df['mean_ic']],
        textposition='outside'
    ))
    fig.add_vline(x=0.05,  line_dash="dash", line_color="#ff7f0e",
                  annotation_text="|IC|=0.05 门槛")
    fig.add_vline(x=-0.05, line_dash="dash", line_color="#ff7f0e")
    fig.add_vline(x=0, line_dash="solid", line_color="grey", line_width=0.8)

    fig.update_layout(
        title=dict(text="所有因子 IC 均值对比（绿=正向预测，红=负向预测）", x=0.5),
        xaxis_title="IC 均值",
        template='plotly_white',
        height=max(400, 30 * len(df) + 100),
        margin=dict(l=180)
    )
    return fig
