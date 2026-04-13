# GeoPolitical-FX-Sentiment
## 地缘政治风险下的外汇与贵金属舆情高频策略

> **背景**：美伊战争地缘政治风险急剧拉升、全球能源被战争绑架、通胀可能走高
> **适用对象**：商业银行资金营运中心，外汇与贵金属交易员
> **资产范围**：G7 外汇 + XAU/USD、XAG/USD
> **数据源**：路透社新闻（Reuters Newswire）+ LLM 情感分析

---

## 文件说明

| 文件 | 内容 |
|------|------|
| `01_宏观背景洞察报告.md` | 美伊战争、能源市场、G7 央行政策、FX/贵金属格局全面分析 |
| `02_舆情驱动高频外汇贵金属策略方案.md` | 完整策略设计：框架、NSIF 因子、信号规则、风控体系、实施路线图 |
| `03_strategy_implementation.py` | Python 实现代码（Claude API + 情感分析 + NSIF + 信号生成 + 风控管理）|

---

## 快速开始

### 环境安装

```bash
pip install anthropic pandas numpy scipy
```

### 运行演示

```bash
export ANTHROPIC_API_KEY=sk-ant-xxxxx
python 03_strategy_implementation.py
```

### 核心流程

```
路透社新闻 → LLM（Claude Haiku）情感分析 → NSIF 因子
         → 信号生成（3层过滤）→ 风控检查 → 执行/拒绝
```

---

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `nsif_entry_threshold` | 0.35 | NSIF 开仓阈值 |
| `nsif_strong_threshold` | 0.65 | 强信号阈值 |
| `geo_risk_level` | 1 | 0=正常, 1=升级, 2=危机 |
| `max_position_pct` | 30% | 单资产最大仓位 |
| `max_holding_hours` | 4h | 最长持仓时间 |
| `daily_loss_limit` | 2% | 日亏损熔断 |
