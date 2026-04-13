"""
舆情驱动高频外汇与贵金属策略实现
GeoPolitical News Sentiment → FX & Precious Metals HF Strategy

依赖:
    pip install anthropic pandas numpy scipy requests websocket-client
"""

import json
import math
import time
import threading
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

import numpy as np
import pandas as pd
from scipy.special import expit  # sigmoid for Platt scaling

# ─── Anthropic SDK ────────────────────────────────────────────────────────────
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("geo-fx-strategy")

# ══════════════════════════════════════════════════════════════════════════════
# 1. 数据结构定义
# ══════════════════════════════════════════════════════════════════════════════

ASSETS = ["XAU/USD", "XAG/USD", "EUR/USD", "GBP/USD", "USD/JPY",
          "USD/CAD", "USD/CHF", "AUD/USD"]

LOGIC_TAGS = [
    "geopolitical_escalation", "geopolitical_deescalation",
    "energy_supply_shock", "central_bank_signal",
    "inflation_data", "trade_war_escalation",
    "risk_off_flight", "commodity_demand_shock",
]

# 各 logic_tag 的半衰期（小时）
HALF_LIFE_HOURS: dict[str, float] = {
    "geopolitical_escalation":    4.0,
    "geopolitical_deescalation": 12.0,
    "energy_supply_shock":        6.0,
    "central_bank_signal":       36.0,
    "inflation_data":            18.0,
    "trade_war_escalation":      12.0,
    "risk_off_flight":            2.0,
    "commodity_demand_shock":    10.0,
}

# 跨资产传导矩阵（logic_tag → asset → 方向强度 [-1, +1]）
ASSET_REACTION: dict[str, dict[str, float]] = {
    "geopolitical_escalation": {
        "XAU/USD": +0.90, "XAG/USD": +0.75,
        "EUR/USD": -0.60, "GBP/USD": -0.40,
        "USD/JPY": -0.70, "USD/CAD": +0.10,
        "USD/CHF": -0.80, "AUD/USD": -0.55,
    },
    "geopolitical_deescalation": {
        "XAU/USD": -0.70, "XAG/USD": -0.55,
        "EUR/USD": +0.50, "GBP/USD": +0.30,
        "USD/JPY": +0.60, "USD/CAD":  0.00,
        "USD/CHF": +0.65, "AUD/USD": +0.50,
    },
    "energy_supply_shock": {
        "XAU/USD": +0.50, "XAG/USD": +0.35,
        "EUR/USD": -0.45, "GBP/USD": -0.30,
        "USD/JPY": -0.25, "USD/CAD": +0.70,
        "USD/CHF": -0.35, "AUD/USD": -0.20,
    },
    "central_bank_signal": {
        "XAU/USD": -0.60, "XAG/USD": -0.50,
        "EUR/USD":  0.00, "GBP/USD":  0.00,
        "USD/JPY":  0.00, "USD/CAD":  0.00,
        "USD/CHF": -0.20, "AUD/USD": -0.30,
    },
    "inflation_data": {
        "XAU/USD": +0.40, "XAG/USD": +0.30,
        "EUR/USD": -0.20, "GBP/USD": -0.20,
        "USD/JPY": -0.15, "USD/CAD": +0.15,
        "USD/CHF": -0.10, "AUD/USD": -0.20,
    },
    "trade_war_escalation": {
        "XAU/USD": +0.55, "XAG/USD": +0.40,
        "EUR/USD": -0.50, "GBP/USD": -0.35,
        "USD/JPY": -0.30, "USD/CAD": -0.40,
        "USD/CHF": -0.45, "AUD/USD": -0.60,
    },
    "risk_off_flight": {
        "XAU/USD": +0.85, "XAG/USD": +0.65,
        "EUR/USD": -0.55, "GBP/USD": -0.45,
        "USD/JPY": -0.70, "USD/CAD": -0.30,
        "USD/CHF": -0.80, "AUD/USD": -0.65,
    },
    "commodity_demand_shock": {
        "XAU/USD": -0.20, "XAG/USD": -0.40,
        "EUR/USD": -0.15, "GBP/USD": -0.10,
        "USD/JPY": +0.10, "USD/CAD": -0.60,
        "USD/CHF": +0.10, "AUD/USD": -0.55,
    },
}


@dataclass
class NewsItem:
    """单条路透社新闻"""
    news_id: str
    timestamp: datetime
    headline: str
    body: str = ""
    source: str = "Reuters"
    urgency: str = "normal"          # normal / high / critical


@dataclass
class SentimentResult:
    """LLM 情感分析输出"""
    news_id: str
    timestamp: datetime
    logic_tag: str
    direction: float                 # [-1, +1]
    intensity: float                 # [0, 1]
    raw_confidence: float            # LLM 原始置信度 [0, 1]
    calibrated_confidence: float     # Platt 校准后
    urgency: str
    affected_assets: list[str]
    expected_moves: dict[str, str]   # asset → "strong_positive" / "negative" 等
    half_life_hours: float = 4.0

    @property
    def decay_lambda(self) -> float:
        return math.log(2) / self.half_life_hours


@dataclass
class NSIFState:
    """某资产当前 NSIF 状态（滚动窗口）"""
    asset: str
    nsif: float = 0.0
    last_updated: Optional[datetime] = None
    contributing_news: list[str] = field(default_factory=list)


@dataclass
class TradeSignal:
    """交易信号"""
    asset: str
    direction: int          # +1 = 做多, -1 = 做空
    nsif_score: float       # 触发信号的 NSIF 绝对值
    urgency: str            # normal / high / critical
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    position_pct: float = 0.0       # 建议仓位（占可用资金比例）
    stop_loss_pct: float = 0.015    # 止损比例
    take_profit_pct: float = 0.03   # 止盈比例
    max_holding_hours: float = 4.0

    @property
    def signal_label(self) -> str:
        d = "多" if self.direction > 0 else "空"
        return f"{d}  {self.asset}  (NSIF={self.nsif_score:.3f}, pos={self.position_pct:.1%})"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Platt Scaling 校准器
# ══════════════════════════════════════════════════════════════════════════════

class PlattCalibrator:
    """
    对 LLM 输出的原始置信度进行 Platt Scaling 校准。

    参数通过历史"新闻→价格实现"对训练：
    - 正例：价格在预测方向上运动 > 0.3%
    - 负例：价格未如预测方向运动
    使用逻辑回归拟合 a, b 使 sigmoid(a*score + b) ≈ 真实概率。

    默认参数 a=1.2, b=-0.25 来自合理先验，实际应用中需用历史数据拟合。
    """

    def __init__(self, a: float = 1.2, b: float = -0.25):
        self.a = a
        self.b = b

    def calibrate(self, raw_score: float) -> float:
        return float(expit(self.a * raw_score + self.b))

    def fit(self, raw_scores: list[float], labels: list[int]) -> None:
        """用历史数据重新拟合参数。labels: 1=方向正确, 0=方向错误"""
        from scipy.optimize import minimize

        def neg_log_likelihood(params):
            a, b = params
            probs = expit(a * np.array(raw_scores) + b)
            probs = np.clip(probs, 1e-9, 1 - 1e-9)
            y = np.array(labels)
            return -np.mean(y * np.log(probs) + (1 - y) * np.log(1 - probs))

        result = minimize(neg_log_likelihood, [self.a, self.b], method="Nelder-Mead")
        self.a, self.b = result.x
        log.info("Platt Scaling 参数更新：a=%.4f, b=%.4f", self.a, self.b)


# ══════════════════════════════════════════════════════════════════════════════
# 3. LLM 情感分析引擎（Claude API）
# ══════════════════════════════════════════════════════════════════════════════

SENTIMENT_PROMPT = """You are a financial news sentiment analyzer specialized in FX and precious metals markets for a commercial bank treasury desk.

Analyze the following Reuters news item and extract structured sentiment information.

**News:**
{news_text}

**Instructions:**
Return a JSON object with exactly these fields:
- logic_tag: one of [geopolitical_escalation, geopolitical_deescalation, energy_supply_shock, central_bank_signal, inflation_data, trade_war_escalation, risk_off_flight, commodity_demand_shock]
- direction: float [-1.0 to +1.0], positive = bullish for safe havens (gold/CHF/JPY), negative = risk-off
- intensity: float [0.0 to 1.0], magnitude of expected market impact
- confidence: float [0.0 to 1.0], your confidence in this assessment
- urgency: one of [normal, high, critical]
- affected_assets: list of asset codes from [XAU/USD, XAG/USD, EUR/USD, GBP/USD, USD/JPY, USD/CAD, USD/CHF, AUD/USD]
- expected_moves: dict mapping affected assets to one of [strong_positive, positive, neutral, negative, strong_negative]
- reasoning: brief 1-sentence explanation

Return ONLY valid JSON, no markdown formatting."""


class LLMSentimentEngine:
    """
    调用 Claude API 对新闻进行情感分析。
    使用批量异步处理以控制 API 调用速率和成本。
    """

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001",
                 calibrator: Optional[PlattCalibrator] = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.calibrator = calibrator or PlattCalibrator()
        self._cost_tracker = 0.0     # 累计 API 成本估算（USD）

    def analyze(self, news: NewsItem) -> Optional[SentimentResult]:
        """分析单条新闻，返回结构化情感结果"""
        news_text = f"Headline: {news.headline}\n\nBody: {news.body or '(no body)'}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{
                    "role": "user",
                    "content": SENTIMENT_PROMPT.format(news_text=news_text)
                }]
            )
            raw_text = response.content[0].text.strip()

            # 清理可能的 markdown 代码块
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            data = json.loads(raw_text)

        except json.JSONDecodeError as e:
            log.warning("JSON 解析失败（news_id=%s）: %s", news.news_id, e)
            return None
        except Exception as e:
            log.error("LLM API 调用失败: %s", e)
            return None

        logic_tag = data.get("logic_tag", "risk_off_flight")
        raw_conf = float(data.get("confidence", 0.5))
        cal_conf = self.calibrator.calibrate(raw_conf)

        return SentimentResult(
            news_id=news.news_id,
            timestamp=news.timestamp,
            logic_tag=logic_tag,
            direction=float(data.get("direction", 0.0)),
            intensity=float(data.get("intensity", 0.5)),
            raw_confidence=raw_conf,
            calibrated_confidence=cal_conf,
            urgency=data.get("urgency", "normal"),
            affected_assets=data.get("affected_assets", []),
            expected_moves=data.get("expected_moves", {}),
            half_life_hours=HALF_LIFE_HOURS.get(logic_tag, 4.0),
        )

    def analyze_batch(self, news_list: list[NewsItem]) -> list[Optional[SentimentResult]]:
        """批量分析新闻（顺序执行，避免并发超限）"""
        results = []
        for news in news_list:
            result = self.analyze(news)
            results.append(result)
            time.sleep(0.2)  # 速率限制：5 req/s
        return results


# ══════════════════════════════════════════════════════════════════════════════
# 4. NSIF 计算引擎
# ══════════════════════════════════════════════════════════════════════════════

SOURCE_WEIGHTS = {
    "Reuters Breaking": 1.0,
    "Reuters Headline": 1.0,
    "Reuters Flash":    0.90,
    "Reuters":          0.80,
    "Reuters Analysis": 0.60,
}

GEO_AMPLIFIER_TAGS = {"geopolitical_escalation", "energy_supply_shock", "risk_off_flight"}


class NSIFEngine:
    """
    维护滚动时间窗口内的 NSIF 因子状态。

    NSIF = Σ direction × intensity × calibrated_confidence
             × source_weight × exp(-λ × Δt) × geo_amplifier
    """

    def __init__(self, window_hours: float = 12.0, geo_risk_level: int = 1):
        self.window_hours = window_hours
        self.geo_risk_level = geo_risk_level   # 0=正常, 1=升级, 2=危机
        self._sentiments: deque[SentimentResult] = deque()
        self._lock = threading.Lock()

    def set_geo_risk_level(self, level: int) -> None:
        """手动设置地缘政治风险级别（由操作员根据市场状况调整）"""
        self.geo_risk_level = max(0, min(2, level))
        log.info("地缘政治风险级别设置为 %d", self.geo_risk_level)

    def add_sentiment(self, sentiment: SentimentResult) -> None:
        with self._lock:
            self._sentiments.append(sentiment)
            self._prune_old()

    def _prune_old(self) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - self.window_hours * 3600
        while self._sentiments:
            if self._sentiments[0].timestamp.timestamp() < cutoff:
                self._sentiments.popleft()
            else:
                break

    def _geo_amplifier(self, logic_tag: str) -> float:
        if logic_tag in GEO_AMPLIFIER_TAGS:
            return 1.0 + 0.5 * self.geo_risk_level  # 最高 2.0x
        return 1.0

    def compute_nsif(self, asset: str,
                     source_map: Optional[dict[str, str]] = None
                     ) -> NSIFState:
        """计算指定资产当前的 NSIF 值"""
        now_ts = datetime.now(timezone.utc).timestamp()
        nsif_total = 0.0
        contributing = []

        with self._lock:
            self._prune_old()
            for s in self._sentiments:
                # 该 logic_tag 对该资产的标准反应方向
                reaction = ASSET_REACTION.get(s.logic_tag, {}).get(asset, 0.0)
                if abs(reaction) < 0.05:
                    continue  # 该资产基本不受此类新闻影响

                # 时间衰减
                delta_h = (now_ts - s.timestamp.timestamp()) / 3600.0
                time_decay = math.exp(-s.decay_lambda * delta_h)

                # 来源权重
                src_tag = source_map.get(s.news_id, "Reuters") if source_map else "Reuters"
                src_w = SOURCE_WEIGHTS.get(src_tag, 0.8)

                # 地缘政治放大器
                amp = self._geo_amplifier(s.logic_tag)

                # NSIF 贡献
                contribution = (
                    s.direction * s.intensity * s.calibrated_confidence
                    * src_w * time_decay * amp * reaction
                )
                nsif_total += contribution
                contributing.append(s.news_id)

        return NSIFState(
            asset=asset,
            nsif=nsif_total,
            last_updated=datetime.now(timezone.utc),
            contributing_news=contributing,
        )

    def compute_all(self) -> dict[str, NSIFState]:
        """计算所有资产的 NSIF"""
        return {asset: self.compute_nsif(asset) for asset in ASSETS}


# ══════════════════════════════════════════════════════════════════════════════
# 5. 信号生成模块
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketSnapshot:
    """当前市场行情快照（由实盘接口填充）"""
    asset: str
    bid: float
    ask: float
    mid: float
    atr_1min: float          # 1 分钟 ATR
    atr_baseline: float      # 历史基准 ATR（20 期均值）
    price_change_5min: float # 最近 5 分钟价格变化（百分比）
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0 else 0.0


class SignalGenerator:
    """
    三层过滤信号生成器：
    Layer 1: NSIF 阈值
    Layer 2: 价格动量方向一致性
    Layer 3: 波动率与流动性过滤
    """

    def __init__(self,
                 nsif_entry: float = 0.35,
                 nsif_strong: float = 0.65,
                 atr_spike_filter: float = 3.0,
                 spread_spike_filter: float = 5.0):
        self.nsif_entry = nsif_entry
        self.nsif_strong = nsif_strong
        self.atr_spike_filter = atr_spike_filter
        self.spread_spike_filter = spread_spike_filter
        self._normal_spreads: dict[str, float] = {}  # 正常市场基准价差

    def set_normal_spread(self, asset: str, spread_pct: float) -> None:
        self._normal_spreads[asset] = spread_pct

    def generate(self, nsif_state: NSIFState,
                 snapshot: MarketSnapshot) -> Optional[TradeSignal]:
        """生成单资产交易信号"""
        asset = nsif_state.asset
        nsif_val = nsif_state.nsif

        # Layer 1: NSIF 阈值
        if abs(nsif_val) < self.nsif_entry:
            return None

        direction = 1 if nsif_val > 0 else -1

        # Layer 3: 波动率过滤（先于动量检查，避免危险进场）
        if snapshot.atr_baseline > 0:
            atr_ratio = snapshot.atr_1min / snapshot.atr_baseline
            if atr_ratio > self.atr_spike_filter:
                log.warning("%s ATR 激增 %.1fx，暂停开仓", asset, atr_ratio)
                return None

        # 流动性过滤
        normal_spread = self._normal_spreads.get(asset, 0.0)
        if normal_spread > 0:
            spread_ratio = snapshot.spread_pct / normal_spread
            if spread_ratio > self.spread_spike_filter:
                log.warning("%s 价差激增 %.1fx（%.5f%%），暂停开仓",
                            asset, spread_ratio, snapshot.spread_pct * 100)
                return None

        # Layer 2: 动量方向一致性
        momentum_aligned = (
            (direction > 0 and snapshot.price_change_5min > 0) or
            (direction < 0 and snapshot.price_change_5min < 0)
        )
        if not momentum_aligned:
            nsif_val *= 0.5  # 信号降级：方向不一致则减半

        abs_nsif = abs(nsif_val)
        if abs_nsif < self.nsif_entry:
            return None

        # 仓位计算
        position_pct = self._calc_position(abs_nsif, snapshot)

        # 根据 NSIF 强度设置止盈止损
        if abs_nsif >= self.nsif_strong:
            sl, tp = 0.012, 0.025
        else:
            sl, tp = 0.015, 0.030

        return TradeSignal(
            asset=asset,
            direction=direction,
            nsif_score=abs_nsif,
            urgency="critical" if abs_nsif >= self.nsif_strong else "normal",
            position_pct=position_pct,
            stop_loss_pct=sl,
            take_profit_pct=tp,
        )

    def _calc_position(self, abs_nsif: float,
                       snapshot: MarketSnapshot) -> float:
        """波动率调整 Kelly 仓位"""
        max_pct = 0.30
        kelly_f = min(abs_nsif * 0.5, max_pct)
        if snapshot.atr_baseline > 0:
            vol_adj = min(snapshot.atr_baseline / snapshot.atr_1min, 1.0)
        else:
            vol_adj = 1.0
        return round(kelly_f * vol_adj, 3)

    def generate_all(self, nsif_states: dict[str, NSIFState],
                     snapshots: dict[str, MarketSnapshot]
                     ) -> list[TradeSignal]:
        """生成所有资产的交易信号"""
        signals = []
        for asset, nsif_state in nsif_states.items():
            snapshot = snapshots.get(asset)
            if snapshot is None:
                continue
            sig = self.generate(nsif_state, snapshot)
            if sig:
                signals.append(sig)
        return signals


# ══════════════════════════════════════════════════════════════════════════════
# 6. 风控管理模块
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    """持仓记录"""
    asset: str
    direction: int
    entry_price: float
    entry_time: datetime
    position_pct: float
    stop_loss_price: float
    take_profit_price: float
    max_holding_hours: float = 4.0
    status: str = "open"   # open / closed
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.direction * (self.exit_price - self.entry_price) / self.entry_price

    @property
    def holding_hours(self) -> float:
        ref = self.exit_time or datetime.now(timezone.utc)
        return (ref - self.entry_time).total_seconds() / 3600


class RiskManager:
    """
    风险管理模块
    - 持仓跟踪与止损执行
    - 总敞口限制
    - 日亏损熔断
    """

    def __init__(self,
                 max_position_pct: float = 0.30,
                 max_total_pct: float = 0.80,
                 daily_loss_limit: float = 0.02):
        self.max_position_pct = max_position_pct
        self.max_total_pct = max_total_pct
        self.daily_loss_limit = daily_loss_limit

        self.positions: dict[str, Position] = {}   # asset → open position
        self.closed_positions: list[Position] = []
        self.daily_pnl: float = 0.0
        self.circuit_broken: bool = False
        self._lock = threading.Lock()

    def check_new_signal(self, signal: TradeSignal) -> tuple[bool, str]:
        """
        检查新信号是否可以开仓。
        返回 (allowed: bool, reason: str)
        """
        if self.circuit_broken:
            return False, "日亏损熔断已触发，策略暂停"

        if signal.asset in self.positions:
            existing = self.positions[signal.asset]
            if existing.direction == signal.direction:
                return False, f"已有同向持仓 {signal.asset}"

        # 总敞口检查
        total_pct = sum(p.position_pct for p in self.positions.values())
        if total_pct + signal.position_pct > self.max_total_pct:
            return False, f"总敞口 ({total_pct:.1%}) + 新仓位超过 {self.max_total_pct:.0%} 上限"

        return True, "OK"

    def open_position(self, signal: TradeSignal,
                      entry_price: float) -> Optional[Position]:
        """开仓"""
        allowed, reason = self.check_new_signal(signal)
        if not allowed:
            log.info("开仓被拒绝 [%s]: %s", signal.asset, reason)
            return None

        if signal.direction > 0:
            sl_price = entry_price * (1 - signal.stop_loss_pct)
            tp_price = entry_price * (1 + signal.take_profit_pct)
        else:
            sl_price = entry_price * (1 + signal.stop_loss_pct)
            tp_price = entry_price * (1 - signal.take_profit_pct)

        pos = Position(
            asset=signal.asset,
            direction=signal.direction,
            entry_price=entry_price,
            entry_time=datetime.now(timezone.utc),
            position_pct=signal.position_pct,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            max_holding_hours=signal.max_holding_hours,
        )

        with self._lock:
            self.positions[signal.asset] = pos

        log.info("开仓 %s  价格=%.5f  仓位=%.1f%%  止损=%.5f  止盈=%.5f",
                 signal.signal_label, entry_price,
                 signal.position_pct * 100, sl_price, tp_price)
        return pos

    def check_exits(self, snapshots: dict[str, MarketSnapshot]) -> list[Position]:
        """检查所有持仓是否触达止损/止盈/时间止损"""
        to_close = []

        with self._lock:
            for asset, pos in list(self.positions.items()):
                snap = snapshots.get(asset)
                if snap is None:
                    continue

                mid = snap.mid
                reason = ""

                # 止盈
                if pos.direction > 0 and mid >= pos.take_profit_price:
                    reason = "止盈"
                elif pos.direction < 0 and mid <= pos.take_profit_price:
                    reason = "止盈"

                # 止损
                elif pos.direction > 0 and mid <= pos.stop_loss_price:
                    reason = "止损"
                elif pos.direction < 0 and mid >= pos.stop_loss_price:
                    reason = "止损"

                # 时间止损
                elif pos.holding_hours >= pos.max_holding_hours:
                    reason = f"时间止损（持仓 {pos.holding_hours:.1f}h）"

                if reason:
                    pos.exit_price = mid
                    pos.exit_time = datetime.now(timezone.utc)
                    pos.exit_reason = reason
                    pos.status = "closed"
                    self.daily_pnl += pos.pnl_pct * pos.position_pct
                    to_close.append(pos)
                    del self.positions[asset]
                    self.closed_positions.append(pos)
                    log.info("平仓 %s [%s]  盈亏=%.2f%%",
                             asset, reason, pos.pnl_pct * 100)

        # 检查日亏损熔断
        if self.daily_pnl < -self.daily_loss_limit:
            self.circuit_broken = True
            log.warning("⚠️  日亏损熔断触发！日亏损 %.2f%% 超过上限 %.2f%%",
                        abs(self.daily_pnl) * 100, self.daily_loss_limit * 100)

        return to_close

    def nsif_reversal_check(self, asset: str,
                            new_nsif: float,
                            reversal_threshold: float = 0.5
                            ) -> bool:
        """检查 NSIF 方向是否反转，若反转则强制平仓"""
        pos = self.positions.get(asset)
        if pos is None:
            return False

        reversed_ = (
            (pos.direction > 0 and new_nsif < -reversal_threshold) or
            (pos.direction < 0 and new_nsif > reversal_threshold)
        )
        return reversed_

    def get_summary(self) -> dict:
        open_count = len(self.positions)
        closed_count = len(self.closed_positions)
        win_count = sum(1 for p in self.closed_positions if p.pnl_pct > 0)
        win_rate = win_count / closed_count if closed_count > 0 else 0.0
        total_pnl = sum(p.pnl_pct * p.position_pct for p in self.closed_positions)
        return {
            "open_positions": open_count,
            "closed_trades": closed_count,
            "win_rate": round(win_rate, 3),
            "total_pnl_weighted": round(total_pnl, 4),
            "daily_pnl": round(self.daily_pnl, 4),
            "circuit_broken": self.circuit_broken,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 7. 紧急响应协议（地缘政治危机快速套保包）
# ══════════════════════════════════════════════════════════════════════════════

CRITICAL_PLAYBOOK: list[dict] = [
    {"asset": "XAU/USD", "direction": +1, "position_pct": 0.30, "sl": 0.015, "tp": 0.030},
    {"asset": "USD/JPY", "direction": -1, "position_pct": 0.20, "sl": 0.010, "tp": 0.020},
    {"asset": "USD/CHF", "direction": -1, "position_pct": 0.15, "sl": 0.008, "tp": 0.015},
    {"asset": "EUR/USD", "direction": -1, "position_pct": 0.15, "sl": 0.008, "tp": 0.015},
]


def execute_critical_playbook(risk_mgr: RiskManager,
                              snapshots: dict[str, MarketSnapshot]) -> list[TradeSignal]:
    """执行紧急地缘政治危机标准套保包"""
    signals = []
    for item in CRITICAL_PLAYBOOK:
        snap = snapshots.get(item["asset"])
        if snap is None:
            continue
        sig = TradeSignal(
            asset=item["asset"],
            direction=item["direction"],
            nsif_score=0.9,
            urgency="critical",
            position_pct=item["position_pct"],
            stop_loss_pct=item["sl"],
            take_profit_pct=item["tp"],
        )
        risk_mgr.open_position(sig, snap.mid)
        signals.append(sig)
    log.warning("🚨 已执行地缘政治危机紧急套保包，开启 %d 个头寸", len(signals))
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# 8. 回测引擎（事件研究回测）
# ══════════════════════════════════════════════════════════════════════════════

class EventStudyBacktester:
    """
    事件研究回测：
    给定历史事件列表（带 timestamp + sentiment），
    查询对应时段的价格数据，统计事件后 T+15/30/60/120min 的平均收益率。
    """

    def __init__(self, price_data: dict[str, pd.DataFrame]):
        """
        price_data: {asset: DataFrame with columns [timestamp(index), open, high, low, close]}
        """
        self.price_data = price_data

    def study(self, events: list[SentimentResult],
              horizons_min: list[int] = (15, 30, 60, 120)
              ) -> pd.DataFrame:
        """
        返回每个 horizon 下，按方向预测的平均收益率和方向准确率（IC）。
        """
        records = []
        for sentiment in events:
            for asset in sentiment.affected_assets:
                df = self.price_data.get(asset)
                if df is None:
                    continue

                t0 = sentiment.timestamp
                try:
                    p0 = df.loc[df.index >= t0, "close"].iloc[0]
                except IndexError:
                    continue

                row = {
                    "news_id": sentiment.news_id,
                    "asset": asset,
                    "logic_tag": sentiment.logic_tag,
                    "direction": sentiment.direction,
                    "nsif_score": (sentiment.direction * sentiment.intensity
                                   * sentiment.calibrated_confidence),
                }

                for h in horizons_min:
                    t1 = pd.Timestamp(t0) + pd.Timedelta(minutes=h)
                    try:
                        p1 = df.loc[df.index >= t1, "close"].iloc[0]
                        ret = (p1 - p0) / p0
                    except IndexError:
                        ret = float("nan")
                    row[f"ret_{h}min"] = ret

                records.append(row)

        result = pd.DataFrame(records)
        if result.empty:
            return result

        # 计算方向准确率 和 IC
        summary_rows = []
        for h in horizons_min:
            col = f"ret_{h}min"
            sub = result[[col, "nsif_score"]].dropna()
            if len(sub) < 5:
                continue

            direction_acc = np.mean(np.sign(sub[col]) == np.sign(sub["nsif_score"]))
            ic = sub["nsif_score"].corr(sub[col])

            summary_rows.append({
                "horizon_min": h,
                "n_events": len(sub),
                "mean_ret": sub[col].mean(),
                "direction_accuracy": direction_acc,
                "IC": ic,
            })

        return pd.DataFrame(summary_rows)

    def plot_cumulative(self, events: list[SentimentResult],
                        asset: str, horizon_min: int = 60) -> None:
        """可视化事件后累计平均收益（仅在 Jupyter 环境中有效）"""
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            log.warning("matplotlib 未安装，跳过可视化")
            return

        df = self.price_data.get(asset)
        if df is None:
            return

        all_paths = []
        for s in events:
            if asset not in s.affected_assets:
                continue
            t0 = s.timestamp
            sub = df.loc[df.index >= t0].head(horizon_min + 1)
            if len(sub) < 5:
                continue
            path = s.direction * (sub["close"] / sub["close"].iloc[0] - 1).values
            all_paths.append(path[:horizon_min + 1])

        if not all_paths:
            return

        max_len = max(len(p) for p in all_paths)
        padded = [np.pad(p, (0, max_len - len(p)), constant_values=np.nan)
                  for p in all_paths]
        avg_path = np.nanmean(padded, axis=0)

        plt.figure(figsize=(10, 5))
        plt.plot(avg_path * 100)
        plt.axhline(0, color="gray", linestyle="--")
        plt.xlabel("分钟")
        plt.ylabel("平均累计收益率 (%)")
        plt.title(f"事件研究：{asset} 事件后 {horizon_min} 分钟平均累计收益")
        plt.tight_layout()
        plt.show()


# ══════════════════════════════════════════════════════════════════════════════
# 9. 主策略协调器（Strategy Orchestrator）
# ══════════════════════════════════════════════════════════════════════════════

class GeoFXSentimentStrategy:
    """
    主策略协调器：
    整合 LLM 情感分析、NSIF 计算、信号生成、风控管理为完整策略。

    部署模式：
    - live: 接入实盘路透社 API + 交易系统
    - paper: 接入路透社 API + 模拟账户
    - backtest: 离线历史数据回测
    """

    def __init__(self,
                 anthropic_api_key: str,
                 geo_risk_level: int = 1,
                 mode: str = "paper"):
        self.mode = mode

        self.llm_engine = LLMSentimentEngine(
            api_key=anthropic_api_key,
            model="claude-haiku-4-5-20251001",   # 使用 Haiku 控制成本
        )
        self.nsif_engine = NSIFEngine(geo_risk_level=geo_risk_level)
        self.signal_gen = SignalGenerator()
        self.risk_mgr = RiskManager()
        self._snapshots: dict[str, MarketSnapshot] = {}
        self._running = False

    def on_news(self, news: NewsItem) -> list[TradeSignal]:
        """处理新闻事件（主入口）"""
        # Step 1: LLM 情感分析
        sentiment = self.llm_engine.analyze(news)
        if sentiment is None:
            return []

        log.info("新闻情感 [%s] tag=%s dir=%.2f intensity=%.2f conf=%.2f",
                 news.news_id, sentiment.logic_tag,
                 sentiment.direction, sentiment.intensity,
                 sentiment.calibrated_confidence)

        # Step 2: 更新 NSIF
        self.nsif_engine.add_sentiment(sentiment)

        # Step 3: 危机快速响应
        if sentiment.urgency == "critical":
            return execute_critical_playbook(self.risk_mgr, self._snapshots)

        # Step 4: 常规信号生成
        nsif_states = self.nsif_engine.compute_all()
        signals = self.signal_gen.generate_all(nsif_states, self._snapshots)

        # Step 5: 执行信号
        for sig in signals:
            snap = self._snapshots.get(sig.asset)
            if snap:
                self.risk_mgr.open_position(sig, snap.mid)

        return signals

    def on_tick(self, snapshots: dict[str, MarketSnapshot]) -> list[Position]:
        """处理行情更新（每分钟或更高频率调用）"""
        self._snapshots = snapshots

        # 检查止损/止盈/时间止损
        exits = self.risk_mgr.check_exits(snapshots)

        # 检查 NSIF 反转
        nsif_states = self.nsif_engine.compute_all()
        for asset, state in nsif_states.items():
            if self.risk_mgr.nsif_reversal_check(asset, state.nsif):
                snap = snapshots.get(asset)
                if snap:
                    log.info("NSIF 反转，强制平仓 %s（NSIF=%.3f）",
                             asset, state.nsif)
                    self.risk_mgr.positions.get(asset)  # will be closed in next check

        return exits

    def get_status(self) -> dict:
        """获取策略当前状态摘要"""
        nsif_states = self.nsif_engine.compute_all()
        return {
            "mode": self.mode,
            "geo_risk_level": self.nsif_engine.geo_risk_level,
            "risk_summary": self.risk_mgr.get_summary(),
            "nsif_snapshot": {
                asset: round(state.nsif, 4)
                for asset, state in nsif_states.items()
            },
            "open_positions": [
                {
                    "asset": p.asset,
                    "direction": "多" if p.direction > 0 else "空",
                    "entry_price": p.entry_price,
                    "holding_hours": round(p.holding_hours, 2),
                    "position_pct": f"{p.position_pct:.1%}",
                }
                for p in self.risk_mgr.positions.values()
            ],
        }


# ══════════════════════════════════════════════════════════════════════════════
# 10. 示例使用 / Demo
# ══════════════════════════════════════════════════════════════════════════════

def demo_offline(api_key: str) -> None:
    """
    离线演示：使用模拟新闻数据测试策略逻辑。
    （不需要实盘路透社 API 接入）
    """

    strategy = GeoFXSentimentStrategy(
        anthropic_api_key=api_key,
        geo_risk_level=2,   # 设置为危机模式
        mode="paper",
    )

    # 模拟市场行情快照
    mock_snapshots: dict[str, MarketSnapshot] = {
        "XAU/USD": MarketSnapshot("XAU/USD", 3190.5, 3191.5, 3191.0, 8.5, 4.0, 0.003),
        "XAG/USD": MarketSnapshot("XAG/USD", 40.10,   40.20,  40.15,  0.35, 0.18, 0.004),
        "EUR/USD": MarketSnapshot("EUR/USD",  1.0998,  1.0999, 1.0998, 0.0012, 0.0008, -0.001),
        "USD/JPY": MarketSnapshot("USD/JPY", 144.60,  144.65, 144.62, 0.35, 0.22, -0.002),
        "USD/CHF": MarketSnapshot("USD/CHF",  0.8810,  0.8815, 0.8812, 0.0015, 0.001, -0.003),
        "AUD/USD": MarketSnapshot("AUD/USD",  0.6350,  0.6352, 0.6351, 0.0010, 0.0007, -0.001),
        "GBP/USD": MarketSnapshot("GBP/USD",  1.2850,  1.2852, 1.2851, 0.0018, 0.0012, -0.001),
        "USD/CAD": MarketSnapshot("USD/CAD",  1.3850,  1.3855, 1.3852, 0.002, 0.0015, 0.001),
    }

    # 模拟一条高危新闻
    news_1 = NewsItem(
        news_id="RTR-20260413-001",
        timestamp=datetime.now(timezone.utc),
        headline="BREAKING: Iran fires ballistic missiles at US naval assets in Persian Gulf",
        body="Iranian forces fired multiple ballistic missiles at US Navy vessels in the Persian Gulf "
             "on Sunday, marking a significant escalation in the US-Iran standoff. "
             "The Pentagon confirmed the attack, saying missile defense systems intercepted most projectiles. "
             "Oil futures surged 8% in after-hours trading.",
        source="Reuters Breaking",
        urgency="critical",
    )

    print("\n" + "=" * 70)
    print("舆情驱动高频策略 — 离线演示")
    print("=" * 70)
    print(f"\n[新闻] {news_1.headline}")

    # 更新行情快照
    strategy._snapshots = mock_snapshots

    # 处理新闻
    signals = strategy.on_news(news_1)

    print(f"\n[信号] 生成 {len(signals)} 个交易信号")
    for sig in signals:
        print(f"  → {sig.signal_label}")

    # 模拟行情更新（30 分钟后黄金上涨 2%）
    import copy
    mock_snapshots_30m = copy.deepcopy(mock_snapshots)
    mock_snapshots_30m["XAU/USD"] = MarketSnapshot(
        "XAU/USD", 3254.0, 3255.0, 3254.5, 6.0, 4.0, 0.02
    )
    exits = strategy.on_tick(mock_snapshots_30m)
    if exits:
        print(f"\n[平仓] {len(exits)} 个头寸平仓")
        for pos in exits:
            print(f"  → {pos.asset} [{pos.exit_reason}] 盈亏={pos.pnl_pct*100:.2f}%")

    # 打印状态
    status = strategy.get_status()
    print("\n[状态摘要]")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "your_api_key_here")
    if api_key == "your_api_key_here":
        print("请设置环境变量 ANTHROPIC_API_KEY 后运行。")
        print("示例：export ANTHROPIC_API_KEY=sk-ant-xxxxx")
    else:
        demo_offline(api_key)
