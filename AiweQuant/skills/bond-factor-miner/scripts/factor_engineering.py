"""
特征工程工具集：债券因子构建

职责：
  - 基于机构行为数据构建六类候选因子
  - 提供因子元数据（用于报告生成）
  - 支持自定义扩展

因子分类：机构行为 | 宏观经济 | 资金面 | 技术面 | 政策面 | 情绪面
详细说明见：references/02_factor_taxonomy.md
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any


# ─────────────────────────────────────────────
# 因子构建器
# ─────────────────────────────────────────────

class BondFactorBuilder:
    """
    债券因子构建器。

    使用方式
    --------
    builder = BondFactorBuilder(df_aligned, target_col='yield_30y')
    factors_df = builder.build_all_factors()
    metadata   = builder.get_factor_metadata()
    """

    def __init__(self, df: pd.DataFrame, target_col: str):
        self.df         = df.copy()
        self.target_col = target_col
        self.factors: Dict[str, pd.Series] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

        # 自动识别特征列（排除目标列和预测目标列）
        self.feature_cols = [
            c for c in df.columns
            if c not in (target_col, 'target_fwd_change')
        ]

    # ─────────────────────────────────────────
    # 机构行为类因子
    # ─────────────────────────────────────────

    def build_net_buying_factor(self, col: str) -> pd.Series:
        """机构净买入流量因子：直接使用净买入量"""
        name = f"flow_net_{col}"
        s = self.df[col].copy().rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': f'{col} 净买入量',
            'formula': 'Flow_Net(t) = NetBuy(t)',
            'description': '直接反映机构当期配置意愿。净买入量增加表明机构看多，推动收益率下行',
            'expected_dir': '负相关（净买入↑ → 收益率↓）',
            'data_source': col
        })
        return s

    def build_flow_ma_factor(self, col: str, window: int = 4) -> pd.Series:
        """净买入量滚动均值因子：平滑短期噪声，反映趋势性配置"""
        name = f"flow_ma{window}_{col}"
        s = self.df[col].rolling(window).mean().rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': f'{col} {window}期滚动均值',
            'formula': f'Flow_MA(t,{window}) = Mean(NetBuy(t-{window}+1),...,NetBuy(t))',
            'description': f'平滑短期波动，反映 {window} 期内机构配置的趋势性意愿',
            'expected_dir': '负相关',
            'data_source': col
        })
        return s

    def build_flow_mom_factor(self, col: str) -> pd.Series:
        """净买入量环比变化率因子：捕捉边际加速/减速信号"""
        name = f"flow_mom_{col}"
        eps = 1e-6
        mom = self.df[col].diff() / (self.df[col].shift(1).abs() + eps)
        s = mom.rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': f'{col} 净买入环比变化率',
            'formula': 'Flow_MoM(t) = ΔNetBuy(t) / |NetBuy(t-1)|',
            'description': '边际变化往往是趋势转折的早期信号，净买入加速预示持续看多',
            'expected_dir': '负相关（加速增持↑ → 收益率↓）',
            'data_source': col
        })
        return s

    def build_flow_cumsum_factor(self, col: str, window: int = 12) -> pd.Series:
        """滚动累积净买入量因子：反映中期趋势性建仓力度"""
        name = f"flow_cumsum{window}_{col}"
        s = self.df[col].rolling(window).sum().rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': f'{col} {window}期累积净买入',
            'formula': f'Flow_Cumsum(t,{window}) = Sum(NetBuy(t-{window}+1),...,NetBuy(t))',
            'description': f'反映机构近 {window} 期的累计配置力度，捕捉中期趋势性建仓行为',
            'expected_dir': '负相关',
            'data_source': col
        })
        return s

    def build_flow_zscore_factor(self, col: str, window: int = 52) -> pd.Series:
        """净买入量滚动 Z-score 因子：消除量级差异，反映相对异常程度"""
        name = f"flow_zscore{window}_{col}"
        roll_mean = self.df[col].rolling(window).mean()
        roll_std  = self.df[col].rolling(window).std()
        s = ((self.df[col] - roll_mean) / (roll_std + 1e-10)).rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': f'{col} {window}期滚动Z-score',
            'formula': f'Z-Score(t,{window}) = (X(t) - Mean(t,{window})) / Std(t,{window})',
            'description': '标准化处理消除量级差异，反映当前净买入量相对历史的异常程度（正值=历史高位）',
            'expected_dir': '负相关（高Z-score → 超常规增持 → 收益率↓）',
            'data_source': col
        })
        return s

    def build_flow_composite_factor(self, cols: List[str]) -> pd.Series:
        """多机构综合净买入因子：等权合并多机构信号"""
        name = "flow_composite"
        # 各列先 Z-score 标准化，再等权平均
        z_series = []
        for col in cols:
            z = (self.df[col] - self.df[col].mean()) / (self.df[col].std() + 1e-10)
            z_series.append(z)
        s = pd.concat(z_series, axis=1).mean(axis=1).rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': '多机构综合净买入因子',
            'formula': f'Composite(t) = EqualWeight({", ".join(cols)}_zscore)',
            'description': '综合多类机构信号（等权），避免单一机构数据噪声，全面反映市场配置倾向',
            'expected_dir': '负相关',
            'data_source': '|'.join(cols)
        })
        return s

    def build_flow_divergence_factor(self, cols: List[str]) -> pd.Series:
        """机构行为分歧度因子：标准差衡量机构间分歧"""
        name = "flow_divergence"
        s = self.df[cols].std(axis=1).rename(name)
        self._add_factor(name, s, {
            'category': '机构行为',
            'name_cn': '机构买卖行为分歧度',
            'formula': f'Divergence(t) = Std({", ".join(cols)})',
            'description': '分歧度高时，市场方向不确定性增大，往往预示收益率波动放大',
            'expected_dir': '正相关（分歧↑ → 不确定性↑ → 收益率波动↑）',
            'data_source': '|'.join(cols)
        })
        return s

    # ─────────────────────────────────────────
    # 技术面类因子（基于目标收益率本身）
    # ─────────────────────────────────────────

    def build_momentum_factor(self, window: int = 4) -> pd.Series:
        """收益率动量因子：近期趋势延续"""
        name = f"tech_momentum_{window}"
        s = self.df[self.target_col].diff(window).rename(name)
        self._add_factor(name, s, {
            'category': '技术面',
            'name_cn': f'{window}期收益率动量',
            'formula': f'Momentum(t,{window}) = Yield(t) - Yield(t-{window})',
            'description': '利率市场存在趋势延续性。近期下行趋势往往因机构追涨而延续',
            'expected_dir': '正相关（近期下行 → 趋势延续 → 未来继续下行）',
            'data_source': self.target_col
        })
        return s

    def build_ma_deviation_factor(self, short_w: int = 4, long_w: int = 52) -> pd.Series:
        """收益率均线偏差因子：均值回归信号"""
        name = f"tech_ma_dev_{short_w}_{long_w}"
        ma_long = self.df[self.target_col].rolling(long_w).mean()
        s = ((self.df[self.target_col] - ma_long) / (ma_long + 1e-10) * 100).rename(name)
        self._add_factor(name, s, {
            'category': '技术面',
            'name_cn': f'收益率与{long_w}期均线偏差(%)',
            'formula': f'MA_Dev(t) = (Yield(t)-MA_{long_w}(t)) / MA_{long_w}(t) × 100',
            'description': '收益率大幅高于长期均线表示高估，存在均值回归下行压力',
            'expected_dir': '正相关（高偏差 → 高估 → 均值回归 → 收益率↓，负向预测）',
            'data_source': self.target_col
        })
        return s

    def build_quantile_factor(self, window: int = 52) -> pd.Series:
        """收益率历史分位数因子：衡量当前估值水平"""
        name = f"tech_quantile_{window}"
        s = self.df[self.target_col].rolling(window).apply(
            lambda x: pd.Series(x).rank().iloc[-1] / len(x) * 100, raw=False
        ).rename(name)
        self._add_factor(name, s, {
            'category': '技术面',
            'name_cn': f'{window}期滚动历史分位数',
            'formula': f'Quantile(t,{window}) = Rank(Yield(t)) / {window} × 100',
            'description': '分位数高表示收益率处于历史高位，配置价值强，倾向均值回归下行',
            'expected_dir': '正相关（分位数高 → 估值偏高 → 收益率下行）',
            'data_source': self.target_col
        })
        return s

    # ─────────────────────────────────────────
    # 构建全部因子（自动遍历特征列）
    # ─────────────────────────────────────────

    def build_all_factors(self) -> pd.DataFrame:
        """
        基于 self.feature_cols 自动构建所有机构行为因子，
        并附加技术面因子（基于目标收益率）。

        返回
        ----
        pd.DataFrame：索引与 self.df 一致，列为所有候选因子
        """
        # 机构行为类因子（对每个特征列构建 5 类因子）
        for col in self.feature_cols:
            self.build_net_buying_factor(col)
            self.build_flow_ma_factor(col, window=4)
            self.build_flow_ma_factor(col, window=12)
            self.build_flow_mom_factor(col)
            self.build_flow_cumsum_factor(col, window=12)
            self.build_flow_zscore_factor(col, window=52)

        # 多机构综合 & 分歧（当特征列 ≥ 2 时）
        if len(self.feature_cols) >= 2:
            self.build_flow_composite_factor(self.feature_cols)
            self.build_flow_divergence_factor(self.feature_cols)

        # 技术面因子（基于目标收益率）
        self.build_momentum_factor(window=4)
        self.build_momentum_factor(window=12)
        self.build_ma_deviation_factor(long_w=52)
        self.build_quantile_factor(window=52)

        factors_df = pd.DataFrame(self.factors, index=self.df.index)
        print(f"✅ 共构建 {len(factors_df.columns)} 个候选因子")
        return factors_df

    # ─────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────

    def _add_factor(
        self, name: str, series: pd.Series, meta: Dict[str, Any]
    ) -> None:
        """注册因子及其元数据。"""
        self.factors[name] = series
        meta['factor_code'] = name
        self._metadata[name] = meta

    def get_factor_metadata(self) -> Dict[str, Dict[str, Any]]:
        """返回所有已构建因子的元数据字典。"""
        return self._metadata

    def get_factor_list(self) -> List[str]:
        """返回已构建的因子名称列表。"""
        return list(self.factors.keys())
