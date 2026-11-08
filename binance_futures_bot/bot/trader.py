"""Main trading loop: polls closed candles, runs the strategy, manages orders."""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Union

from .broker import LiveBroker, PaperBroker
from .client import BinanceFuturesClient
from .config import Config
from .risk import DailyLossGuard, SymbolFilters, position_size
from .strategy import Candle, make_strategy

log = logging.getLogger(__name__)

KLINE_LIMIT = 300


def parse_klines(raw: List[list]) -> List[Candle]:
    return [Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                   float(k[5]), int(k[6])) for k in raw]


class Trader:
    def __init__(self, cfg: Config, client: Optional[BinanceFuturesClient] = None):
        self.cfg = cfg
        self.client = client or BinanceFuturesClient(cfg.api_key, cfg.api_secret, cfg.base_url)
        self.strategy = make_strategy(cfg)
        self.guard = DailyLossGuard(cfg.max_daily_loss_pct)
        self.broker: Union[PaperBroker, LiveBroker, None] = None
        self.filters = SymbolFilters()
        self.last_candle_time: Optional[int] = None

    # ----------------------------------------------------------------- setup
    def setup(self) -> None:
        cfg = self.cfg
        mode = "TESTNET" if cfg.use_testnet else "MAINNET (REAL MONEY)"
        log.info("Starting bot: %s %s | strategy=%s | %s | %s | leverage=%dx %s",
                 cfg.symbol, cfg.interval, cfg.strategy, mode, "DRY_RUN" if cfg.dry_run else "LIVE ORDERS",
                 cfg.leverage, cfg.margin_type)
        self.client.sync_time()
        self.filters = SymbolFilters.from_exchange_info(self.client.symbol_info(cfg.symbol))
        log.info("Filters: %s", self.filters)

        if cfg.dry_run:
            self.broker = PaperBroker(cfg.paper_balance, self.filters)
            return

        if self.client.is_hedge_mode():
            raise RuntimeError("Account is in Hedge Mode. Switch to One-way Mode in Binance "
                               "Futures settings (Preferences -> Position Mode).")
        self.client.set_margin_type(cfg.symbol, cfg.margin_type)
        self.client.set_leverage(cfg.symbol, cfg.leverage)
        self.broker = LiveBroker(self.client, cfg.symbol, self.filters)
        pos = self.broker.get_position()
        if pos:
            log.warning("Existing position detected: %s. The bot will manage it on the next signal; "
                        "make sure it has a stop loss.", pos)

    # ------------------------------------------------------------------ loop
    def closed_candles(self) -> List[Candle]:
        candles = parse_klines(self.client.klines(self.cfg.symbol, self.cfg.interval, KLINE_LIMIT))
        now = int(time.time() * 1000) + self.client._time_offset
        return [c for c in candles if c.close_time < now]

    def step(self) -> None:
        candles = self.closed_candles()
        if not candles:
            return
        last = candles[-1]
        if self.last_candle_time is None:
            # Don't act on a candle that closed before the bot started.
            self.last_candle_time = last.open_time
            log.info("Synced to candle %d; waiting for the next close...", last.open_time)
            return
        if last.open_time <= self.last_candle_time:
            return
        self.last_candle_time = last.open_time
        self.on_closed_candle(candles)

    def on_closed_candle(self, candles: List[Candle]) -> None:
        cfg, broker = self.cfg, self.broker
        last = candles[-1]
        broker.on_candle(last)

        balance = broker.get_balance()
        self.guard.update(balance)
        pos = broker.get_position()
        log.info("Candle close=%.4f | balance=%.2f | position=%s",
                 last.close, balance, f"{pos.side} {pos.qty} @ {pos.entry}" if pos else "none")

        signal = self.strategy.evaluate(candles)
        if not signal:
            return
        log.info("Signal %s: %s", signal.side, signal.reason)

        if pos and pos.side == signal.side:
            log.info("Already %s, ignoring signal", pos.side)
            return
        if pos:
            broker.close(last.close, "reverse_signal", last.close_time)
            balance = broker.get_balance()

        if not self.guard.can_trade(balance):
            log.warning("Daily loss limit (%.1f%%) reached - no new entries today", cfg.max_daily_loss_pct)
            return

        qty = position_size(balance, signal.entry, signal.stop_loss, cfg.risk_per_trade_pct,
                            cfg.leverage, cfg.max_position_fraction, self.filters)
        if qty <= 0:
            log.warning("Position size below exchange minimum, skipping (balance=%.2f)", balance)
            return
        broker.open(signal, qty, last.close, last.close_time)

    def run(self, poll_seconds: int = 10) -> None:
        self.setup()
        log.info("Running. Press Ctrl+C to stop.")
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("Error in trading loop (will retry)")
            time.sleep(poll_seconds)
