"""EMA-crossover trend strategy with an RSI filter and ATR-based stops.

Rules (evaluated only on CLOSED candles):
  * LONG  when fast EMA crosses above slow EMA and RSI > 50
  * SHORT when fast EMA crosses below slow EMA and RSI < 50
  * Stop loss   = entry -/+ ATR * SL_ATR_MULT
  * Take profit = entry +/- ATR * TP_ATR_MULT
  * An opposite signal closes the open position and reverses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .indicators import atr, ema, rsi


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
            return Signal(
                side="LONG",
                entry=price,
                stop_loss=price - a1 * self.cfg.sl_atr_mult,
                take_profit=price + a1 * self.cfg.tp_atr_mult,
                atr=a1,
                reason=f"EMA{self.cfg.ema_fast} crossed above EMA{self.cfg.ema_slow}, RSI={r1:.1f}",
            )
        if crossed_down and r1 < 50:
            return Signal(
                side="SHORT",
                entry=price,
                stop_loss=price + a1 * self.cfg.sl_atr_mult,
                take_profit=price - a1 * self.cfg.tp_atr_mult,
                atr=a1,
                reason=f"EMA{self.cfg.ema_fast} crossed below EMA{self.cfg.ema_slow}, RSI={r1:.1f}",
            )
        return None
