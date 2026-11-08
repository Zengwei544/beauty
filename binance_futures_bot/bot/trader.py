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
from .text import side as zh_side

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
        mode = "測試網" if cfg.use_testnet else "正式網（真實資金）"
        strat = {"macd_rsi": "MACD + RSI", "ema_cross": "EMA 交叉"}[cfg.strategy]
        margin = "逐倉" if cfg.margin_type == "ISOLATED" else "全倉"
        log.info("啟動機器人：%s %s ｜策略=%s ｜%s ｜%s ｜槓桿 %d 倍 %s",
                 cfg.symbol, cfg.interval, strat, mode, "紙上交易（不下單）" if cfg.dry_run else "真實下單",
                 cfg.leverage, margin)
        self.client.sync_time()
        self.filters = SymbolFilters.from_exchange_info(self.client.symbol_info(cfg.symbol))
        f = self.filters
        log.info("交易規則：數量步長=%s 最小數量=%s 價格精度=%s 最小名目價值=%s",
                 f.step_size, f.min_qty, f.tick_size, f.min_notional)

        if cfg.dry_run:
            self.broker = PaperBroker(cfg.paper_balance, self.filters)
            return

        if self.client.is_hedge_mode():
            raise RuntimeError("帳戶目前是「雙向持倉」模式，請到幣安合約「偏好設定 → 持倉模式」"
                               "改成「單向持倉」後再啟動。")
        self.client.set_margin_type(cfg.symbol, cfg.margin_type)
        self.client.set_leverage(cfg.symbol, cfg.leverage)
        self.broker = LiveBroker(self.client, cfg.symbol, self.filters)
        pos = self.broker.get_position()
        if pos:
            log.warning("偵測到既有持倉：%s %s @ %s。機器人會在下個訊號時接手，請確認它已有止損單。",
                        zh_side(pos.side), pos.qty, pos.entry)

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
            log.info("已同步最新 K 線，等待下一根 K 線收盤…")
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
        log.info("K 線收盤價=%.4f ｜餘額=%.2f ｜持倉=%s",
                 last.close, balance, f"{zh_side(pos.side)} {pos.qty} @ {pos.entry}" if pos else "無")

        signal = self.strategy.evaluate(candles)
        if not signal:
            return
        log.info("訊號 %s：%s", zh_side(signal.side), signal.reason)

        if pos and pos.side == signal.side:
            log.info("已經是%s持倉，忽略此訊號", zh_side(pos.side))
            return
        if pos:
            broker.close(last.close, "reverse_signal", last.close_time)
            balance = broker.get_balance()

        if not self.guard.can_trade(balance):
            log.warning("已達單日虧損上限（%.1f%%），今天不再開新倉", cfg.max_daily_loss_pct)
            return

        qty = position_size(balance, signal.entry, signal.stop_loss, cfg.risk_per_trade_pct,
                            cfg.leverage, cfg.max_position_fraction, self.filters)
        if qty <= 0:
            log.warning("計算出的倉位低於交易所最小下單量，略過（餘額=%.2f）", balance)
            return
        broker.open(signal, qty, last.close, last.close_time)

    def run(self, poll_seconds: int = 10) -> None:
        self.setup()
        log.info("運行中，按 Ctrl+C 停止。")
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                log.error("交易迴圈發生錯誤（稍後重試）：%s", e)
                log.debug("詳細錯誤", exc_info=True)
            time.sleep(poll_seconds)
