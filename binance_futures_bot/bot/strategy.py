"""Trading strategies. All are evaluated only on CLOSED candles.

MacdRsiStrategy (default, STRATEGY=macd_rsi):
  * LONG  when MACD line crosses above its signal line and
          RSI_LONG_MIN < RSI < RSI_LONG_MAX   (momentum up, not overbought)
  * SHORT when MACD line crosses below its signal line and
          RSI_SHORT_MIN < RSI < RSI_SHORT_MAX (momentum down, not oversold)

EmaCrossStrategy (STRATEGY=ema_cross):
  * LONG / SHORT on fast/slow EMA cross with RSI above / below 50

Common to both:
  * Stop loss   = entry -/+ ATR * SL_ATR_MULT
  * Take profit = entry +/- ATR * TP_ATR_MULT
  * An opposite signal closes the open position and reverses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .indicators import atr, ema, macd, rsi


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass
class Signal:
    side: str            # "LONG" or "SHORT"
    entry: float         # reference price (close of signal candle)
    stop_loss: float
    take_profit: float
    atr: float
    reason: str


def _make_signal(cfg: Config, side: str, price: float, a: float, reason: str) -> Signal:
    d = 1 if side == "LONG" else -1
    return Signal(side=side, entry=price,
                  stop_loss=price - d * a * cfg.sl_atr_mult,
                  take_profit=price + d * a * cfg.tp_atr_mult,
                  atr=a, reason=reason)


class MacdRsiStrategy:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    @property
    def warmup(self) -> int:
        return max(self.cfg.macd_slow + self.cfg.macd_signal,
                   self.cfg.rsi_period, self.cfg.atr_period) + 2

    def evaluate(self, candles: List[Candle]) -> Optional[Signal]:
        cfg = self.cfg
        if len(candles) < self.warmup:
            return None
        closes = [c.close for c in candles]
        line, sig, hist = macd(closes, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        r = rsi(closes, cfg.rsi_period)[-1]
        a = atr([c.high for c in candles], [c.low for c in candles], closes, cfg.atr_period)[-1]
        h0, h1 = hist[-2], hist[-1]
        if None in (h0, h1, r, a) or a <= 0:
            return None

        price = closes[-1]
        info = f"MACD={line[-1]:.4f} signal={sig[-1]:.4f} RSI={r:.1f}"
        # histogram changing sign == MACD line crossing its signal line
        if h0 <= 0 < h1 and cfg.rsi_long_min < r < cfg.rsi_long_max:
            return _make_signal(cfg, "LONG", price, a, "MACD crossed above signal, " + info)
        if h0 >= 0 > h1 and cfg.rsi_short_min < r < cfg.rsi_short_max:
            return _make_signal(cfg, "SHORT", price, a, "MACD crossed below signal, " + info)
        return None


class EmaCrossStrategy:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    @property
    def warmup(self) -> int:
        return max(self.cfg.ema_slow, self.cfg.rsi_period, self.cfg.atr_period) + 2

    def evaluate(self, candles: List[Candle]) -> Optional[Signal]:
        """Return a signal for the last candle in `candles`, or None."""
        if len(candles) < self.warmup:
            return None
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        fast = ema(closes, self.cfg.ema_fast)
        slow = ema(closes, self.cfg.ema_slow)
        r = rsi(closes, self.cfg.rsi_period)
        a = atr(highs, lows, closes, self.cfg.atr_period)

        f0, f1, s0, s1 = fast[-2], fast[-1], slow[-2], slow[-1]
        r1, a1 = r[-1], a[-1]
        if None in (f0, f1, s0, s1, r1, a1) or a1 <= 0:
            return None

        price = closes[-1]
        crossed_up = f0 <= s0 and f1 > s1
        crossed_down = f0 >= s0 and f1 < s1

        if crossed_up and r1 > 50:
            return _make_signal(self.cfg, "LONG", price, a1,
                                f"EMA{self.cfg.ema_fast} crossed above EMA{self.cfg.ema_slow}, RSI={r1:.1f}")
        if crossed_down and r1 < 50:
            return _make_signal(self.cfg, "SHORT", price, a1,
                                f"EMA{self.cfg.ema_fast} crossed below EMA{self.cfg.ema_slow}, RSI={r1:.1f}")
        return None


STRATEGIES = {"macd_rsi": MacdRsiStrategy, "ema_cross": EmaCrossStrategy}


def make_strategy(cfg: Config):
    return STRATEGIES[cfg.strategy](cfg)
