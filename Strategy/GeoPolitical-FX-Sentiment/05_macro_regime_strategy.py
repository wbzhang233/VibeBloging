"""
宏观情景驱动多因子高频策略实现
Macro Regime-Driven Multi-Factor HF Strategy for FX & Precious Metals

与 03_strategy_implementation.py（NSIF 驱动）完全不同的架构：
  - 四因子信号矩阵（NSI + Lead-Lag + Regime + BoJ Tracker）
  - LLM 做宏观情景研判而非逐条新闻情感提取
  - 状态机驱动的仓位管理

依赖:
    pip install anthropic pandas numpy
"""

import json
import math
import time
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
from collections import deque
from enum import Enum

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("macro-regime-strategy")


# ══════════════════════════════════════════════════════════════════════════════
# 1. 核心枚举与常量
# ══════════════════════════════════════════════════════════════════════════════

class Regime(Enum):
    """宏观情景状态机的四种状态"""
    ESCALATION   = "A"   # 地缘紧张升级
    DIGESTION    = "B"   # 恐慌消化
    DEESCALATION = "C"   # 地缘缓和
    DATA_DRIVEN  = "D"   # 宏观数据驱动


class Bias(Enum):
    STRONG_BULL = "strong_bull"
    BULL        = "bull"
    NEUTRAL     = "neutral"
    BEAR        = "bear"
    STRONG_BEAR = "strong_bear"

    def to_direction(self) -> int:
        return {
            "strong_bull": 1, "bull": 1, "neutral": 0,
            "bear": -1, "strong_bear": -1,
        }[self.value]

    def to_strength(self) -> float:
        return {
            "strong_bull": 1.0, "bull": 0.6, "neutral": 0.0,
            "bear": 0.6, "strong_bear": 1.0,
        }[self.value]


ASSETS = ["XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD",
          "USD/JPY", "USD/CAD", "USD/CHF", "AUD/USD"]

# 各状态下的风险预算比例
REGIME_RISK_BUDGET = {
    Regime.ESCALATION:   0.70,
    Regime.DIGESTION:    0.20,
    Regime.DEESCALATION: 0.50,
    Regime.DATA_DRIVEN:  0.40,
}


# ══════════════════════════════════════════════════════════════════════════════
# 2. 数据结构
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NewsHeadline:
    """新闻标题（不需要正文，本策略只做批量研判）"""
    news_id: str
    timestamp: datetime
    headline: str
    urgency: str = "normal"  # normal / high / breaking

    @property
    def urgency_score(self) -> float:
        return {"breaking": 3.0, "high": 2.0, "normal": 1.0}.get(self.urgency, 0.5)


@dataclass
class PriceBar:
    """5 分钟 K 线"""
    asset: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range_pct(self) -> float:
        return (self.high - self.low) / self.open if self.open > 0 else 0.0

    @property
    def change_pct(self) -> float:
        return (self.close - self.open) / self.open if self.open > 0 else 0.0


@dataclass
class MarketState:
    """当前市场全貌快照"""
    gold_price: float
    gold_1h_chg: float     # %
    oil_price: float
    oil_1h_chg: float      # %
    usdjpy: float
    usdjpy_1h_chg: float   # %
    dxy: float
    dxy_1h_chg: float      # %
    vix: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RegimeAssessment:
    """LLM 宏观情景研判结果"""
    regime: Regime
    confidence: float
    key_risk: str
    gold_bias: Bias
    jpy_bias: Bias
    oil_signal: str         # risk_off_spreading / supply_shock / demand_fear / neutral
    actionable_pairs: list  # [{"pair": ..., "direction": ..., "conviction": ...}]
    avoid_pairs: list       # [{"pair": ..., "reason": ...}]
    reasoning: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Position:
    """持仓"""
    asset: str
    direction: int          # +1 long, -1 short
    entry_price: float
    entry_time: datetime
    size_pct: float         # 占可用资金比例
    stop_loss: float
    take_profit: Optional[float]
    trailing_stop_pct: float = 0.0  # 0 = 不用追踪止损
    max_hold_hours: float = 6.0
    position_type: str = "event"  # "base" 底仓 / "event" 事件仓
    status: str = "open"
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""

    @property
    def pnl_pct(self) -> float:
        ref = self.exit_price or self.entry_price
        return self.direction * (ref - self.entry_price) / self.entry_price

    @property
    def hold_hours(self) -> float:
        ref = self.exit_time or datetime.now(timezone.utc)
        return (ref - self.entry_time).total_seconds() / 3600


# ══════════════════════════════════════════════════════════════════════════════
# 3. Factor 1: News Shock Intensity (NSI)
# ══════════════════════════════════════════════════════════════════════════════

class NSIEngine:
    """
    新闻冲击强度——不关心方向，只关心"有多大动静"。
    NSI = 近 30 分钟新闻数量 × 平均紧迫度。
    """

    def __init__(self, window_minutes: int = 30):
        self.window = timedelta(minutes=window_minutes)
        self._headlines: deque[NewsHeadline] = deque()
        self.threshold_high = 8.0    # NSI > 8 进入高波动模式
        self.threshold_surge = 15.0  # NSI > 15 新闻潮涌，紧急研判

    def add(self, headline: NewsHeadline) -> None:
        self._headlines.append(headline)
        self._prune()

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.window
        while self._headlines and self._headlines[0].timestamp < cutoff:
            self._headlines.popleft()

    def compute(self) -> float:
        self._prune()
        if not self._headlines:
            return 0.0
        total_urgency = sum(h.urgency_score for h in self._headlines)
        return total_urgency

    @property
    def is_high(self) -> bool:
        return self.compute() > self.threshold_high

    @property
    def is_surge(self) -> bool:
        return self.compute() > self.threshold_surge


# ══════════════════════════════════════════════════════════════════════════════
# 4. Factor 2: Cross-Asset Lead-Lag
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LeadLagSignal:
    """跨资产领先-滞后信号"""
    leader: str
    leader_move_pct: float
    predicted_asset: str
    predicted_direction: int     # +1 / -1
    signal_type: str             # supply_shock / demand_fear / risk_off / carry_unwind
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# 领先-滞后规则表
LEAD_LAG_RULES = [
    # (leader, threshold_pct, sign, predicted_asset, predicted_dir, signal_type)
    ("BRENT",   +1.5, "XAU/USD",  +1, "supply_shock"),
    ("BRENT",   +1.5, "USD/CAD",  -1, "supply_shock"),     # CAD 升值 = USD/CAD 跌
    ("BRENT",   -1.5, "AUD/USD",  -1, "demand_fear"),
    ("BRENT",   -1.5, "USD/CAD",  +1, "demand_fear"),
    ("XAU/USD", +0.8, "USD/JPY",  -1, "risk_off"),
    ("XAU/USD", +0.8, "USD/CHF",  -1, "risk_off"),
    ("USD/JPY", -0.5, "AUD/USD",  -1, "carry_unwind"),
    ("USD/JPY", -0.5, "XAU/USD",  +1, "carry_unwind"),
]


class LeadLagEngine:
    """
    检测领先资产异动，生成滞后资产交易信号。
    """

    def __init__(self):
        self._recent_bars: dict[str, deque[PriceBar]] = {}  # asset → recent bars
        self._cooldown: dict[str, datetime] = {}             # 避免重复触发

    def update_bar(self, bar: PriceBar) -> None:
        if bar.asset not in self._recent_bars:
            self._recent_bars[bar.asset] = deque(maxlen=12)  # 保留 12 根 5min K 线
        self._recent_bars[bar.asset].append(bar)

    def _get_5min_change(self, asset: str) -> Optional[float]:
        bars = self._recent_bars.get(asset, deque())
        if len(bars) < 2:
            return None
        return (bars[-1].close - bars[-2].close) / bars[-2].close * 100

    def scan(self) -> list[LeadLagSignal]:
        """扫描所有规则，返回触发的信号"""
        now = datetime.now(timezone.utc)
        signals = []

        for leader, threshold, target, direction, sig_type in LEAD_LAG_RULES:
            move = self._get_5min_change(leader)
            if move is None:
                continue

            triggered = (threshold > 0 and move >= threshold) or \
                        (threshold < 0 and move <= threshold)
            if not triggered:
                continue

            # 冷却检查：同一规则 10 分钟内不重复触发
            key = f"{leader}_{target}_{sig_type}"
            if key in self._cooldown and (now - self._cooldown[key]).seconds < 600:
                continue

            self._cooldown[key] = now
            signals.append(LeadLagSignal(
                leader=leader,
                leader_move_pct=move,
                predicted_asset=target,
                predicted_direction=direction,
                signal_type=sig_type,
            ))
            log.info("Lead-Lag 信号：%s %.2f%% → %s %s [%s]",
                     leader, move, target,
                     "多" if direction > 0 else "空", sig_type)

        return signals


# ══════════════════════════════════════════════════════════════════════════════
# 5. Factor 3: Macro Regime State Machine (LLM-driven)
# ══════════════════════════════════════════════════════════════════════════════

REGIME_PROMPT = """你是一位商业银行资金营运中心的高级宏观策略师。

以下是最近 1 小时的路透社新闻标题（按时间倒序）：
{headlines}

当前市场行情：
  XAU/USD: {gold_price} (1h chg: {gold_chg:+.2f}%)
  Brent: {oil_price} (1h chg: {oil_chg:+.2f}%)
  USD/JPY: {usdjpy} (1h chg: {usdjpy_chg:+.2f}%)
  DXY: {dxy} (1h chg: {dxy_chg:+.2f}%)
  VIX: {vix}

请以 JSON 格式回答（不要 markdown 代码块）：

1. regime: A=地缘紧张升级 / B=恐慌消化 / C=地缘缓和 / D=宏观数据驱动
2. regime_confidence: 0.0-1.0
3. key_risk: 未来4小时最大单一风险事件（一句话）
4. gold_bias: strong_bull / bull / neutral / bear / strong_bear
5. jpy_bias: strong_bull / bull / neutral / bear / strong_bear（JPY走强=bull）
6. oil_signal: risk_off_spreading / supply_shock / demand_fear / neutral
7. actionable_pairs: [{{"pair":"XAU/USD","direction":"long","conviction":0.85}}, ...]
8. avoid_pairs: [{{"pair":"...","reason":"..."}}]
9. reasoning: 50字以内核心逻辑"""


class RegimeEngine:
    """
    LLM 驱动的宏观情景状态机。
    每 15 分钟调用一次（NSI 飙升时紧急调用）。
    """

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.current_regime = Regime.DATA_DRIVEN
        self.current_assessment: Optional[RegimeAssessment] = None
        self._last_call: Optional[datetime] = None

    def assess(self, headlines: list[NewsHeadline],
               market: MarketState) -> RegimeAssessment:
        """调用 LLM 做宏观情景研判"""
        headlines_text = "\n".join(
            f"[{h.urgency.upper()}] {h.headline}" for h in headlines[-30:]
        )

        prompt = REGIME_PROMPT.format(
            headlines=headlines_text,
            gold_price=market.gold_price, gold_chg=market.gold_1h_chg,
            oil_price=market.oil_price, oil_chg=market.oil_1h_chg,
            usdjpy=market.usdjpy, usdjpy_chg=market.usdjpy_1h_chg,
            dxy=market.dxy, dxy_chg=market.dxy_1h_chg,
            vix=market.vix,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
        except Exception as e:
            log.error("LLM 情景研判失败: %s", e)
            return self._fallback_assessment(market)

        regime_map = {"A": Regime.ESCALATION, "B": Regime.DIGESTION,
                      "C": Regime.DEESCALATION, "D": Regime.DATA_DRIVEN}

        assessment = RegimeAssessment(
            regime=regime_map.get(data.get("regime", "D"), Regime.DATA_DRIVEN),
            confidence=float(data.get("regime_confidence", 0.5)),
            key_risk=data.get("key_risk", "unknown"),
            gold_bias=Bias(data.get("gold_bias", "neutral")),
            jpy_bias=Bias(data.get("jpy_bias", "neutral")),
            oil_signal=data.get("oil_signal", "neutral"),
            actionable_pairs=data.get("actionable_pairs", []),
            avoid_pairs=data.get("avoid_pairs", []),
            reasoning=data.get("reasoning", ""),
        )

        self.current_regime = assessment.regime
        self.current_assessment = assessment
        self._last_call = datetime.now(timezone.utc)

        log.info("情景研判：Regime=%s (%.0f%%) | 黄金=%s | 日元=%s | %s",
                 assessment.regime.value, assessment.confidence * 100,
                 assessment.gold_bias.value, assessment.jpy_bias.value,
                 assessment.reasoning)

        return assessment

    def _fallback_assessment(self, market: MarketState) -> RegimeAssessment:
        """LLM 调用失败时的规则回退"""
        if market.vix > 30:
            regime = Regime.ESCALATION
        elif abs(market.gold_1h_chg) < 0.2 and abs(market.oil_1h_chg) < 0.5:
            regime = Regime.DATA_DRIVEN
        else:
            regime = Regime.DIGESTION

        return RegimeAssessment(
            regime=regime, confidence=0.4,
            key_risk="LLM unavailable, rule-based fallback",
            gold_bias=Bias.NEUTRAL, jpy_bias=Bias.NEUTRAL,
            oil_signal="neutral",
            actionable_pairs=[], avoid_pairs=[],
            reasoning="Fallback: LLM call failed",
        )

    @property
    def needs_refresh(self) -> bool:
        if self._last_call is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_call).seconds
        return elapsed > 900  # 15 分钟


# ══════════════════════════════════════════════════════════════════════════════
# 6. Factor 4: BoJ Signal Tracker
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BoJSignal:
    """日本央行相关信号"""
    timestamp: datetime
    source: str             # statement / official_speech / data / market_implied
    direction: int          # +1 鹰派, -1 鸽派
    description: str

    @property
    def weight(self) -> float:
        return {"statement": 5.0, "official_speech": 3.0,
                "data": 2.0, "market_implied": 1.0}.get(self.source, 1.0)


class BoJTracker:
    """
    追踪 BoJ 政策信号，维护累计 BoJ_Score。
    BoJ_Score > +3 → 做空 USD/JPY 信号
    BoJ_Score < -2 → 暂停 USD/JPY 空头
    """

    ENTRY_THRESHOLD = 3.0
    PAUSE_THRESHOLD = -2.0

    def __init__(self):
        self._signals: list[BoJSignal] = []

    def add_signal(self, signal: BoJSignal) -> None:
        self._signals.append(signal)
        log.info("BoJ 信号：%s [%s] dir=%+d | 当前 Score=%.1f",
                 signal.description, signal.source,
                 signal.direction, self.score)

    @property
    def score(self) -> float:
        now = datetime.now(timezone.utc)
        total = 0.0
        for s in self._signals:
            hours_ago = (now - s.timestamp).total_seconds() / 3600
            if hours_ago < 24:
                decay = 1.0
            elif hours_ago < 72:
                decay = 0.6
            elif hours_ago < 168:
                decay = 0.3
            else:
                decay = 0.1
            total += s.direction * s.weight * decay
        return total

    @property
    def should_short_usdjpy(self) -> bool:
        return self.score > self.ENTRY_THRESHOLD

    @property
    def should_pause_usdjpy(self) -> bool:
        return self.score < self.PAUSE_THRESHOLD


# ══════════════════════════════════════════════════════════════════════════════
# 7. 风险管理器
# ══════════════════════════════════════════════════════════════════════════════

class RiskBudgetManager:
    """
    情景加权风险预算管理。
    不同于 03_ 的 Kelly 方法——按宏观状态分配风险预算。
    """

    def __init__(self, nav: float, daily_risk_pct: float = 0.02):
        self.nav = nav                     # 账户净值
        self.daily_budget = nav * daily_risk_pct
        self.used_budget = 0.0
        self.daily_pnl = 0.0
        self.positions: dict[str, Position] = {}
        self.closed: list[Position] = []
        self.consecutive_losses = 0
        self.halted = False

    @property
    def available_budget(self) -> float:
        return max(0, self.daily_budget - self.used_budget)

    def budget_for_regime(self, regime: Regime) -> float:
        ratio = REGIME_RISK_BUDGET[regime]
        # 连续亏损减半
        if self.consecutive_losses >= 3:
            ratio *= 0.5
        return self.available_budget * ratio

    def calc_position_size(self, entry: float, stop: float,
                           regime: Regime, asset: str) -> float:
        """
        根据风险预算计算仓位。
        返回仓位占比（0-1）。
        """
        risk_per_unit = abs(entry - stop) / entry  # 单位风险百分比
        if risk_per_unit < 1e-6:
            return 0.0
        budget = self.budget_for_regime(regime)
        max_risk_amount = budget * 0.30  # 单笔不超过预算 30%
        position_value = max_risk_amount / risk_per_unit
        size_pct = min(position_value / self.nav, 0.30)  # 上限 30%
        return round(size_pct, 3)

    def open_position(self, pos: Position) -> bool:
        if self.halted:
            log.warning("策略已暂停，拒绝开仓 %s", pos.asset)
            return False
        if pos.asset in self.positions:
            existing = self.positions[pos.asset]
            if existing.position_type == "base" and pos.position_type == "event":
                pass  # 允许底仓+事件仓共存——合并管理
            elif existing.direction == pos.direction:
                log.info("已有同向仓位 %s，跳过", pos.asset)
                return False

        # 总敞口检查
        total = sum(p.size_pct for p in self.positions.values())
        if total + pos.size_pct > 0.80:
            log.warning("总敞口将超过 80%%，拒绝开仓 %s", pos.asset)
            return False

        self.positions[pos.asset] = pos
        self.used_budget += pos.size_pct * self.nav * abs(pos.entry_price - pos.stop_loss) / pos.entry_price
        log.info("开仓 %s %s %.5f | 仓位=%.1f%% | 止损=%.5f",
                 "多" if pos.direction > 0 else "空",
                 pos.asset, pos.entry_price, pos.size_pct * 100, pos.stop_loss)
        return True

    def check_exits(self, prices: dict[str, float]) -> list[Position]:
        """检查止损/止盈/时间止损/追踪止损"""
        to_close = []
        now = datetime.now(timezone.utc)

        for asset, pos in list(self.positions.items()):
            price = prices.get(asset)
            if price is None:
                continue

            reason = ""

            # 止盈
            if pos.take_profit:
                if pos.direction > 0 and price >= pos.take_profit:
                    reason = "止盈"
                elif pos.direction < 0 and price <= pos.take_profit:
                    reason = "止盈"

            # 止损
            if not reason:
                if pos.direction > 0 and price <= pos.stop_loss:
                    reason = "止损"
                elif pos.direction < 0 and price >= pos.stop_loss:
                    reason = "止损"

            # 追踪止损
            if not reason and pos.trailing_stop_pct > 0:
                if pos.direction > 0:
                    trail_price = price * (1 - pos.trailing_stop_pct)
                    if trail_price > pos.stop_loss:
                        pos.stop_loss = trail_price  # 抬高止损
                else:
                    trail_price = price * (1 + pos.trailing_stop_pct)
                    if trail_price < pos.stop_loss:
                        pos.stop_loss = trail_price

            # 时间止损（底仓豁免）
            if not reason and pos.position_type != "base":
                if pos.hold_hours >= pos.max_hold_hours:
                    reason = f"时间止损({pos.hold_hours:.1f}h)"

            if reason:
                pos.exit_price = price
                pos.exit_time = now
                pos.exit_reason = reason
                pos.status = "closed"
                pnl = pos.pnl_pct * pos.size_pct
                self.daily_pnl += pnl
                to_close.append(pos)
                del self.positions[asset]
                self.closed.append(pos)

                if pnl < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0

                log.info("平仓 %s [%s] 盈亏=%.2f%%", asset, reason, pos.pnl_pct * 100)

        # 日亏损熔断
        if self.daily_pnl < -0.02:
            self.halted = True
            log.warning("日亏损熔断！daily_pnl=%.2f%%", self.daily_pnl * 100)

        return to_close

    def reduce_all(self, factor: float = 0.5) -> None:
        """全部仓位按比例缩减（状态 B 消化期使用）"""
        for pos in self.positions.values():
            pos.size_pct *= factor
        log.info("全部仓位缩减至 %.0f%%", factor * 100)

    def get_summary(self) -> dict:
        open_pos = len(self.positions)
        closed_count = len(self.closed)
        wins = sum(1 for p in self.closed if p.pnl_pct > 0)
        return {
            "open_positions": open_pos,
            "closed_trades": closed_count,
            "win_rate": round(wins / closed_count, 3) if closed_count > 0 else 0.0,
            "daily_pnl": f"{self.daily_pnl * 100:.2f}%",
            "consecutive_losses": self.consecutive_losses,
            "halted": self.halted,
            "available_budget": f"{self.available_budget:,.0f}",
        }


# ══════════════════════════════════════════════════════════════════════════════
# 8. 主策略协调器
# ══════════════════════════════════════════════════════════════════════════════

class MacroRegimeStrategy:
    """
    宏观情景驱动多因子策略主协调器。

    四因子融合：
    1. NSI（新闻冲击强度）→ 控制波动率模式
    2. Lead-Lag（跨资产领先-滞后）→ 快速捕捉传导链
    3. Regime（宏观情景状态机）→ 决定总体方向和仓位预算
    4. BoJ Tracker → USD/JPY 专项信号
    """

    def __init__(self, api_key: str, nav: float = 1e8):
        self.nsi = NSIEngine()
        self.lead_lag = LeadLagEngine()
        self.regime_engine = RegimeEngine(api_key=api_key)
        self.boj = BoJTracker()
        self.risk = RiskBudgetManager(nav=nav)
        self._news_buffer: deque[NewsHeadline] = deque(maxlen=200)
        self._prices: dict[str, float] = {}

    # ── 事件入口 ──

    def on_news(self, headline: NewsHeadline) -> None:
        """接收新闻"""
        self._news_buffer.append(headline)
        self.nsi.add(headline)

        # BoJ 相关新闻自动分类
        lower = headline.headline.lower()
        if any(kw in lower for kw in ["boj", "bank of japan", "ueda", "japan cpi",
                                       "japan wage", "jgb yield"]):
            direction = +1 if any(kw in lower for kw in ["hike", "hawk", "above",
                                                          "inflation rise", "wage growth"]) else -1
            self.boj.add_signal(BoJSignal(
                timestamp=headline.timestamp,
                source="data" if "cpi" in lower or "wage" in lower else "official_speech",
                direction=direction,
                description=headline.headline[:80],
            ))

        # NSI 飙升 → 紧急情景研判
        if self.nsi.is_surge:
            log.info("NSI 飙升 (%.1f)，触发紧急情景研判", self.nsi.compute())
            self._run_regime_assessment()

    def on_bar(self, bar: PriceBar) -> None:
        """接收 5 分钟 K 线"""
        self.lead_lag.update_bar(bar)
        self._prices[bar.asset] = bar.close

        # Lead-Lag 信号检测
        signals = self.lead_lag.scan()
        for sig in signals:
            self._execute_lead_lag(sig)

    def on_tick(self, prices: dict[str, float]) -> list[Position]:
        """接收实时行情，检查止损止盈"""
        self._prices.update(prices)
        return self.risk.check_exits(prices)

    def periodic_update(self, market: MarketState) -> Optional[RegimeAssessment]:
        """定期调用（每 15 分钟），执行情景研判和状态转换"""
        if not self.regime_engine.needs_refresh and not self.nsi.is_surge:
            return None

        assessment = self.regime_engine.assess(
            list(self._news_buffer)[-30:], market)

        self._handle_regime_transition(assessment)
        return assessment

    # ── 内部逻辑 ──

    def _run_regime_assessment(self) -> None:
        """紧急情景研判（当 NSI 飙升时）"""
        # 构造一个简易 MarketState
        market = MarketState(
            gold_price=self._prices.get("XAU/USD", 3200),
            gold_1h_chg=0.0,
            oil_price=self._prices.get("BRENT", 85),
            oil_1h_chg=0.0,
            usdjpy=self._prices.get("USD/JPY", 145),
            usdjpy_1h_chg=0.0,
            dxy=self._prices.get("DXY", 103),
            dxy_1h_chg=0.0,
            vix=self._prices.get("VIX", 22),
        )
        assessment = self.regime_engine.assess(list(self._news_buffer)[-30:], market)
        self._handle_regime_transition(assessment)

    def _handle_regime_transition(self, assessment: RegimeAssessment) -> None:
        """根据情景研判结果调整仓位"""
        regime = assessment.regime

        if regime == Regime.ESCALATION and assessment.confidence >= 0.7:
            self._execute_escalation(assessment)
        elif regime == Regime.DIGESTION:
            self._execute_digestion()
        elif regime == Regime.DEESCALATION and assessment.confidence >= 0.65:
            self._execute_deescalation(assessment)
        elif regime == Regime.DATA_DRIVEN:
            self._execute_data_driven(assessment)

    def _execute_escalation(self, assessment: RegimeAssessment) -> None:
        """状态 A：地缘紧张升级——做多黄金、做空风险货币"""
        log.info("执行 Escalation 剧本")
        gold = self._prices.get("XAU/USD")
        if gold:
            atr_est = gold * 0.005  # 约 0.5% 作为 ATR 估算
            self.risk.open_position(Position(
                asset="XAU/USD", direction=+1,
                entry_price=gold, entry_time=datetime.now(timezone.utc),
                size_pct=0.30, stop_loss=gold - atr_est * 2,
                take_profit=None, trailing_stop_pct=0.008,
                max_hold_hours=6, position_type="event",
            ))

        usdjpy = self._prices.get("USD/JPY")
        if usdjpy:
            atr_est = usdjpy * 0.003
            self.risk.open_position(Position(
                asset="USD/JPY", direction=-1,
                entry_price=usdjpy, entry_time=datetime.now(timezone.utc),
                size_pct=0.25, stop_loss=usdjpy + atr_est * 2,
                take_profit=usdjpy - atr_est * 3,
                max_hold_hours=6, position_type="event",
            ))

        usdchf = self._prices.get("USD/CHF")
        if usdchf:
            atr_est = usdchf * 0.003
            self.risk.open_position(Position(
                asset="USD/CHF", direction=-1,
                entry_price=usdchf, entry_time=datetime.now(timezone.utc),
                size_pct=0.15, stop_loss=usdchf + atr_est * 1.5,
                take_profit=usdchf - atr_est * 2.5,
                max_hold_hours=6, position_type="event",
            ))

    def _execute_digestion(self) -> None:
        """状态 B：恐慌消化——减仓并等待"""
        log.info("执行 Digestion 剧本：全部仓位减半")
        self.risk.reduce_all(0.5)

    def _execute_deescalation(self, assessment: RegimeAssessment) -> None:
        """状态 C：地缘缓和——平事件仓、反转交易"""
        log.info("执行 De-escalation 剧本")
        # 平掉事件仓（保留底仓）
        for asset, pos in list(self.risk.positions.items()):
            if pos.position_type == "event" and asset in ("XAU/USD", "USD/CHF"):
                price = self._prices.get(asset, pos.entry_price)
                pos.exit_price = price
                pos.exit_time = datetime.now(timezone.utc)
                pos.exit_reason = "状态C平仓"
                pos.status = "closed"
                self.risk.closed.append(pos)
                del self.risk.positions[asset]
                log.info("缓和平仓：%s", asset)

        # 反转交易：做多 EUR/USD
        eurusd = self._prices.get("EUR/USD")
        if eurusd:
            atr_est = eurusd * 0.002
            self.risk.open_position(Position(
                asset="EUR/USD", direction=+1,
                entry_price=eurusd, entry_time=datetime.now(timezone.utc),
                size_pct=0.15, stop_loss=eurusd - atr_est * 1.0,
                take_profit=eurusd + atr_est * 2.0,
                max_hold_hours=3, position_type="event",
            ))

    def _execute_data_driven(self, assessment: RegimeAssessment) -> None:
        """状态 D：数据驱动——按 LLM 推荐执行"""
        log.info("执行 Data-Driven 剧本")
        for rec in assessment.actionable_pairs[:3]:
            pair = rec.get("pair", "")
            direction = 1 if rec.get("direction") == "long" else -1
            conviction = float(rec.get("conviction", 0.5))
            if pair not in ASSETS or conviction < 0.6:
                continue
            price = self._prices.get(pair)
            if price is None:
                continue
            atr_est = price * 0.002
            self.risk.open_position(Position(
                asset=pair, direction=direction,
                entry_price=price, entry_time=datetime.now(timezone.utc),
                size_pct=min(conviction * 0.15, 0.15),
                stop_loss=price - direction * atr_est * 1.0,
                take_profit=price + direction * atr_est * 2.0,
                max_hold_hours=2, position_type="event",
            ))

    def _execute_lead_lag(self, sig: LeadLagSignal) -> None:
        """执行 Lead-Lag 信号"""
        price = self._prices.get(sig.predicted_asset)
        if price is None:
            return
        atr_est = price * 0.002
        self.risk.open_position(Position(
            asset=sig.predicted_asset, direction=sig.predicted_direction,
            entry_price=price, entry_time=datetime.now(timezone.utc),
            size_pct=0.10,
            stop_loss=price - sig.predicted_direction * atr_est * 1.5,
            take_profit=price + sig.predicted_direction * atr_est * 2.5,
            max_hold_hours=2, position_type="event",
        ))

    # ── 状态查询 ──

    def get_status(self) -> dict:
        return {
            "regime": self.regime_engine.current_regime.value,
            "nsi": round(self.nsi.compute(), 1),
            "nsi_mode": "SURGE" if self.nsi.is_surge else ("HIGH" if self.nsi.is_high else "NORMAL"),
            "boj_score": round(self.boj.score, 1),
            "boj_signal": "SHORT_USDJPY" if self.boj.should_short_usdjpy else (
                "PAUSE_USDJPY" if self.boj.should_pause_usdjpy else "HOLD"),
            "risk": self.risk.get_summary(),
            "positions": {
                asset: {
                    "dir": "多" if p.direction > 0 else "空",
                    "entry": p.entry_price,
                    "size": f"{p.size_pct:.1%}",
                    "type": p.position_type,
                    "hold_h": round(p.hold_hours, 1),
                }
                for asset, p in self.risk.positions.items()
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# 9. 离线演示
# ══════════════════════════════════════════════════════════════════════════════

def demo():
    """
    离线演示：模拟一个地缘政治升级事件的完整处理流程。
    不需要 API Key（跳过 LLM 调用，使用 fallback 逻辑）。
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "demo_key")
    strategy = MacroRegimeStrategy(api_key=api_key, nav=1e8)

    # 模拟当前价格
    strategy._prices = {
        "XAU/USD": 3195.0, "XAG/USD": 40.20,
        "EUR/USD": 1.0985, "GBP/USD": 1.2840,
        "USD/JPY": 144.50, "USD/CAD": 1.3860,
        "USD/CHF": 0.8810, "AUD/USD": 0.6345,
        "BRENT": 84.50, "DXY": 103.2, "VIX": 22.5,
    }

    print("=" * 60)
    print("宏观情景驱动多因子策略 — 离线演示")
    print("=" * 60)

    # 模拟新闻流
    now = datetime.now(timezone.utc)
    news_flow = [
        ("BREAKING: Iran fires ballistic missiles at US naval base in Bahrain",
         "breaking"),
        ("Pentagon confirms Iranian missile attack, assessing damage",
         "breaking"),
        ("Oil surges 6% on Iran attack; Brent hits $90",
         "high"),
        ("Gold jumps $80 to $3,275 as safe-haven demand surges",
         "high"),
        ("Japan PM Ishiba calls emergency security council meeting",
         "high"),
        ("Bank of Japan signals potential rate hike delay amid geopolitical crisis",
         "normal"),
    ]

    print("\n[模拟新闻流]")
    for i, (headline, urgency) in enumerate(news_flow):
        news = NewsHeadline(
            news_id=f"RTR-{i:03d}",
            timestamp=now - timedelta(minutes=30 - i * 5),
            headline=headline,
            urgency=urgency,
        )
        strategy.on_news(news)
        print(f"  [{urgency.upper():8s}] {headline}")

    print(f"\n[NSI] 当前值 = {strategy.nsi.compute():.1f}")
    print(f"[BoJ] Score = {strategy.boj.score:.1f}")

    # 模拟 5min K 线——原油急涨
    bar = PriceBar("BRENT", now, 84.5, 90.2, 84.3, 89.8)
    strategy.lead_lag.update_bar(PriceBar("BRENT", now - timedelta(minutes=5),
                                          82.0, 84.6, 81.8, 84.5))
    strategy.lead_lag.update_bar(bar)
    print(f"\n[Lead-Lag] Brent 5min K: {84.5} → {89.8} (+{(89.8/84.5-1)*100:.1f}%)")
    signals = strategy.lead_lag.scan()
    for sig in signals:
        print(f"  → {sig.leader} {sig.leader_move_pct:+.1f}% → "
              f"{'多' if sig.predicted_direction > 0 else '空'} {sig.predicted_asset} [{sig.signal_type}]")

    # 模拟情景研判（使用 fallback）
    market = MarketState(
        gold_price=3275, gold_1h_chg=2.5,
        oil_price=89.8, oil_1h_chg=6.3,
        usdjpy=143.2, usdjpy_1h_chg=-0.9,
        dxy=103.8, dxy_1h_chg=0.3, vix=32.5,
    )

    print(f"\n[Regime] VIX={market.vix} → Fallback 判断为 Escalation")
    assessment = strategy.regime_engine._fallback_assessment(market)
    strategy.regime_engine.current_regime = assessment.regime
    strategy._handle_regime_transition(assessment)

    # 打印状态
    status = strategy.get_status()
    print(f"\n[策略状态]")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    demo()
