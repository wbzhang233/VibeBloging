---
name: bond-factor-miner
description: |
  债券类因子挖掘技能，专为银行资产负债管理部司库量化策略研究设计。
  适用场景：给定底层数据（如保险、基金、券商等机构超长国债净买入量）和待预测标的
  （如30年期国债收益率），执行完整因子挖掘流程：
  EDA探索 → 数据预处理 → 特征工程构建因子 → 因子检验 → 研究报告生成（.md）。
  所有可视化使用 Plotly 实现，导出 HTML 和 PNG 双格式。
disable-model-invocation: false
metadata:
  version: "1.0.0"
  owner: "资产负债管理部"
  domain: "固定收益量化研究"
  tags: ["债券", "因子挖掘", "量化策略", "司库管理"]
---

# bond-factor-miner：债券类因子挖掘技能

> 适用角色：资产负债管理部资金交易员 / 固定收益量化研究员
> 技能定位：给定数据 → 全流程因子挖掘 → 输出研究报告

---

## 一、知识库

| 文档 | 内容 |
|------|------|
| [`references/01_business_background.md`](references/01_business_background.md) | 业务背景 + EDA 分析解读指引 |
| [`references/02_factor_taxonomy.md`](references/02_factor_taxonomy.md) | 6 大类因子分类框架与构建规范 |
| [`references/03_factor_testing_guide.md`](references/03_factor_testing_guide.md) | IC / Rank IC / 分层 / 稳健性检验方法论 |
| [`references/04_report_specification.md`](references/04_report_specification.md) | 研究报告内容规范（章节结构、因子展开要求、图表解读）|

---

## 二、目录结构

```
bond-factor-research/
├── data/
│   ├── raw/                    # 原始数据（用户提供）
│   └── processed/              # 预处理后数据
├── output/
│   ├── figures/
│   │   ├── eda/                # EDA 图表（HTML + PNG）
│   │   └── factors/            # 因子检验图表（HTML + PNG）
│   ├── factors/                # 因子数据（CSV）+ 元数据（JSON）
│   └── reports/                # 最终报告（.md）
└── logs/
    └── run_config.json         # 本次运行配置
```

---

## 三、输入规范

启动技能时，**只需用户提供以下三项**，其余参数由技能自动推断：

| 必填项 | 说明 | 示例 |
|--------|------|------|
| **数据文件** | 直接上传，或提供路径（CSV / Excel） | `data/raw/flow.csv` |
| **底层数据说明** | 各字段业务含义和单位 | `col1=保险超长国债净买入量（亿元）` |
| **待预测标的说明** | 目标列名、指标含义和单位 | `yield_30y，30年期国债收益率，%` |

> `date_col` 自动识别，`freq` 由 `pd.infer_freq()` 检测（失败时默认 `W`），`forward_period` 默认 **4 期**。

---

## 四、执行步骤

所有步骤的完整实现集中在 [`scripts/pipeline.py`](scripts/pipeline.py)，此处只列出调用入口。

---

### Step A：项目初始化

> 创建目录结构，加载数据，自动推断时间列和数据频率，写入运行配置。

```python
from scripts.pipeline import init_project

config, df = init_project(
    data_path        = "<文件路径>",
    target_col       = "<目标列名>",
    bottom_data_desc = "<底层数据说明>",
    target_desc      = "<待预测标的说明>",
)
```

---

### Step B：数据加载与探索性分析（EDA）

> 生成 7 类 EDA 图表（时序 / 相关性 / 分布 / 缺失值 / 滚动统计 / 双轴联动 / 散点矩阵），
> 全部导出 HTML + PNG。解读要点见 [`references/01_business_background.md`](references/01_business_background.md) §3。

```python
from scripts.pipeline import run_eda

eda_results = run_eda(config, df)
```

---

### Step C：数据预处理

> 自动识别数据类型 → 缺失值处理 → 去极值 → 统一时间频率 → 构造预测目标列 `target_fwd_change`。

```python
from scripts.pipeline import run_preprocessing

df_aligned = run_preprocessing(config, df)
```

预处理决策矩阵：

| 数据类型 | 缺失值方法 | 异常值方法 |
|----------|------------|------------|
| 流量型（flow） | 前向填充（≤5期） | 1% 缩尾 |
| 存量型（level） | 线性插值 | 3σ 法则 |
| 比率型（ratio） | 线性插值 | IQR 法则 |
| 价格/收益率型（price） | 线性插值 | 不处理 |

---

### Step D：特征工程与因子构建

> 基于底层数据构建全部候选因子（机构行为类 × 6 种衍生 + 技术面类），
> 保存因子数据（CSV）和元数据（JSON）。
> 因子分类与构建规范见 [`references/02_factor_taxonomy.md`](references/02_factor_taxonomy.md)。

```python
from scripts.pipeline import run_factor_engineering

factors_df, factor_meta = run_factor_engineering(config, df_aligned)
```

报告第五章须对每个因子独立展开：**名称 / 类别 / 公式 / 业务释义 / 预期方向**。

---

### Step E：因子检验与可视化

> 对所有候选因子执行五层检验，每因子生成 IC 图 + 分层图，输出汇总表和 IC 对比图。
> 检验方法见 [`references/03_factor_testing_guide.md`](references/03_factor_testing_guide.md)。

```python
from scripts.pipeline import run_factor_testing

factor_results, summary_df = run_factor_testing(
    config, factors_df, df_aligned, factor_meta
)
```

合格因子判定标准：`|IC|≥0.05` 且 `IC_IR≥0.3` 且方向性明确（正/负向占比≥55%）。

---

### Step F：报告生成

> 生成完整 Markdown 研究报告，图文并茂，逐步骤记录结果，每个因子在第五章和第六章各有独立小节。
> 报告内容规范见 [`references/04_report_specification.md`](references/04_report_specification.md)。

```python
from scripts.pipeline import run_report

md_path = run_report(
    config, df, df_aligned, eda_results, factor_meta, factor_results, summary_df
)
```

---

## 五、可视化规范

- **框架**：100% Plotly，每图导出 `.html`（交互式）+ `.png`（报告嵌入，1200×600 @2x）
- **颜色**：正值 / 利多绿色 `#2ca02c`，负值 / 利空红色 `#d62728`
- **图注**：每张图下方须有解读文字（图表显示了什么 / 说明了什么 / 有何注意点）

导出函数：[`scripts/visualization.py`](scripts/visualization.py) → `export_figure(fig, name, output_dir)`

---

## 六、注意事项

1. **前视偏差**：因子只用 t 期及之前数据；`target_fwd_change` 通过 `shift(-N)` 构造
2. **最小样本量**：滚动 IC 窗口 = 12 期，有效样本需 ≥ 36 期
3. **多重共线性**：因子相 关性 > 0.8 时在报告中标注，保留 IC_IR 更高的一个
4. **经济含义优先**：统计显著但无业务逻辑支撑的因子需在报告中单独说明
5. **报告完整性**：每个候选因子必须在第五章和第六章各有独立章节，不得省略
