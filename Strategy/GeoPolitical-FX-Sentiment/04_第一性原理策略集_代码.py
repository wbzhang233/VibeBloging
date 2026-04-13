"""
策略动物园：从第一性原理出发的五大策略核心实现
Strategy Zoo: Five Strategies from First Principles

策略 A: 过度反应-回归 (Overreaction-Reversion)        — 行为金融学 + 事件研究
策略 B: 避险资产相对价值 (Safe-Haven Relative Value)   — 资产定价演绎
策略 C: 新闻流物理学 (News Flow Physics)              — 信息传播动力学
策略 D: 套息交易脆弱性 (Carry Trade Fragility)        — 复杂系统/沙堆模型
策略 E: 央行语义漂移 (Central Bank Semantic Drift)     — NLP + 央行沟通学

所有策略共享同一数据管道（新闻 + 分钟行情），可并行运行、独立风控。

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
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("strategy-zoo")


# ══════════════════════════════════════════════════════════════════════════════
# 0. 共享数据结构
# ══════════════════════════════════════════════════════════════════════════════

SAFE_HAVENS = ["XAU/USD", "USD/CHF", "USD/JPY"]
RISK_ASSETS = ["EUR/USD", "GBP/USD", "AUD/USD"]
ALL_ASSETS = SAFE_HAVENS + RISK_ASSETS + ["USD/CAD", "BRENT"]

CENTRAL_BANKS = ["Fed", "ECB", "BoJ", "BoE", "SNB", "BoC", "RBA"]


@dataclass
class NewsItem:
    """单条新闻"""
    timestamp: datetime
    headline: str
    source: str
    urgency: str = "headline"  # breaking / flash / headline / analysis / commentary
    body: str = ""


@dataclass
class PriceBar:
    """分钟级价格"""
    timestamp: datetime
    asset: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class TradeSignal:
    """策略输出信号"""
    timestamp: datetime
    strategy: str
    asset: str
    direction: str          # "long" / "short" / "close"
    size_pct: float         # 目标仓位占比 (0.0-1.0)
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    max_hold_minutes: int = 180
    confidence: float = 0.5
    reason: str = ""


class BaseStrategy(ABC):
    """策略基类"""

    def __init__(self, name: str):
        self.name = name
        self.signals: list[TradeSignal] = []
        self.log = logging.getLogger(f"zoo.{name}")

    @abstractmethod
    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        """新闻事件触发"""
        ...

    @abstractmethod
    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        """价格更新触发"""
        ...

    def _emit(self, signal: TradeSignal) -> TradeSignal:
        self.signals.append(signal)
        self.log.info(
            "SIGNAL %s %s %.4f | SL=%.4f TP=%s | %s",
            signal.direction.upper(), signal.asset, signal.entry_price,
            signal.stop_loss,
            f"{signal.take_profit:.4f}" if signal.take_profit else "trailing",
            signal.reason,
        )
        return signal


# ══════════════════════════════════════════════════════════════════════════════
# A. 过度反应-回归策略 (Overreaction-Reversion)
# ══════════════════════════════════════════════════════════════════════════════
#
# 假设：人类对突发威胁先剧烈反应，再理性评估。
#       一次性冲击在 30-90 分钟内过度偏离，随后 1-4 小时回归 30-60%。
# 方法：归纳法 (事件研究统计)
# LLM角色：事件分类器 (one_shot vs structural)
# ══════════════════════════════════════════════════════════════════════════════

class OverreactionReversionStrategy(BaseStrategy):
    """
    策略 A: 检测 3σ 冲击 → LLM 分类事件类型 → 逆向入场捕捉回调
    """

    # 冲击检测参数
    SHOCK_LOOKBACK_BARS = 60        # 用 60 根 5min 棒计算统计量
    SHOCK_SIGMA = 3.0               # 偏离阈值
    PEAK_CONFIRM_BARS = 3           # 连续 N 根不创新极值视为峰值
    PEAK_CONFIRM_MINUTES = 30       # 或等待 N 分钟

    # 交易参数
    REVERSION_TARGET_PCT = 0.5      # 目标回调 50%（即回到冲击幅度的一半）
    STOP_EXTENSION_PCT = 0.005      # 极值外 0.5% 止损
    MAX_HOLD_MINUTES = 180          # 最长 3 小时

    # LLM 置信度阈值
    MIN_REVERSION_PROB = 0.6

    def __init__(self):
        super().__init__("A-Overreaction-Reversion")
        self.client = anthropic.Anthropic()
        self._returns_buffer: dict[str, deque] = {}  # asset → recent returns
        self._shock_state: dict[str, dict] = {}      # asset → shock tracking

    # ── 统计量计算 ──────────────────────────────────────────────────────────

    def _update_returns(self, bar: PriceBar):
        """维护每个资产的 5min 收益率滑动窗口"""
        buf = self._returns_buffer.setdefault(
            bar.asset, deque(maxlen=self.SHOCK_LOOKBACK_BARS)
        )
        if buf:
            ret = (bar.close - buf[-1]) / abs(buf[-1]) if buf[-1] != 0 else 0
        else:
            ret = 0.0
        buf.append(bar.close)
        return ret

    def _detect_shock(self, asset: str, current_return: float) -> Optional[float]:
        """检测 3σ 冲击，返回冲击幅度或 None"""
        buf = self._returns_buffer.get(asset)
        if not buf or len(buf) < 20:
            return None

        prices = list(buf)
        returns = np.diff(prices) / np.abs(prices[:-1] + 1e-10)
        if len(returns) < 10:
            return None

        mu = np.mean(returns)
        sigma = np.std(returns) + 1e-10

        z_score = (current_return - mu) / sigma
        if abs(z_score) >= self.SHOCK_SIGMA:
            return current_return
        return None

    # ── LLM 事件分类 ───────────────────────────────────────────────────────

    def _classify_event(self, headlines: list[str]) -> dict:
        """
        LLM 判断: 一次性冲击 vs 结构性转变
        返回: {event_type, reversion_probability, expected_reversion_pct}
        """
        prompt = f"""你是地缘政治与金融市场资深分析师。

以下是最近30分钟的新闻标题：
{json.dumps(headlines, ensure_ascii=False, indent=2)}

请判断这些新闻描述的事件是：
- "one_shot": 一次性冲击（单次军事打击、外交事件、数据意外）
- "structural": 结构性变量变化（政策转向、制度变化、联盟重组）

返回严格 JSON:
{{
  "event_type": "one_shot" | "structural",
  "reversion_probability": 0.0-1.0,
  "expected_reversion_pct": 0.0-1.0,
  "reasoning": "一句话理由"
}}"""

        try:
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            # 提取 JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception as e:
            self.log.warning("LLM classify failed: %s", e)

        return {
            "event_type": "one_shot",
            "reversion_probability": 0.5,
            "expected_reversion_pct": 0.4,
        }

    # ── 峰值确认 ───────────────────────────────────────────────────────────

    def _check_peak_confirmed(self, asset: str, bar: PriceBar) -> bool:
        """冲击后，连续 N 根 K 线不创新极值 → 峰值确认"""
        state = self._shock_state.get(asset)
        if not state:
            return False

        direction = state["direction"]  # "up" or "down"
        extreme = state["extreme_price"]

        # 更新极值
        if direction == "up" and bar.high > extreme:
            state["extreme_price"] = bar.high
            state["confirm_count"] = 0
            return False
        elif direction == "down" and bar.low < extreme:
            state["extreme_price"] = bar.low
            state["confirm_count"] = 0
            return False

        state["confirm_count"] = state.get("confirm_count", 0) + 1

        # 时间确认
        elapsed = (bar.timestamp - state["shock_time"]).total_seconds() / 60
        if elapsed >= self.PEAK_CONFIRM_MINUTES:
            return True

        # K线数确认
        if state["confirm_count"] >= self.PEAK_CONFIRM_BARS:
            return True

        return False

    # ── 主入口 ─────────────────────────────────────────────────────────────

    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        return None  # 本策略由价格冲击触发，非直接由新闻触发

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        ret = self._update_returns(bar)
        now = bar.timestamp

        # 已在跟踪某资产的冲击
        if bar.asset in self._shock_state:
            if self._check_peak_confirmed(bar.asset, bar):
                state = self._shock_state.pop(bar.asset)
                # 逆向入场
                direction = "short" if state["direction"] == "up" else "long"
                extreme = state["extreme_price"]
                shock_size = abs(extreme - state["pre_shock_price"])
                target_price = extreme - (shock_size * self.REVERSION_TARGET_PCT) * (
                    1 if state["direction"] == "up" else -1
                )
                stop_price = extreme * (
                    1 + self.STOP_EXTENSION_PCT if state["direction"] == "up"
                    else 1 - self.STOP_EXTENSION_PCT
                )

                return self._emit(TradeSignal(
                    timestamp=now,
                    strategy=self.name,
                    asset=bar.asset,
                    direction=direction,
                    size_pct=state.get("size_pct", 0.15),
                    entry_price=bar.close,
                    stop_loss=stop_price,
                    take_profit=target_price,
                    max_hold_minutes=self.MAX_HOLD_MINUTES,
                    confidence=state.get("reversion_prob", 0.6),
                    reason=f"Peak confirmed, revert {state['direction']} shock "
                           f"from {state['pre_shock_price']:.4f} to {extreme:.4f}",
                ))
            return None

        # 检测新冲击
        shock = self._detect_shock(bar.asset, ret)
        if shock is not None:
            self.log.info("SHOCK detected: %s ret=%.4f", bar.asset, shock)

            # 收集近期新闻标题（由外部注入或模拟）
            headlines = getattr(self, "_recent_headlines", [])
            classification = self._classify_event(headlines)

            if classification["event_type"] == "structural":
                self.log.info("Structural event → skip reversion for %s", bar.asset)
                return None

            reversion_prob = classification.get("reversion_probability", 0.5)
            if reversion_prob < self.MIN_REVERSION_PROB:
                self.log.info("Reversion prob %.2f < threshold → skip", reversion_prob)
                return None

            # 进入峰值确认跟踪
            self._shock_state[bar.asset] = {
                "direction": "up" if shock > 0 else "down",
                "shock_time": now,
                "pre_shock_price": bar.open,
                "extreme_price": bar.high if shock > 0 else bar.low,
                "confirm_count": 0,
                "reversion_prob": reversion_prob,
                "expected_reversion": classification.get("expected_reversion_pct", 0.5),
                "size_pct": min(0.20, 0.10 + reversion_prob * 0.10),
            }
            self.log.info(
                "Tracking %s shock for peak confirmation (prob=%.2f)",
                bar.asset, reversion_prob,
            )

        return None


# ══════════════════════════════════════════════════════════════════════════════
# B. 避险资产相对价值策略 (Safe-Haven Relative Value)
# ══════════════════════════════════════════════════════════════════════════════
#
# 假设：黄金/瑞郎/日元避险来源不同，不同危机中相对强弱不同。
#       交易"排序"比押"方向"更稳定。
# 方法：演绎法 (资产定价理论)
# LLM角色：危机类型判断 → 避险排序
# ══════════════════════════════════════════════════════════════════════════════

class CrisisType(Enum):
    MILITARY_CONFLICT = "military"      # 军事冲突 → XAU >> JPY > CHF
    BOJ_HAWKISH = "boj_hawkish"         # BoJ 鹰派 → JPY >> XAU ~ CHF
    US_FISCAL = "us_fiscal"             # 美国财政危机 → XAU >> CHF > JPY
    SYSTEMIC_FINANCIAL = "systemic"     # 全球金融风险 → USD >> all
    TRADE_WAR = "trade_war"             # 贸易战 → XAU > CHF > JPY
    DEESCALATION = "deescalation"       # 地缘缓和 → 反转


# 危机类型 → 避险资产预期排序（从强到弱）
CRISIS_RANKING = {
    CrisisType.MILITARY_CONFLICT:  ["XAU/USD", "USD/JPY", "USD/CHF"],
    CrisisType.BOJ_HAWKISH:        ["USD/JPY", "XAU/USD", "USD/CHF"],
    CrisisType.US_FISCAL:          ["XAU/USD", "USD/CHF", "USD/JPY"],
    CrisisType.SYSTEMIC_FINANCIAL: ["USD/CHF", "XAU/USD", "USD/JPY"],
    CrisisType.TRADE_WAR:          ["XAU/USD", "USD/CHF", "USD/JPY"],
}

# 信号方向映射：排序中做多最强(long)、做空最弱(short)
# 注意：USD/JPY 和 USD/CHF 中，safe-haven 走强 = USD/X 下跌 = 做空
PAIR_DIRECTION_MAP = {
    "XAU/USD": {"strong": "long", "weak": "short"},     # 黄金强=做多
    "USD/JPY": {"strong": "short", "weak": "long"},      # 日元强=做空USD/JPY
    "USD/CHF": {"strong": "short", "weak": "long"},      # 瑞郎强=做空USD/CHF
}


class SafeHavenRelativeValueStrategy(BaseStrategy):
    """
    策略 B: 配对交易——LLM 判断危机类型 → 做多最强避险 / 做空最弱避险
    """

    REBALANCE_INTERVAL_MINUTES = 60   # 每小时重新评估
    PAIR_SIZE_PCT = 0.15              # 每条腿 15%

    def __init__(self):
        super().__init__("B-SafeHaven-RelativeValue")
        self.client = anthropic.Anthropic()
        self._last_rebalance: Optional[datetime] = None
        self._current_crisis: Optional[CrisisType] = None
        self._current_pair: Optional[tuple[str, str]] = None  # (long_asset, short_asset)

    def _classify_crisis(self, headlines: list[str], price_context: str) -> dict:
        """LLM 判断当前危机类型"""
        crisis_options = "\n".join(
            f"  {ct.value}: {ct.name}" for ct in CrisisType
        )

        prompt = f"""你是避险资产配置专家。

最近新闻标题：
{json.dumps(headlines[-15:], ensure_ascii=False, indent=2)}

当前市场：
{price_context}

请判断当前主要危机类型（选一个最主要的）：
{crisis_options}

返回严格 JSON:
{{
  "crisis_type": "military" | "boj_hawkish" | "us_fiscal" | "systemic" | "trade_war" | "deescalation",
  "confidence": 0.0-1.0,
  "ranking": ["最强避险资产", "第二", "最弱"],
  "reasoning": "一句话"
}}"""

        try:
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception as e:
            self.log.warning("LLM crisis classify failed: %s", e)

        return {"crisis_type": "military", "confidence": 0.5, "ranking": []}

    def _build_pair_trade(
        self, crisis: CrisisType, prices: dict[str, float], now: datetime
    ) -> list[TradeSignal]:
        """根据危机排序构建配对交易"""
        ranking = CRISIS_RANKING.get(crisis)
        if not ranking or len(ranking) < 2:
            return []

        strongest = ranking[0]
        weakest = ranking[-1]

        signals = []

        # 做多最强
        strong_dir = PAIR_DIRECTION_MAP[strongest]["strong"]
        price_s = prices.get(strongest, 0)
        if price_s > 0:
            # ATR 近似（用价格的 0.5% 作为简化止损）
            sl_dist = price_s * 0.005
            signals.append(TradeSignal(
                timestamp=now,
                strategy=self.name,
                asset=strongest,
                direction=strong_dir,
                size_pct=self.PAIR_SIZE_PCT,
                entry_price=price_s,
                stop_loss=price_s - sl_dist if strong_dir == "long" else price_s + sl_dist,
                take_profit=None,
                max_hold_minutes=480,
                confidence=0.65,
                reason=f"Pair leg: {strongest} is STRONGEST in {crisis.value} crisis",
            ))

        # 做空最弱
        weak_dir = PAIR_DIRECTION_MAP[weakest]["weak"]
        price_w = prices.get(weakest, 0)
        if price_w > 0:
            sl_dist = price_w * 0.005
            signals.append(TradeSignal(
                timestamp=now,
                strategy=self.name,
                asset=weakest,
                direction=weak_dir,
                size_pct=self.PAIR_SIZE_PCT,
                entry_price=price_w,
                stop_loss=price_w + sl_dist if weak_dir == "short" else price_w - sl_dist,
                take_profit=None,
                max_hold_minutes=480,
                confidence=0.65,
                reason=f"Pair leg: {weakest} is WEAKEST in {crisis.value} crisis",
            ))

        return signals

    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        return None  # 由定时重平衡驱动

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        now = bar.timestamp

        if self._last_rebalance and (
            now - self._last_rebalance
        ).total_seconds() < self.REBALANCE_INTERVAL_MINUTES * 60:
            return None

        self._last_rebalance = now

        # 收集价格快照
        prices = {}
        for asset, bars_list in recent_bars.items():
            if bars_list:
                prices[asset] = bars_list[-1].close

        price_ctx = ", ".join(f"{a}: {p:.4f}" for a, p in prices.items())
        headlines = getattr(self, "_recent_headlines", [])

        result = self._classify_crisis(headlines, price_ctx)
        try:
            crisis = CrisisType(result["crisis_type"])
        except (ValueError, KeyError):
            crisis = CrisisType.MILITARY_CONFLICT

        self.log.info(
            "Crisis classified: %s (conf=%.2f)",
            crisis.value, result.get("confidence", 0),
        )

        if result.get("crisis_type") == "deescalation":
            self.log.info("De-escalation → close all pairs")
            # 返回平仓信号（简化处理）
            return None

        pair_signals = self._build_pair_trade(crisis, prices, now)
        for sig in pair_signals:
            self._emit(sig)

        return pair_signals[0] if pair_signals else None


# ══════════════════════════════════════════════════════════════════════════════
# C. 新闻流物理学策略 (News Flow Physics)
# ══════════════════════════════════════════════════════════════════════════════
#
# 假设：新闻不是"内容"重要，是"流速"和"加速度"重要。
#       加速度过零点 = 价格拐点领先指标。
# 方法：第一性原理 (信息传播动力学)
# LLM角色：不需要 LLM（纯量化）
# ══════════════════════════════════════════════════════════════════════════════

# 新闻紧急度权重
URGENCY_WEIGHT = {
    "breaking": 3.0,
    "flash": 3.0,
    "headline": 2.0,
    "analysis": 1.0,
    "commentary": 0.5,
}

# 新闻来源权重（质量代理）
SOURCE_WEIGHT = {
    "Reuters": 2.0,
    "Bloomberg": 2.0,
    "AP": 1.5,
    "AFP": 1.5,
    "CNBC": 1.0,
    "Twitter": 0.5,
}


class NewsFlowPhysicsStrategy(BaseStrategy):
    """
    策略 C: 将新闻流视为物理系统，用速度/加速度预测市场状态转换

    物理量映射:
      x(t) = 累计加权新闻数量       → 市场关注度
      v(t) = dx/dt = 新闻频率       → 市场紧张程度
      a(t) = dv/dt = 频率变化率     → 状态转换信号
      m    = 来源权重               → 信息可信度
      F    = m × a = 加权加速度     → 实际市场冲击力
    """

    VELOCITY_WINDOW_MINUTES = 10     # 速度计算窗口
    SAMPLE_INTERVAL_MINUTES = 1      # 速度采样频率
    VELOCITY_HISTORY = 60            # 保留 60 分钟速度历史

    # 信号阈值
    VELOCITY_SURGE_MULTIPLIER = 2.5  # v > v_avg * 2.5 触发趋势追随
    ACCELERATION_ZERO_CROSS = True   # 加速度过零 = 反转信号

    def __init__(self):
        super().__init__("C-NewsFlow-Physics")
        self._news_buffer: deque[tuple[datetime, float]] = deque(maxlen=1000)
        self._velocity_series: deque[tuple[datetime, float]] = deque(
            maxlen=self.VELOCITY_HISTORY
        )
        self._last_sample_time: Optional[datetime] = None
        self._position_state: str = "flat"  # flat / trend_follow / reverting
        self._trend_direction: Optional[str] = None  # "up" / "down"

    def _weighted_count(self, news: NewsItem) -> float:
        """加权新闻计数 = urgency × source_weight"""
        u = URGENCY_WEIGHT.get(news.urgency, 1.0)
        s = SOURCE_WEIGHT.get(news.source, 1.0)
        return u * s

    def _compute_velocity(self, now: datetime) -> float:
        """
        当前时刻的新闻流速度（加权条数/分钟）
        v(t) = Σ weighted_count / window_minutes
        """
        cutoff = now - timedelta(minutes=self.VELOCITY_WINDOW_MINUTES)
        total = sum(w for t, w in self._news_buffer if t >= cutoff)
        return total / self.VELOCITY_WINDOW_MINUTES

    def _compute_acceleration(self) -> float:
        """
        速度的一阶差分 = 加速度
        a(t) = v(t) - v(t-1)
        """
        if len(self._velocity_series) < 2:
            return 0.0
        return self._velocity_series[-1][1] - self._velocity_series[-2][1]

    def _compute_force(self) -> float:
        """
        F = m × a（加权加速度，m 已隐含在速度计算中）
        简化为: 近期高权重新闻占比 × 加速度
        """
        return self._compute_acceleration()  # 权重已在速度计算中体现

    def _avg_velocity(self) -> float:
        """历史平均速度"""
        if not self._velocity_series:
            return 0.0
        return np.mean([v for _, v in self._velocity_series])

    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        """每条新闻入库"""
        weight = self._weighted_count(news)
        self._news_buffer.append((news.timestamp, weight))
        return None

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        """
        每根 K 线更新速度/加速度，生成三类信号:
          信号 1: 加速突破（趋势追随）
          信号 2: 加速度过零（反转）
          信号 3: 速度归零（平仓）
        """
        now = bar.timestamp

        # 每分钟采样一次速度
        if self._last_sample_time is None or (
            now - self._last_sample_time
        ).total_seconds() >= self.SAMPLE_INTERVAL_MINUTES * 60:
            v = self._compute_velocity(now)
            self._velocity_series.append((now, v))
            self._last_sample_time = now

        if len(self._velocity_series) < 5:
            return None

        v_current = self._velocity_series[-1][1]
        v_avg = self._avg_velocity()
        a_current = self._compute_acceleration()

        # 判断市场趋势方向（用最近 K 线）
        xau_bars = recent_bars.get("XAU/USD", [])
        if len(xau_bars) >= 3:
            recent_ret = (xau_bars[-1].close - xau_bars[-3].close) / xau_bars[-3].close
            price_direction = "up" if recent_ret > 0 else "down"
        else:
            return None

        # ── 信号 1: 加速突破（趋势追随）────────────────────────────────
        if (
            v_current > v_avg * self.VELOCITY_SURGE_MULTIPLIER
            and a_current > 0
            and self._position_state == "flat"
        ):
            direction = "long" if price_direction == "up" else "short"
            self._position_state = "trend_follow"
            self._trend_direction = price_direction

            price = bar.close
            sl_dist = price * 0.008  # 0.8% 止损
            return self._emit(TradeSignal(
                timestamp=now,
                strategy=self.name,
                asset="XAU/USD",
                direction=direction,
                size_pct=0.20,
                entry_price=price,
                stop_loss=price - sl_dist if direction == "long" else price + sl_dist,
                take_profit=None,
                max_hold_minutes=120,
                confidence=min(0.9, 0.5 + v_current / (v_avg * 5 + 1e-10)),
                reason=f"News surge: v={v_current:.2f} >> avg={v_avg:.2f}, a={a_current:.3f}>0",
            ))

        # ── 信号 2: 加速度过零（反转信号）────────────────────────────────
        if len(self._velocity_series) >= 3:
            a_prev = self._velocity_series[-2][1] - self._velocity_series[-3][1]
            zero_cross = (a_prev > 0 and a_current <= 0)

            if (
                zero_cross
                and v_current > v_avg
                and self._position_state == "trend_follow"
            ):
                # 减仓或反向小仓位
                self._position_state = "reverting"
                rev_direction = "short" if self._trend_direction == "up" else "long"

                price = bar.close
                sl_dist = price * 0.006
                return self._emit(TradeSignal(
                    timestamp=now,
                    strategy=self.name,
                    asset="XAU/USD",
                    direction=rev_direction,
                    size_pct=0.10,  # 小仓位反向
                    entry_price=price,
                    stop_loss=price + sl_dist if rev_direction == "short" else price - sl_dist,
                    take_profit=None,
                    max_hold_minutes=60,
                    confidence=0.55,
                    reason=f"Acceleration zero-cross: a {a_prev:.3f}→{a_current:.3f}, peak passed",
                ))

        # ── 信号 3: 速度归零（全部平仓）─────────────────────────────────
        if v_current <= v_avg and self._position_state != "flat":
            self._position_state = "flat"
            self._trend_direction = None
            return self._emit(TradeSignal(
                timestamp=now,
                strategy=self.name,
                asset="XAU/USD",
                direction="close",
                size_pct=0.0,
                entry_price=bar.close,
                stop_loss=bar.close,
                reason=f"Velocity normalized: v={v_current:.2f} <= avg={v_avg:.2f}",
            ))

        return None


# ══════════════════════════════════════════════════════════════════════════════
# D. 套息交易脆弱性策略 (Carry Trade Fragility)
# ══════════════════════════════════════════════════════════════════════════════
#
# 假设：日元套息头寸在稳态下积累，在冲击下非线性崩溃。
#       识别"临界态"后，一个小触发即可引发雪崩式平仓。
# 方法：演绎法 (复杂系统/沙堆模型)
# LLM角色：辅助（脆弱性指标中的 BoJ 信号组件）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CarryFragilityState:
    """套息脆弱性系统状态"""
    # CFTC 日元投机性空头持仓百分位（0-1）
    cftc_jpy_short_percentile: float = 0.5
    # 短期 vs 长期隐含波动率比值（>1 = 期限结构倒挂）
    vol_term_ratio: float = 0.9
    # 高息货币相关性（正常 0.3-0.5，共振 >0.7）
    cross_carry_correlation: float = 0.4
    # BoJ 鹰派信号评分 (-5 到 +5)
    boj_hawkish_score: float = 0.0


class CarryTradeFragilityStrategy(BaseStrategy):
    """
    策略 D: 沙堆模型——监控脆弱性积累，捕捉套息平仓雪崩

    四阶段操作:
      1. 脆弱性积累（建小额底仓）
      2. 触发事件检测（加仓）
      3. 雪崩加速（追踪止损跟随）
      4. 雪崩结束（平仓 80%）
    """

    # 脆弱性指数权重
    W_CFTC = 0.30
    W_VOL_TERM = 0.25
    W_CORRELATION = 0.25
    W_BOJ = 0.20

    # 阈值
    FRAGILITY_THRESHOLD = 0.65       # 脆弱性指数进入临界态
    TRIGGER_JPY_5MIN_PCT = -0.005    # USD/JPY 5分钟跌 0.5%
    TRIGGER_VIX_JUMP_PCT = 0.10      # VIX 日内涨 10%
    AVALANCHE_ACCEL_BARS = 3         # 连续加速确认

    # 仓位
    BASE_SIZE = 0.05                 # 底仓 5%
    TRIGGER_SIZE = 0.25              # 触发后 25%
    TRAIL_STOP_PCT = 0.008           # 追踪止损 0.8%

    class Phase(Enum):
        MONITORING = "monitoring"
        BASE_POSITION = "base"
        TRIGGERED = "triggered"
        AVALANCHE = "avalanche"
        COOLING = "cooling"

    def __init__(self):
        super().__init__("D-CarryTrade-Fragility")
        self.fragility = CarryFragilityState()
        self.phase = self.Phase.MONITORING
        self._trigger_time: Optional[datetime] = None
        self._best_price: Optional[float] = None  # 雪崩中的最佳价格

    def compute_fragility_index(self) -> float:
        """
        Carry_Fragility_Index = w1×CFTC + w2×Vol_Term + w3×Correlation + w4×BoJ

        各分量归一化到 [0, 1]
        """
        # CFTC: percentile 直接用
        cftc_score = self.fragility.cftc_jpy_short_percentile

        # Vol term: ratio > 1 = 倒挂 → 高分
        vol_score = min(1.0, max(0.0, (self.fragility.vol_term_ratio - 0.7) / 0.6))

        # Correlation: > 0.7 = 共振
        corr_score = min(1.0, max(0.0, (self.fragility.cross_carry_correlation - 0.3) / 0.5))

        # BoJ: 归一化 [-5, 5] → [0, 1]
        boj_score = (self.fragility.boj_hawkish_score + 5) / 10.0
        boj_score = min(1.0, max(0.0, boj_score))

        index = (
            self.W_CFTC * cftc_score
            + self.W_VOL_TERM * vol_score
            + self.W_CORRELATION * corr_score
            + self.W_BOJ * boj_score
        )
        return index

    def update_fragility(self, **kwargs):
        """外部注入脆弱性指标更新"""
        for key, val in kwargs.items():
            if hasattr(self.fragility, key):
                setattr(self.fragility, key, val)

    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        """BoJ 相关新闻 → 更新 boj_hawkish_score"""
        headline_lower = news.headline.lower()
        boj_keywords = ["boj", "bank of japan", "日銀", "植田", "ueda", "利上げ"]

        if any(kw in headline_lower for kw in boj_keywords):
            # 简单规则：加息/鹰派相关 → +1，降息/鸽派 → -1
            hawkish_kw = ["hike", "raise", "hawkish", "tighten", "normalize",
                          "利上げ", "引き締め"]
            dovish_kw = ["pause", "dovish", "patient", "cautious", "据え置き"]

            delta = 0
            for kw in hawkish_kw:
                if kw in headline_lower:
                    delta += 1.0
                    break
            for kw in dovish_kw:
                if kw in headline_lower:
                    delta -= 1.0
                    break

            if delta != 0:
                self.fragility.boj_hawkish_score = max(
                    -5, min(5, self.fragility.boj_hawkish_score + delta)
                )
                self.log.info(
                    "BoJ signal updated: score=%.1f (%+.1f)",
                    self.fragility.boj_hawkish_score, delta,
                )
        return None

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        if bar.asset != "USD/JPY":
            return None

        now = bar.timestamp
        fi = self.compute_fragility_index()

        usdjpy_bars = recent_bars.get("USD/JPY", [])

        # ── 阶段 1: 监控 → 底仓 ────────────────────────────────────────
        if self.phase == self.Phase.MONITORING and fi > self.FRAGILITY_THRESHOLD:
            self.phase = self.Phase.BASE_POSITION
            self.log.info("Fragility index %.3f > threshold → base position", fi)

            return self._emit(TradeSignal(
                timestamp=now,
                strategy=self.name,
                asset="USD/JPY",
                direction="short",
                size_pct=self.BASE_SIZE,
                entry_price=bar.close,
                stop_loss=bar.close * 1.015,  # 1.5% 宽止损
                max_hold_minutes=7200,  # 5天
                confidence=fi,
                reason=f"Fragility {fi:.3f} > {self.FRAGILITY_THRESHOLD}: critical state",
            ))

        # ── 阶段 2: 底仓 → 触发 ────────────────────────────────────────
        if self.phase == self.Phase.BASE_POSITION and len(usdjpy_bars) >= 2:
            ret_5min = (bar.close - usdjpy_bars[-2].close) / usdjpy_bars[-2].close

            # 检测触发：USD/JPY 急跌
            if ret_5min <= self.TRIGGER_JPY_5MIN_PCT:
                self.phase = self.Phase.TRIGGERED
                self._trigger_time = now
                self._best_price = bar.close
                self.log.info(
                    "TRIGGER: USD/JPY 5min ret=%.4f, adding to %d%%",
                    ret_5min, int(self.TRIGGER_SIZE * 100),
                )

                return self._emit(TradeSignal(
                    timestamp=now,
                    strategy=self.name,
                    asset="USD/JPY",
                    direction="short",
                    size_pct=self.TRIGGER_SIZE,
                    entry_price=bar.close,
                    stop_loss=bar.close * 1.010,  # 1% 止损
                    max_hold_minutes=1440,
                    confidence=0.7,
                    reason=f"Carry unwind triggered: 5min drop {ret_5min:.4f}",
                ))

        # ── 阶段 3: 触发 → 雪崩加速 ────────────────────────────────────
        if self.phase == self.Phase.TRIGGERED:
            if self._best_price and bar.close < self._best_price:
                self._best_price = bar.close  # 追踪最佳

            # 检测加速：连续创新低
            if len(usdjpy_bars) >= self.AVALANCHE_ACCEL_BARS:
                is_accelerating = all(
                    usdjpy_bars[-(i+1)].close < usdjpy_bars[-(i+2)].close
                    for i in range(self.AVALANCHE_ACCEL_BARS - 1)
                )
                if is_accelerating:
                    self.phase = self.Phase.AVALANCHE
                    self.log.info("AVALANCHE phase: %d consecutive new lows",
                                  self.AVALANCHE_ACCEL_BARS)

        # ── 阶段 4: 雪崩 → 冷却 ─────────────────────────────────────────
        if self.phase == self.Phase.AVALANCHE:
            if self._best_price and bar.close < self._best_price:
                self._best_price = bar.close

            # 追踪止损：从最佳价格回撤 N%
            if self._best_price:
                trail_stop = self._best_price * (1 + self.TRAIL_STOP_PCT)
                if bar.close > trail_stop:
                    self.phase = self.Phase.COOLING
                    self.log.info(
                        "Avalanche cooling: price %.4f > trail stop %.4f",
                        bar.close, trail_stop,
                    )
                    return self._emit(TradeSignal(
                        timestamp=now,
                        strategy=self.name,
                        asset="USD/JPY",
                        direction="close",
                        size_pct=0.0,  # 平掉 80%
                        entry_price=bar.close,
                        stop_loss=bar.close,
                        confidence=0.6,
                        reason=f"Avalanche ended: retraced from best {self._best_price:.4f}",
                    ))

        # 脆弱性下降 → 回到监控
        if fi < self.FRAGILITY_THRESHOLD * 0.8 and self.phase == self.Phase.BASE_POSITION:
            self.phase = self.Phase.MONITORING
            self.log.info("Fragility dropped to %.3f → back to monitoring", fi)

        return None


# ══════════════════════════════════════════════════════════════════════════════
# E. 央行语义漂移策略 (Central Bank Semantic Drift)
# ══════════════════════════════════════════════════════════════════════════════
#
# 假设：央行措辞的微妙变化领先于政策行动和市场定价 1-3 个月。
#       LLM 可以检测到这种语义漂移。
# 方法：归纳法 (NLP + 央行沟通学)
# LLM角色：核心（语义距离分析）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CBStatement:
    """央行声明记录"""
    date: datetime
    bank: str           # "Fed" / "ECB" / "BoJ" / "BoE"
    topic: str          # "inflation" / "employment" / "policy_path"
    text: str           # 关键句子
    source_type: str    # "statement" / "minutes" / "speech"


@dataclass
class SemanticDrift:
    """语义漂移检测结果"""
    bank: str
    topic: str
    direction: float    # +1 鹰 / -1 鸽
    magnitude: float    # 0.0 - 1.0
    prev_date: datetime
    curr_date: datetime
    reasoning: str = ""


# 信号 → 资产映射
CB_SIGNAL_MAP = {
    ("Fed", "hawkish"):  [("XAU/USD", "short"), ("EUR/USD", "short")],
    ("Fed", "dovish"):   [("XAU/USD", "long"), ("EUR/USD", "long")],
    ("BoJ", "hawkish"):  [("USD/JPY", "short")],
    ("BoJ", "dovish"):   [("USD/JPY", "long")],
    ("ECB", "hawkish"):  [("EUR/USD", "long")],
    ("ECB", "dovish"):   [("EUR/USD", "short")],
    ("BoE", "hawkish"):  [("GBP/USD", "long")],
    ("BoE", "dovish"):   [("GBP/USD", "short")],
}


class CentralBankSemanticDriftStrategy(BaseStrategy):
    """
    策略 E: 检测央行措辞的语义漂移，捕捉市场尚未充分定价的政策转向

    低频信号（月均 4-8 次），作为底仓方向偏见使用。
    """

    DRIFT_MAGNITUDE_THRESHOLD = 0.6   # 漂移幅度阈值
    CONSECUTIVE_SIGNALS = 2            # 连续 N 次同方向才出信号
    POSITION_SIZE = 0.15               # 底仓仓位

    def __init__(self):
        super().__init__("E-CB-SemanticDrift")
        self.client = anthropic.Anthropic()
        self._statement_history: dict[str, list[CBStatement]] = {}  # bank → statements
        self._drift_history: dict[str, list[SemanticDrift]] = {}    # bank → drifts
        self._active_biases: dict[str, str] = {}                    # bank → "hawkish"/"dovish"

    def add_statement(self, stmt: CBStatement):
        """添加新的央行声明到语料库"""
        bank_history = self._statement_history.setdefault(stmt.bank, [])
        bank_history.append(stmt)
        bank_history.sort(key=lambda s: s.date)

    def _detect_drift(self, bank: str, topic: str) -> Optional[SemanticDrift]:
        """
        LLM 对比同一主题前后两次声明，检测语义漂移
        """
        history = self._statement_history.get(bank, [])
        topic_stmts = [s for s in history if s.topic == topic]

        if len(topic_stmts) < 2:
            return None

        prev = topic_stmts[-2]
        curr = topic_stmts[-1]

        prompt = f"""你是央行沟通研究专家。

以下是 {bank} 关于 [{topic}] 的两次表述:

【前次】({prev.date.strftime('%Y-%m-%d')}, {prev.source_type}):
"{prev.text}"

【本次】({curr.date.strftime('%Y-%m-%d')}, {curr.source_type}):
"{curr.text}"

请分析语气变化:

返回严格 JSON:
{{
  "drift_direction": +1.0 (更鹰派) 到 -1.0 (更鸽派),
  "drift_magnitude": 0.0 (无变化) 到 1.0 (重大转向),
  "key_word_shifts": ["word_before → word_after", ...],
  "reasoning": "一句话说明核心变化"
}}"""

        try:
            resp = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(text[start:end])
                return SemanticDrift(
                    bank=bank,
                    topic=topic,
                    direction=float(result.get("drift_direction", 0)),
                    magnitude=float(result.get("drift_magnitude", 0)),
                    prev_date=prev.date,
                    curr_date=curr.date,
                    reasoning=result.get("reasoning", ""),
                )
        except Exception as e:
            self.log.warning("LLM drift detection failed: %s", e)

        return None

    def analyze_new_statement(self, stmt: CBStatement) -> list[TradeSignal]:
        """
        新声明进入 → 对每个话题检测漂移 → 累积一致性 → 生成信号
        """
        self.add_statement(stmt)

        # 对该央行的所有话题做漂移检测
        topics = set(s.topic for s in self._statement_history.get(stmt.bank, []))
        drifts = []
        for topic in topics:
            drift = self._detect_drift(stmt.bank, topic)
            if drift and abs(drift.magnitude) > 0:
                drifts.append(drift)
                bank_drifts = self._drift_history.setdefault(stmt.bank, [])
                bank_drifts.append(drift)
                self.log.info(
                    "Drift detected: %s/%s dir=%.2f mag=%.2f — %s",
                    drift.bank, drift.topic, drift.direction,
                    drift.magnitude, drift.reasoning,
                )

        if not drifts:
            return []

        # 检查是否满足信号条件
        signals = []
        bank = stmt.bank
        bank_drifts = self._drift_history.get(bank, [])

        # 最近 N 次漂移
        recent = bank_drifts[-self.CONSECUTIVE_SIGNALS:]
        if len(recent) < self.CONSECUTIVE_SIGNALS:
            return []

        # 条件 1: 方向一致
        directions = [d.direction for d in recent]
        all_hawkish = all(d > 0 for d in directions)
        all_dovish = all(d < 0 for d in directions)

        if not (all_hawkish or all_dovish):
            return []

        # 条件 2: 平均幅度超阈值
        avg_magnitude = np.mean([d.magnitude for d in recent])
        if avg_magnitude < self.DRIFT_MAGNITUDE_THRESHOLD:
            return []

        # 生成信号
        bias = "hawkish" if all_hawkish else "dovish"
        self._active_biases[bank] = bias

        signal_key = (bank, bias)
        asset_directions = CB_SIGNAL_MAP.get(signal_key, [])

        for asset, direction in asset_directions:
            signals.append(self._emit(TradeSignal(
                timestamp=stmt.date,
                strategy=self.name,
                asset=asset,
                direction=direction,
                size_pct=self.POSITION_SIZE,
                entry_price=0.0,   # 底仓信号，实际入场价由执行层决定
                stop_loss=0.0,     # 宽止损，由执行层根据 ATR 设定
                max_hold_minutes=20160,  # 2 周
                confidence=avg_magnitude,
                reason=f"{bank} semantic drift: {self.CONSECUTIVE_SIGNALS}× "
                       f"consistent {bias} (avg_mag={avg_magnitude:.2f})",
            )))

        return signals

    def on_news(self, news: NewsItem) -> Optional[TradeSignal]:
        """非央行声明的新闻不处理"""
        return None

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> Optional[TradeSignal]:
        """低频策略不在 bar 级别交易"""
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 策略动物园管理器 (Zoo Orchestrator)
# ══════════════════════════════════════════════════════════════════════════════

class StrategyZoo:
    """
    策略组合管理器——并行运行五个策略，汇总信号。

    层次结构:
      底仓层（周度调整）:   E 央行语义漂移
      战略层（日内调整）:   B 避险相对价值 + D 套息脆弱性
      战术层（分钟级）:     A 过度反应回归 + C 新闻流物理学

    资金分配: 底仓 20% | 战略 40% | 战术 40%
    """

    LAYER_BUDGET = {
        "base":      0.20,   # 底仓层 (E)
        "strategic":  0.40,   # 战略层 (B + D)
        "tactical":   0.40,   # 战术层 (A + C)
    }

    STRATEGY_LAYER = {
        "A-Overreaction-Reversion":   "tactical",
        "B-SafeHaven-RelativeValue":  "strategic",
        "C-NewsFlow-Physics":         "tactical",
        "D-CarryTrade-Fragility":     "strategic",
        "E-CB-SemanticDrift":         "base",
    }

    def __init__(self):
        self.strategies: dict[str, BaseStrategy] = {
            "A": OverreactionReversionStrategy(),
            "B": SafeHavenRelativeValueStrategy(),
            "C": NewsFlowPhysicsStrategy(),
            "D": CarryTradeFragilityStrategy(),
            "E": CentralBankSemanticDriftStrategy(),
        }
        self.all_signals: list[TradeSignal] = []
        self.log = logging.getLogger("zoo.orchestrator")

    def inject_headlines(self, headlines: list[str]):
        """注入新闻标题到需要的策略"""
        for s in self.strategies.values():
            s._recent_headlines = headlines

    def on_news(self, news: NewsItem) -> list[TradeSignal]:
        """广播新闻到所有策略"""
        signals = []
        for key, strategy in self.strategies.items():
            sig = strategy.on_news(news)
            if sig:
                signals.append(sig)
        self.all_signals.extend(signals)
        return signals

    def on_bar(self, bar: PriceBar, recent_bars: dict[str, list[PriceBar]]) -> list[TradeSignal]:
        """广播价格到所有策略"""
        signals = []
        for key, strategy in self.strategies.items():
            sig = strategy.on_bar(bar, recent_bars)
            if sig:
                signals.append(sig)
        self.all_signals.extend(signals)
        return signals

    def on_cb_statement(self, stmt: CBStatement) -> list[TradeSignal]:
        """央行声明专用通道"""
        strategy_e: CentralBankSemanticDriftStrategy = self.strategies["E"]
        signals = strategy_e.analyze_new_statement(stmt)
        self.all_signals.extend(signals)
        return signals

    def get_portfolio_view(self) -> dict:
        """获取当前组合视图"""
        layer_usage = {layer: 0.0 for layer in self.LAYER_BUDGET}

        active = []
        for sig in self.all_signals[-20:]:  # 最近 20 个信号
            if sig.direction != "close":
                layer = self.STRATEGY_LAYER.get(sig.strategy, "tactical")
                layer_usage[layer] += sig.size_pct
                active.append({
                    "strategy": sig.strategy,
                    "asset": sig.asset,
                    "direction": sig.direction,
                    "size": sig.size_pct,
                    "layer": layer,
                })

        return {
            "active_signals": active,
            "layer_usage": layer_usage,
            "layer_budget": self.LAYER_BUDGET,
            "total_exposure": sum(layer_usage.values()),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 演示：模拟场景运行
# ══════════════════════════════════════════════════════════════════════════════

def demo_scenario():
    """
    模拟场景：2026 年 4 月某日，伊朗导弹袭击美军基地 → 市场连锁反应

    时间线:
      T+0min  : 路透社 Breaking 快讯
      T+5min  : 黄金暴涨 1.5%，原油涨 3%
      T+10min : 更多新闻涌入，USD/JPY 急跌
      T+30min : 新闻频率开始下降
      T+60min : BoJ 声明"密切关注金融市场稳定"
      T+120min: 市场初步稳定
    """
    zoo = StrategyZoo()
    base_time = datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc)
    recent_bars: dict[str, list[PriceBar]] = {a: [] for a in ALL_ASSETS}

    print("=" * 78)
    print("  策略动物园演示 — 伊朗导弹袭击美军基地模拟场景")
    print("=" * 78)

    # ── T+0: Breaking news ──────────────────────────────────────────────
    t0 = base_time
    print(f"\n{'─'*78}")
    print(f"  T+0 ({t0.strftime('%H:%M')}) 路透社 Breaking:")
    print(f"  'Iran launches missile attack on US military base in Iraq'")
    print(f"{'─'*78}")

    news_t0 = NewsItem(
        timestamp=t0,
        headline="BREAKING: Iran launches missile attack on US military base in Iraq",
        source="Reuters",
        urgency="breaking",
    )
    zoo.inject_headlines([news_t0.headline])
    signals = zoo.on_news(news_t0)
    print(f"  >> 策略信号: {len(signals)} 个")

    # ── T+5min: 价格冲击 ────────────────────────────────────────────────
    t5 = base_time + timedelta(minutes=5)
    print(f"\n{'─'*78}")
    print(f"  T+5min ({t5.strftime('%H:%M')}) 价格冲击:")
    print(f"  XAU: 3200→3248 (+1.5%), Brent: 82→84.5 (+3.0%), USD/JPY: 148→146.5 (-1.0%)")
    print(f"{'─'*78}")

    price_bars_t5 = [
        PriceBar(t5, "XAU/USD", 3200, 3252, 3198, 3248),
        PriceBar(t5, "BRENT", 82.0, 84.8, 81.8, 84.5),
        PriceBar(t5, "USD/JPY", 148.0, 148.2, 146.3, 146.5),
        PriceBar(t5, "USD/CHF", 0.8900, 0.8910, 0.8845, 0.8860),
    ]
    for b in price_bars_t5:
        recent_bars[b.asset].append(b)

    # 策略 D: 注入脆弱性状态（模拟当前处于高脆弱性）
    strategy_d: CarryTradeFragilityStrategy = zoo.strategies["D"]
    strategy_d.update_fragility(
        cftc_jpy_short_percentile=0.92,
        vol_term_ratio=1.15,
        cross_carry_correlation=0.72,
        boj_hawkish_score=2.5,
    )
    fi = strategy_d.compute_fragility_index()
    print(f"  >> 策略 D 脆弱性指数: {fi:.3f} (阈值: {strategy_d.FRAGILITY_THRESHOLD})")

    for b in price_bars_t5:
        sigs = zoo.on_bar(b, recent_bars)
        for s in sigs:
            print(f"  >> 信号: [{s.strategy}] {s.direction.upper()} {s.asset} @ {s.entry_price:.4f}")

    # ── T+10min: 新闻密集涌入 ───────────────────────────────────────────
    t10 = base_time + timedelta(minutes=10)
    print(f"\n{'─'*78}")
    print(f"  T+10min ({t10.strftime('%H:%M')}) 新闻持续涌入（策略 C 新闻流物理学）:")
    print(f"{'─'*78}")

    rapid_news = [
        "US confirms missile strikes on base, casualties reported",
        "Pentagon scrambles fighter jets to Gulf region",
        "Oil prices surge as Hormuz Strait fears mount",
        "Gold hits fresh all-time high above $3,250",
        "Japan PM calls emergency national security meeting",
        "Swiss franc surges as safe-haven demand intensifies",
        "EUR/USD drops as risk-off sentiment grips markets",
        "VIX jumps 25% in early trading",
    ]
    for i, headline in enumerate(rapid_news):
        news = NewsItem(
            timestamp=t10 + timedelta(seconds=i*30),
            headline=headline,
            source="Reuters" if i % 2 == 0 else "Bloomberg",
            urgency="flash" if i < 3 else "headline",
        )
        zoo.on_news(news)

    zoo.inject_headlines([n.headline for n in [news_t0]] + rapid_news)

    # 策略 C 速度计算
    strategy_c: NewsFlowPhysicsStrategy = zoo.strategies["C"]
    v = strategy_c._compute_velocity(t10)
    a = strategy_c._compute_acceleration()
    print(f"  >> 策略 C: 新闻速度 v={v:.2f} 条/分钟, 加速度 a={a:.3f}")

    # 继续价格更新
    t10_bars = [
        PriceBar(t10, "XAU/USD", 3248, 3265, 3245, 3260),
        PriceBar(t10, "USD/JPY", 146.5, 146.8, 145.8, 146.0),
    ]
    for b in t10_bars:
        recent_bars[b.asset].append(b)
        sigs = zoo.on_bar(b, recent_bars)
        for s in sigs:
            print(f"  >> 信号: [{s.strategy}] {s.direction.upper()} {s.asset}")

    # ── T+60min: BoJ 声明 ──────────────────────────────────────────────
    t60 = base_time + timedelta(minutes=60)
    print(f"\n{'─'*78}")
    print(f"  T+60min ({t60.strftime('%H:%M')}) BoJ 声明: '密切关注金融市场稳定'")
    print(f"{'─'*78}")

    boj_news = NewsItem(
        timestamp=t60,
        headline="BoJ says closely watching financial market stability amid geopolitical tensions",
        source="Reuters",
        urgency="headline",
    )
    sigs = zoo.on_news(boj_news)
    print(f"  >> BoJ 鹰派评分更新: {strategy_d.fragility.boj_hawkish_score:.1f}")

    # 策略 E: 模拟央行声明对比
    strategy_e: CentralBankSemanticDriftStrategy = zoo.strategies["E"]

    prev_stmt = CBStatement(
        date=datetime(2026, 3, 15, tzinfo=timezone.utc),
        bank="BoJ",
        topic="policy_path",
        text="We will patiently continue to assess the impact of our policy adjustments.",
        source_type="minutes",
    )
    curr_stmt = CBStatement(
        date=t60,
        bank="BoJ",
        topic="policy_path",
        text="We are closely monitoring market conditions and stand ready to act as necessary to ensure financial stability.",
        source_type="statement",
    )
    strategy_e.add_statement(prev_stmt)
    print("  >> 策略 E: 对比 BoJ 3月 vs 4月表述（需 LLM 调用）...")

    # ── 最终组合视图 ─────────────────────────────────────────────────────
    print(f"\n{'═'*78}")
    print(f"  策略组合汇总")
    print(f"{'═'*78}")

    view = zoo.get_portfolio_view()
    print(f"  活跃信号数: {len(view['active_signals'])}")
    print(f"  总敞口: {view['total_exposure']:.1%}")

    for layer, budget in view["layer_budget"].items():
        usage = view["layer_usage"].get(layer, 0)
        print(f"  {layer:>12s}: 已用 {usage:.1%} / 预算 {budget:.1%}")

    print(f"\n  活跃持仓:")
    for sig in view["active_signals"]:
        print(f"    [{sig['strategy']:30s}] {sig['direction']:5s} {sig['asset']:10s} "
              f"size={sig['size']:.0%} ({sig['layer']})")

    print(f"\n{'═'*78}")
    print(f"  演示结束 — 五策略并行运行，独立风控")
    print(f"{'═'*78}")


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    demo_scenario()
