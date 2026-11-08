"""Position sizing, exchange-filter rounding and daily loss guard."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


@dataclass
class SymbolFilters:
    step_size: Decimal = Decimal("0.001")
    min_qty: Decimal = Decimal("0.001")
    tick_size: Decimal = Decimal("0.1")
    min_notional: Decimal = Decimal("5")

    @classmethod
    def from_exchange_info(cls, symbol_info: dict) -> "SymbolFilters":
        f = cls()
        for flt in symbol_info.get("filters", []):
            t = flt.get("filterType")
            if t == "LOT_SIZE":
                f.step_size = Decimal(flt["stepSize"])
                f.min_qty = Decimal(flt["minQty"])
            elif t == "PRICE_FILTER":
                f.tick_size = Decimal(flt["tickSize"])
            elif t == "MIN_NOTIONAL":
                f.min_notional = Decimal(flt.get("notional", flt.get("minNotional", "5")))
        return f

    def round_qty(self, qty: float) -> Decimal:
        q = Decimal(str(qty))
        return (q / self.step_size).to_integral_value(rounding=ROUND_DOWN) * self.step_size

    def round_price(self, price: float) -> Decimal:
        p = Decimal(str(price))
        return (p / self.tick_size).to_integral_value(rounding=ROUND_HALF_UP) * self.tick_size


def position_size(
    balance: float,
    entry: float,
    stop_loss: float,
    risk_pct: float,
    leverage: int,
    max_position_fraction: float,
    filters: SymbolFilters,
) -> Decimal:
    """Quantity so that hitting the stop loses ~risk_pct% of balance.

    Also capped so notional <= balance * leverage * max_position_fraction.
    Returns Decimal(0) if the resulting order would be below exchange minimums.
    """
    stop_dist = abs(entry - stop_loss)
    if balance <= 0 or entry <= 0 or stop_dist <= 0:
        return Decimal(0)
    risk_amount = balance * risk_pct / 100.0
    qty_by_risk = risk_amount / stop_dist
    qty_by_cap = balance * leverage * max_position_fraction / entry
    qty = filters.round_qty(min(qty_by_risk, qty_by_cap))
    if qty < filters.min_qty or qty * Decimal(str(entry)) < filters.min_notional:
        return Decimal(0)
    return qty


class DailyLossGuard:
    """Blocks new entries once realised loss for the UTC day exceeds a limit."""

    def __init__(self, max_daily_loss_pct: float):
        self.max_pct = max_daily_loss_pct
        self.day: dt.date | None = None
        self.start_balance = 0.0

    def update(self, balance: float, today: dt.date | None = None) -> None:
        today = today or dt.datetime.now(dt.timezone.utc).date()
        if self.day != today:
            self.day = today
            self.start_balance = balance

    def can_trade(self, balance: float) -> bool:
        if self.start_balance <= 0:
            return True
        loss_pct = (self.start_balance - balance) / self.start_balance * 100
        return loss_pct < self.max_pct
