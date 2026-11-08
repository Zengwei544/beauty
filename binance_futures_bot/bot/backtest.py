"""Simple candle-by-candle backtester that reuses the live strategy and risk code."""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from typing import List

from .broker import PaperBroker, Trade
from .config import Config
from .risk import SymbolFilters, position_size
from .strategy import Candle, make_strategy

WINDOW = 300  # same number of candles the live bot sees


@dataclass
class BacktestResult:
    start_balance: float
    end_balance: float
    trades: List[Trade]
    max_drawdown_pct: float

    @property
    def return_pct(self) -> float:
        return (self.end_balance / self.start_balance - 1) * 100

    @property
    def win_rate(self) -> float:
        return 100 * sum(t.pnl > 0 for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        win = sum(t.pnl for t in self.trades if t.pnl > 0)
        loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        return win / loss if loss else float("inf") if win else 0.0

    def summary(self) -> str:
        return "\n".join([
            "=" * 32,
            f" 起始資金：{self.start_balance:,.2f} USDT",
            f" 最終資金：{self.end_balance:,.2f} USDT",
            f" 報酬率　：{self.return_pct:+.2f}%",
            f" 交易次數：{len(self.trades)}",
            f" 勝率　　：{self.win_rate:.1f}%",
            f" 獲利因子：{self.profit_factor:.2f}",
            f" 最大回撤：{self.max_drawdown_pct:.2f}%",
            "=" * 32,
        ])


def run_backtest(cfg: Config, candles: List[Candle], filters: SymbolFilters | None = None) -> BacktestResult:
    filters = filters or SymbolFilters()
    strategy = make_strategy(cfg)
    broker = PaperBroker(cfg.paper_balance, filters)
    peak, max_dd = cfg.paper_balance, 0.0

    for i in range(len(candles)):
        c = candles[i]
        broker.on_candle(c)

        # mark-to-market equity for drawdown
        pos = broker.position
        equity = broker.balance
        if pos:
            equity += (c.close - pos.entry) * pos.qty * (1 if pos.side == "LONG" else -1)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100 if peak > 0 else 0)

        if i + 1 >= len(candles):
            break
        signal = strategy.evaluate(candles[max(0, i + 1 - WINDOW): i + 1])
        if not signal:
            continue
        nxt = candles[i + 1]  # execute at next candle's open (no look-ahead)
        if pos and pos.side == signal.side:
            continue
        if pos:
            broker.close(nxt.open, "reverse_signal", nxt.open_time)
        qty = position_size(broker.balance, signal.entry, signal.stop_loss, cfg.risk_per_trade_pct,
                            cfg.leverage, cfg.max_position_fraction, filters)
        if qty > 0:
            broker.open(signal, qty, nxt.open, nxt.open_time)

    if broker.position:
        broker.close(candles[-1].close, "end_of_data", candles[-1].close_time)
    return BacktestResult(cfg.paper_balance, broker.balance, broker.trades, max_dd)


# ------------------------------------------------------------------ data
def load_csv(path: str) -> List[Candle]:
    """CSV in Binance kline format (open_time, open, high, low, close, volume, close_time, ...)."""
    out: List[Candle] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip().isdigit():
                continue  # skip header
            out.append(Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]),
                              float(row[4]), float(row[5]), int(row[6])))
    return out


def fetch_history(client, symbol: str, interval: str, days: int) -> List[Candle]:
    from .trader import parse_klines
    import time
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    out: List[Candle] = []
    while start < end:
        batch = parse_klines(client.klines(symbol, interval, 1500, start_time=start))
        if not batch:
            break
        out.extend(batch)
        start = batch[-1].close_time + 1
        if len(batch) < 1500:
            break
    return out


def synthetic_candles(n: int = 3000, start_price: float = 60000.0, seed: int = 42,
                      interval_ms: int = 900_000) -> List[Candle]:
    """Random-walk candles with alternating trend regimes, for offline testing."""
    rng = random.Random(seed)
    price, t, drift = start_price, 1_700_000_000_000, 0.0
    out: List[Candle] = []
    for i in range(n):
        if i % 200 == 0:
            drift = rng.choice([-1, 1]) * rng.uniform(0.0002, 0.0012)
        o = price
        ret = drift + rng.gauss(0, 0.004)
        c = o * math.exp(ret)
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.002)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.002)))
        out.append(Candle(t, o, h, l, c, rng.uniform(10, 100), t + interval_ms - 1))
        price, t = c, t + interval_ms
    return out
