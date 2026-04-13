"""
报告生成工具集：生成 .md 格式的债券因子挖掘研究报告

报告格式：Markdown (.md)，支持 GitHub Flavored Markdown，嵌入本地 PNG 图片路径。

报告章节结构：
  1. 执行摘要
  2. 数据说明
  3. EDA 分析（全部图表 + 解读）
  4. 数据预处理
  5. 因子构建（每因子独立小节）
  6. 因子检验结果（每因子独立小节：IC + 分层 + 稳健性）
  7. 因子汇总
  8. 结论与建议

内容规范：详见 references/04_report_specification.md
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────
# Markdown 报告生成
# ─────────────────────────────────────────────

def generate_md_report(report_data: Dict[str, Any], output_path: str) -> str:
    """
    生成 Markdown 格式研究报告。

    参数
    ----
    report_data : 包含 config, df_raw, df_processed, eda_results,
                  factor_meta, factor_results, summary_df, figures_dir
    output_path : 输出文件路径（.md）

    返回
    ----
    str: 输出文件路径
    """
    config         = report_data['config']
    df_raw         = report_data['df_raw']
    df_processed   = report_data['df_processed']
    eda_results    = report_data['eda_results']
    factor_meta    = report_data['factor_meta']
    factor_results = report_data['factor_results']
    summary_df     = report_data['summary_df']
    figures_dir    = report_data['figures_dir']

    lines: List[str] = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── 封面
    lines += [
        "# 债券类因子挖掘研究报告",
        "",
        f"> **生成时间**：{now}",
        f"> **数据频率**：{config.get('freq', 'N/A')}",
        f"> **目标变量**：{config.get('target_col', 'N/A')}",
        f"> **预测期**：未来 {config.get('forward_period', 'N/A')} 期",
        f"> **数据范围**：{str(df_raw.index.min())[:10]} ~ {str(df_raw.index.max())[:10]}",
        "",
        "---",
        ""
    ]

    # ── 第一章：执行摘要
    n_factors   = len(factor_results)
    qualified   = (summary_df['综合评级'] == '✅ 合格').sum() if len(summary_df) > 0 else 0
    potential   = (summary_df['综合评级'] == '⭐ 潜力').sum() if len(summary_df) > 0 else 0
    n_obs       = df_raw.shape[0]
    n_features  = df_raw.shape[1]

    lines += [
        "## 一、执行摘要",
        "",
        "### 研究概况",
        "",
        f"本报告基于 **{n_features} 个**底层数据变量，",
        f"以 **{config.get('target_col', '目标变量')}** 为预测标的，",
        f"通过系统化因子挖掘流程，共构建 **{n_factors} 个**候选因子，",
        f"并完成 IC 分析、分层回测、稳健性检验。",
        "",
        "### 核心结论",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 有效样本量 | {n_obs} 期 |",
        f"| 底层数据变量数 | {n_features} 个 |",
        f"| 候选因子总数 | {n_factors} 个 |",
        f"| 合格因子数（✅） | {qualified} 个 |",
        f"| 潜力因子数（⭐） | {potential} 个 |",
        f"| 排除因子数（❌） | {n_factors - qualified - potential} 个 |",
        "",
    ]

    # 合格因子列表
    if len(summary_df) > 0:
        qual_factors = summary_df[summary_df['综合评级'] == '✅ 合格']
        if len(qual_factors) > 0:
            lines.append("**推荐纳入因子库的合格因子：**")
            lines.append("")
            for _, row in qual_factors.iterrows():
                lines.append(
                    f"- **{row['因子代码']}**（{row['因子名称']}）："
                    f"IC均值={row['IC均值']}，IC_IR={row['IC_IR']}"
                )
            lines.append("")

    lines += ["---", ""]

    # ── 第二章：数据说明
    lines += [
        "## 二、数据说明",
        "",
        "### 2.1 底层数据概况",
        "",
        f"| 项目 | 详情 |",
        f"|------|------|",
        f"| 数据文件 | {config.get('data_path', 'N/A')} |",
        f"| 时间范围 | {str(df_raw.index.min())[:10]} ~ {str(df_raw.index.max())[:10]} |",
        f"| 数据频率 | {config.get('freq', 'N/A')} |",
        f"| 观测数量 | {n_obs} 期 |",
        f"| 变量数量 | {n_features} 列 |",
        "",
        "### 2.2 各变量描述统计",
        "",
    ]

    # 描述统计表
    desc = df_raw.describe().round(4)
    lines.append(_df_to_md_table(desc.reset_index().rename(columns={'index': '统计量'})))
    lines.append("")

    # 缺失值说明
    missing = df_raw.isnull().sum()
    missing_pct = (missing / len(df_raw) * 100).round(2)
    lines += [
        "### 2.3 缺失值情况",
        "",
        "| 字段 | 缺失数量 | 缺失比例 |",
        "|------|----------|----------|"
    ]
    for col in df_raw.columns:
        lines.append(f"| {col} | {missing[col]} | {missing_pct[col]:.1f}% |")
    lines += ["", "---", ""]

    # ── 第三章：EDA 分析
    lines += [
        "## 三、探索性数据分析（EDA）",
        "",
        "> 所有图表均使用 Plotly 生成，提供 HTML（交互式）和 PNG（报告嵌入）两种格式。",
        ""
    ]

    eda_descs = {
        'time_series':    ('EDA-01', '时间序列总览', '展示所有变量的完整时间序列，用于直观判断趋势性、季节性和结构性断点。'),
        'correlation':    ('EDA-02', '相关性热力图', '所有变量的 Pearson 相关系数矩阵。颜色越红相关性越强（正），越蓝越强（负）。'),
        'target_dist':    ('EDA-03', '目标变量分布', '目标变量的直方图和箱线图，用于评估分布形态、偏态和极端值。'),
        'missing':        ('EDA-04', '缺失值分析', '各字段缺失比例，绿色<5%、橙色5-20%、红色>20%。'),
        'rolling_stats':  ('EDA-05', '滚动统计图', '目标变量的12期滚动均值和±1σ置信带，反映均值和波动率的时变特征。'),
    }

    for key, (num, name, desc_text) in eda_descs.items():
        if key in eda_results:
            _, png_path = eda_results[key]
            rel_path    = _relative_path(png_path, output_path)
            lines += [
                f"### {num}：{name}",
                "",
                f"![{name}]({rel_path})",
                "",
                f"*{desc_text}*",
                ""
            ]

    # 双轴联动图
    dual_keys = [k for k in eda_results if k.startswith('dual_axis_')]
    if dual_keys:
        lines += ["### EDA-06：底层数据与目标变量联动分析", ""]
        for i, key in enumerate(dual_keys, 1):
            col_name = key.replace('dual_axis_', '')
            _, png_path = eda_results[key]
            rel_path    = _relative_path(png_path, output_path)
            lines += [
                f"**图 EDA-06-{i:02d}：{col_name} vs {config.get('target_col', '')}**",
                "",
                f"![{col_name}联动图]({rel_path})",
                ""
            ]

    lines += ["---", ""]

    # ── 第四章：数据预处理
    lines += [
        "## 四、数据预处理",
        "",
        "### 4.1 数据类型识别与处理策略",
        "",
        "根据各变量的统计特征，自动识别数据类型并选择相应的预处理方法：",
        "",
        "| 数据类型 | 缺失值方法 | 异常值方法 | 说明 |",
        "|----------|------------|------------|------|",
        "| 流量型（flow） | 前向填充（≤5期） | 1% 缩尾 | 机构净买入量 |",
        "| 存量型（level） | 线性插值 | 3σ 法则 | 持仓量、余额 |",
        "| 比率型（ratio） | 线性插值 | IQR 法则 | 利差、占比 |",
        "| 价格/收益率型（price） | 线性插值 | 不处理 | 国债收益率 |",
        "",
        "### 4.2 预处理后数据概况",
        "",
        f"- 预处理后有效样本数：**{df_processed.dropna().shape[0]}** 期",
        f"- 预处理后变量数：**{df_processed.shape[1]}** 列（含预测目标列）",
        "",
        "### 4.3 预测目标变量构造",
        "",
        f"预测目标定义为目标变量的未来 {config.get('forward_period', 'N')} 期变化量：",
        "",
        "```",
        f"target_fwd_change(t) = {config.get('target_col', 'Yield')}(t + {config.get('forward_period', 'N')}) - {config.get('target_col', 'Yield')}(t)",
        "```",
        "",
        "正值表示收益率上行，负值表示收益率下行。",
        "",
        "---",
        ""
    ]

    # ── 第五章：因子构建
    lines += [
        "## 五、因子构建",
        "",
        f"基于 {len(factor_meta)} 个底层数据变量，",
        f"运用机构行为分析框架和技术面分析方法，共构建 **{len(factor_meta)} 个**候选因子。",
        "",
        "### 5.1 因子构建汇总表",
        "",
        "| # | 因子代码 | 因子名称 | 类别 | 构建方法 | 预期方向 |",
        "|---|----------|----------|------|----------|----------|"
    ]

    for i, (fname, meta) in enumerate(factor_meta.items(), 1):
        formula_short = meta.get('formula', '-')[:60] + '...' \
                        if len(meta.get('formula', '-')) > 60 \
                        else meta.get('formula', '-')
        lines.append(
            f"| {i} | `{fname}` | {meta.get('name_cn', '-')} | "
            f"{meta.get('category', '-')} | {formula_short} | "
            f"{meta.get('expected_dir', '-')} |"
        )

    lines += ["", "### 5.2 各因子详细说明", ""]

    for i, (fname, meta) in enumerate(factor_meta.items(), 1):
        lines += [
            f"#### 因子 {i}：{meta.get('name_cn', fname)}（`{fname}`）",
            "",
            f"| 属性 | 内容 |",
            f"|------|------|",
            f"| 因子代码 | `{fname}` |",
            f"| 所属类别 | {meta.get('category', '-')} |",
            f"| 数据来源 | {meta.get('data_source', '-')} |",
            f"| 构建公式 | {meta.get('formula', '-')} |",
            f"| 业务释义 | {meta.get('description', '-')} |",
            f"| 预期方向 | {meta.get('expected_dir', '-')} |",
            ""
        ]

    lines += ["---", ""]

    # ── 第六章：因子检验结果（每因子）
    lines += [
        "## 六、因子检验结果",
        "",
        "### 检验方法说明",
        "",
        "- **IC 分析**：计算因子值与未来 N 期收益率变化的 Pearson 相关系数（滚动窗口=12期）",
        "- **Rank IC**：基于 Spearman 秩相关，对极端值更鲁棒",
        "- **IC_IR**：IC 均值 / IC 标准差，衡量预测稳定性",
        "- **分层分析**：因子值等分为 5 组，验证各组收益率变化的单调性",
        "- **稳健性检验**：将样本等分为 4 段，分别计算 IC，验证跨期一致性",
        "",
        "---",
        ""
    ]

    for fname, res in factor_results.items():
        meta     = factor_meta.get(fname, {})
        ic_stats = res.get('ic_stats', {})

        lines += [
            f"### {meta.get('name_cn', fname)}（`{fname}`）",
            ""
        ]

        # IC 统计摘要
        lines += [
            "**IC 统计摘要：**",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| IC 均值 | {ic_stats.get('mean_ic', '-')} |",
            f"| \|IC\| 均值 | {ic_stats.get('abs_ic', '-')} |",
            f"| IC_IR | {ic_stats.get('ic_ir', '-')} |",
            f"| IC 正向占比 | {ic_stats.get('ic_pos_pct', 0)*100:.1f}% |",
            f"| Rank IC 均值 | {res['rank_ic_series'].mean():.4f} |" \
                if res.get('rank_ic_series') is not None else "| Rank IC 均值 | - |",
            f"| 样本数 | {ic_stats.get('n_obs', '-')} |",
            ""
        ]

        # IC 图表
        ic_png = f"output/figures/factors/factor_{fname}_ic.png"
        if os.path.exists(ic_png):
            rel = _relative_path(ic_png, output_path)
            lines += [
                f"![{fname} IC分析]({rel})",
                "",
                f"*图：{meta.get('name_cn', fname)} IC 时序图（上：Pearson IC 柱状图 + Rank IC 折线；下：IC 分布直方图）*",
                ""
            ]

        # 分层分析
        layer_df = res.get('layer_returns', pd.DataFrame())
        if len(layer_df) > 0:
            lines += ["**分层分析结果：**", ""]
            lines.append(_df_to_md_table(layer_df[['group', 'mean', 'std', 'count', 'sharpe']]))
            lines.append("")

            ls_diff = layer_df['mean'].iloc[-1] - layer_df['mean'].iloc[0]
            lines.append(f"多空差异（Q5 - Q1）：**{ls_diff:+.6f}**")
            lines.append("")

        # 分层图表
        layer_png = f"output/figures/factors/factor_{fname}_layered.png"
        if os.path.exists(layer_png):
            rel = _relative_path(layer_png, output_path)
            lines += [
                f"![{fname} 分层分析]({rel})",
                "",
                f"*图：{meta.get('name_cn', fname)} 因子分层收益图（误差棒为 ±1 标准差）*",
                ""
            ]

        lines += ["---", ""]

    # ── 第七章：因子汇总
    lines += [
        "## 七、因子检验汇总",
        "",
        "### 7.1 全量因子评价表",
        ""
    ]

    if len(summary_df) > 0:
        lines.append(_df_to_md_table(summary_df))
        lines.append("")

    # 汇总图
    summary_png = "output/figures/factors/00_factor_summary_table.png"
    if os.path.exists(summary_png):
        rel = _relative_path(summary_png, output_path)
        lines += [
            f"![因子汇总表]({rel})",
            "",
            "*图：因子检验结果汇总（绿=合格，黄=潜力，红=不合格）*",
            ""
        ]

    # 汇总条形图
    comparison_png = "output/figures/factors/ic_comparison.png"
    if os.path.exists(comparison_png):
        rel = _relative_path(comparison_png, output_path)
        lines += [
            f"![IC对比图]({rel})",
            "",
            "*图：所有因子 IC 均值对比（绿=正向预测，红=负向预测，虚线=±0.05 门槛）*",
            ""
        ]

    lines += ["---", ""]

    # ── 第八章：结论与建议
    lines += [
        "## 八、结论与建议",
        "",
        "### 8.1 合格因子推荐",
        ""
    ]

    if len(summary_df) > 0:
        qual = summary_df[summary_df['综合评级'] == '✅ 合格']
        if len(qual) > 0:
            lines.append("以下因子通过全部检验，建议纳入司库量化策略因子库：")
            lines.append("")
            lines.append("| 因子代码 | 因子名称 | IC均值 | IC_IR | 评级 |")
            lines.append("|----------|----------|--------|-------|------|")
            for _, row in qual.iterrows():
                lines.append(
                    f"| `{row['因子代码']}` | {row['因子名称']} | "
                    f"{row['IC均值']} | {row['IC_IR']} | {row['综合评级']} |"
                )
            lines.append("")
        else:
            lines.append("> 本次分析未发现满足全部条件的合格因子，建议扩充底层数据或调整预测期。")
            lines.append("")

        pot = summary_df[summary_df['综合评级'] == '⭐ 潜力']
        if len(pot) > 0:
            lines += [
                "### 8.2 潜力因子",
                "",
                "以下因子满足部分条件，建议结合业务判断后在组合使用：",
                "",
                "| 因子代码 | 因子名称 | IC均值 | IC_IR | 评级 |",
                "|----------|----------|--------|-------|------|"
            ]
            for _, row in pot.iterrows():
                lines.append(
                    f"| `{row['因子代码']}` | {row['因子名称']} | "
                    f"{row['IC均值']} | {row['IC_IR']} | {row['综合评级']} |"
                )
            lines.append("")

    lines += [
        "### 8.3 后续建议",
        "",
        "1. **因子合成**：对合格因子进行 IC 加权合成，构建综合得分信号",
        "2. **信号阈值**：通过历史分位数确定做多/做空信号的触发阈值",
        "3. **策略回测**：基于合成信号构建利率趋势跟踪策略并进行历史回测",
        "4. **数据扩充**：补充宏观经济（CPI、PMI）和资金面（DR007）数据，丰富因子类型",
        "5. **定期更新**：建议每季度重新检验因子有效性，剔除失效因子",
        "",
        "---",
        "",
        "## 附录A：运行环境",
        "",
        "| 项目 | 信息 |",
        "|------|------|",
        f"| 报告生成时间 | {now} |",
        f"| 数据文件 | {config.get('data_path', 'N/A')} |",
        "| 技能版本 | bond-factor-miner v1.0.0 |",
        "| Python 主要依赖 | pandas, numpy, plotly, scipy |",
        "",
        "---",
        "",
        "## 附录B：核心源代码",
        "",
        "> 本附录收录技能执行过程中的核心实现代码，供人工核验因子构建逻辑和检验方法。",
        "",
    ]

    for script_name, section_title in [
        ("pipeline.py",           "B.1 执行流水线（pipeline.py）"),
        ("preprocessing.py",      "B.2 数据预处理（preprocessing.py）"),
        ("factor_engineering.py", "B.3 因子构建（factor_engineering.py）"),
        ("factor_testing.py",     "B.4 因子检验（factor_testing.py）"),
    ]:
        code = _read_script_code(script_name)
        lines += [f"### {section_title}", "", "```python", code, "```", ""]

    lines += [
        "---",
        "",
        f"*本报告由 bond-factor-miner 技能自动生成 | 生成时间：{now}*",
        ""
    ]

    # 写入文件
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"✅ Markdown 报告已生成：{output_path}")
    return output_path


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _read_script_code(script_name: str) -> str:
    """读取 scripts/ 目录下指定脚本的源代码，用于嵌入报告附录。"""
    candidates = [
        os.path.join("scripts", script_name),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
    return f"# [{script_name} 文件未找到，请检查 scripts/ 目录]"


def _df_to_md_table(df: pd.DataFrame) -> str:
    """将 DataFrame 转换为 GitHub Flavored Markdown 表格字符串。"""
    cols   = df.columns.tolist()
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "| " + " | ".join("---" for _ in cols) + " |"
    rows   = []
    for _, row in df.iterrows():
        rows.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join([header, sep] + rows)


def _relative_path(target_path: str, base_file: str) -> str:
    """
    计算从 base_file 所在目录到 target_path 的相对路径。
    用于 Markdown 图片引用。
    """
    base_dir = os.path.dirname(os.path.abspath(base_file))
    abs_target = os.path.abspath(target_path)
    try:
        return os.path.relpath(abs_target, base_dir).replace('\\', '/')
    except ValueError:
        # Windows 跨盘符时无法计算相对路径，返回绝对路径
        return abs_target.replace('\\', '/')
