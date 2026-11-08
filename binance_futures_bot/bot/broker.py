"""Brokers: PaperBroker (local simulation) and LiveBroker (real Binance orders)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from .client import BinanceFuturesClient
from .risk import SymbolFilters
from .strategy import Candle, Signal
from .text import reason as zh_reason, side as zh_side

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
        log.info("【模擬】開倉 %s 數量=%s 價格=%.4f 止損=%.4f 止盈=%.4f", zh_side(signal.side), qty, price,
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
        log.info("【模擬】平倉 %s 價格=%.4f（%s）損益=%.2f 餘額=%.2f",
                 zh_side(p.side), price, zh_reason(reason), trade.pnl, self.balance)
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
        log.info("【實盤】開倉 %s 數量=%s 成交均價=%.4f 訂單編號=%s",
                 zh_side(signal.side), qty, fill, order.get("orderId"))

        # Re-anchor SL/TP to the real fill price, keeping the same distances.
        sl = fill - (signal.entry - signal.stop_loss)
        tp = fill + (signal.take_profit - signal.entry)
        sl_s, tp_s = str(self.filters.round_price(sl)), str(self.filters.round_price(tp))
        try:
            self.client.close_position_stop(self.symbol, exit_side, "STOP_MARKET", sl_s)
            self.client.close_position_stop(self.symbol, exit_side, "TAKE_PROFIT_MARKET", tp_s)
            log.info("【實盤】已掛止損單=%s 止盈單=%s", sl_s, tp_s)
        except Exception as e:
            log.error("止損/止盈單掛單失敗：%s → 為了安全立即平倉", e)
            log.debug("詳細錯誤", exc_info=True)
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
        log.info("【實盤】平倉 %s 數量=%s（%s）訂單編號=%s",
                 zh_side(pos.side), qty, zh_reason(reason), order.get("orderId"))

    def on_candle(self, c: Candle) -> None:
        # SL/TP live on the exchange; nothing to simulate.
        return None
