"""Brokers: PaperBroker (local simulation) and LiveBroker (real Binance orders)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from .client import BinanceFuturesClient
from .risk import SymbolFilters
from .strategy import Candle, Signal

log = logging.getLogger(__name__)

TAKER_FEE = 0.0005  # 0.05% per side (default VIP0 taker fee)


@dataclass
class Position:
    side: str          # "LONG" / "SHORT"
    qty: float
    entry: float
    stop_loss: float = 0.0
    take_profit: float = 0.0


@dataclass
class Trade:
    side: str
    qty: float
    entry: float
    exit: float
    pnl: float
    reason: str
    entry_time: int = 0
    exit_time: int = 0


class PaperBroker:
    """Simulates fills locally. Used for DRY_RUN and backtesting."""

    def __init__(self, balance: float, filters: Optional[SymbolFilters] = None, fee: float = TAKER_FEE):
        self.balance = balance
        self.filters = filters or SymbolFilters()
        self.fee = fee
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self._entry_time = 0

    def get_balance(self) -> float:
        return self.balance

    def get_position(self) -> Optional[Position]:
        return self.position

    def open(self, signal: Signal, qty: Decimal, price: float, ts: int = 0) -> None:
        q = float(qty)
        self.balance -= q * price * self.fee
        # Re-anchor SL/TP to the actual fill price, keeping the same distances.
        shift = price - signal.entry
        self.position = Position(signal.side, q, price,
                                 signal.stop_loss + shift, signal.take_profit + shift)
        self._entry_time = ts
        log.info("[PAPER] OPEN %s qty=%s @ %.4f SL=%.4f TP=%.4f", signal.side, qty, price,
                 self.position.stop_loss, self.position.take_profit)

    def close(self, price: float, reason: str, ts: int = 0) -> Optional[Trade]:
        p = self.position
        if not p:
            return None
        direction = 1 if p.side == "LONG" else -1
        gross = (price - p.entry) * p.qty * direction
        exit_fee = p.qty * price * self.fee
        entry_fee = p.qty * p.entry * self.fee   # already deducted at open
        self.balance += gross - exit_fee
        trade = Trade(p.side, p.qty, p.entry, price, gross - exit_fee - entry_fee,
                      reason, self._entry_time, ts)
        self.trades.append(trade)
        self.position = None
        log.info("[PAPER] CLOSE %s @ %.4f (%s) pnl=%.2f balance=%.2f",
                 p.side, price, reason, trade.pnl, self.balance)
        return trade

    def on_candle(self, c: Candle) -> Optional[Trade]:
        """Check whether SL/TP was touched within this candle (SL assumed first if both)."""
        p = self.position
        if not p:
            return None
        if p.side == "LONG":
            if c.low <= p.stop_loss:
                return self.close(min(p.stop_loss, c.open), "stop_loss", c.close_time)
            if c.high >= p.take_profit:
                return self.close(max(p.take_profit, c.open), "take_profit", c.close_time)
        else:
            if c.high >= p.stop_loss:
                return self.close(max(p.stop_loss, c.open), "stop_loss", c.close_time)
            if c.low <= p.take_profit:
                return self.close(min(p.take_profit, c.open), "take_profit", c.close_time)
        return None


class LiveBroker:
    """Sends real orders to Binance (testnet or mainnet). One-way position mode only."""

    def __init__(self, client: BinanceFuturesClient, symbol: str, filters: SymbolFilters):
        self.client = client
        self.symbol = symbol
        self.filters = filters

    def get_balance(self) -> float:
        return self.client.usdt_balance()["wallet"]

    def get_position(self) -> Optional[Position]:
        for p in self.client.position_risk(self.symbol):
            if p.get("positionSide", "BOTH") != "BOTH":
                continue
            amt = float(p["positionAmt"])
            if amt != 0:
                return Position("LONG" if amt > 0 else "SHORT", abs(amt), float(p["entryPrice"]))
        return None

    def open(self, signal: Signal, qty: Decimal, price: float, ts: int = 0) -> None:
        side = "BUY" if signal.side == "LONG" else "SELL"
        exit_side = "SELL" if side == "BUY" else "BUY"
        self.client.cancel_all(self.symbol)
        order = self.client.market_order(self.symbol, side, str(qty))
        fill = float(order.get("avgPrice") or price)
        log.info("[LIVE] OPEN %s qty=%s avg=%.4f orderId=%s", signal.side, qty, fill, order.get("orderId"))

        # Re-anchor SL/TP to the real fill price, keeping the same distances.
        sl = fill - (signal.entry - signal.stop_loss)
        tp = fill + (signal.take_profit - signal.entry)
        sl_s, tp_s = str(self.filters.round_price(sl)), str(self.filters.round_price(tp))
        try:
            self.client.close_position_stop(self.symbol, exit_side, "STOP_MARKET", sl_s)
            self.client.close_position_stop(self.symbol, exit_side, "TAKE_PROFIT_MARKET", tp_s)
            log.info("[LIVE] Protective orders placed SL=%s TP=%s", sl_s, tp_s)
        except Exception:
            log.exception("Failed to place SL/TP -> closing position for safety")
            self.close(price, "protection_failed")
            raise

    def close(self, price: float, reason: str, ts: int = 0) -> None:
        pos = self.get_position()
        self.client.cancel_all(self.symbol)
        if not pos:
            return
        side = "SELL" if pos.side == "LONG" else "BUY"
        qty = self.filters.round_qty(pos.qty)
        order = self.client.market_order(self.symbol, side, str(qty), reduce_only=True)
        log.info("[LIVE] CLOSE %s qty=%s (%s) orderId=%s", pos.side, qty, reason, order.get("orderId"))

    def on_candle(self, c: Candle) -> None:
        # SL/TP live on the exchange; nothing to simulate.
        return None
