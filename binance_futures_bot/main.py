#!/usr/bin/env python3
"""幣安 USDT-M 合約自動交易系統 / Binance USDT-M Futures auto-trading bot.

Usage:
    python main.py run                          # start trading (respects DRY_RUN / USE_TESTNET)
    python main.py backtest --days 60           # backtest on real history (public API)
    python main.py backtest --csv data.csv      # backtest on a CSV of klines
    python main.py backtest --synthetic         # offline backtest on generated data
    python main.py status                       # show balance and position
    python main.py close                        # emergency: cancel orders + close position
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from bot.backtest import fetch_history, load_csv, run_backtest, synthetic_candles
from bot.client import BinanceFuturesClient
from bot.config import Config
from bot.risk import SymbolFilters
from bot.trader import Trader


def setup_logging(verbose: bool) -> None:
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler("logs/bot.log", encoding="utf-8")],
    )


def confirm_mainnet(cfg: Config) -> None:
    if not cfg.dry_run and not cfg.use_testnet:
        print("\n⚠️  你即將在【正式網】使用【真實資金】下單！")
        print("⚠️  You are about to trade REAL MONEY on Binance mainnet.")
        if input("輸入 YES 繼續 / type YES to continue: ").strip() != "YES":
            sys.exit("Aborted.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Binance USDT-M futures auto-trading bot")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--env", default=".env", help="path to .env file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="start the trading loop")
    r.add_argument("--poll", type=int, default=10, help="seconds between checks")

    b = sub.add_parser("backtest", help="backtest the strategy")
    src = b.add_mutually_exclusive_group()
    src.add_argument("--days", type=int, default=60, help="days of history to download")
    src.add_argument("--csv", help="CSV file of klines")
    src.add_argument("--synthetic", action="store_true", help="use generated data (offline)")
    b.add_argument("--trades", action="store_true", help="print every trade")
    b.add_argument("--strategy", choices=["macd_rsi", "ema_cross"], help="override STRATEGY")

    sub.add_parser("status", help="show balance / position")
    sub.add_parser("close", help="cancel all orders and close the position")

    args = ap.parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("main")

    if args.cmd == "backtest":
        # Backtests never need keys or send orders.
        from bot.config import load_dotenv
        load_dotenv(args.env)
        import os
        os.environ["DRY_RUN"] = "true"
        if args.strategy:
            os.environ["STRATEGY"] = args.strategy
    cfg = Config.from_env(args.env)
    client = BinanceFuturesClient(cfg.api_key, cfg.api_secret, cfg.base_url)
    if args.cmd in ("status", "close") and not (cfg.api_key and cfg.api_secret):
        sys.exit("BINANCE_API_KEY / BINANCE_API_SECRET are required for this command (.env)")

    if args.cmd == "run":
        confirm_mainnet(cfg)
        try:
            Trader(cfg, client).run(args.poll)
        except KeyboardInterrupt:
            log.info("Stopped by user. Open positions (if any) keep their exchange SL/TP orders.")

    elif args.cmd == "backtest":
        logging.getLogger("bot.broker").setLevel(logging.WARNING)
        filters = SymbolFilters()
        if args.synthetic:
            candles = synthetic_candles()
        elif args.csv:
            candles = load_csv(args.csv)
        else:
            # always use mainnet market data for backtests
            data_client = BinanceFuturesClient("", "", "https://fapi.binance.com")
            filters = SymbolFilters.from_exchange_info(data_client.symbol_info(cfg.symbol))
            candles = fetch_history(data_client, cfg.symbol, cfg.interval, args.days)
        log.info("Backtesting %d candles with strategy=%s...", len(candles), cfg.strategy)
        res = run_backtest(cfg, candles, filters)
        if args.trades:
            for t in res.trades:
                print(f"{t.side:5} entry={t.entry:.2f} exit={t.exit:.2f} pnl={t.pnl:+.2f} ({t.reason})")
        print(res.summary())

    elif args.cmd == "status":
        client.sync_time()
        bal = client.usdt_balance()
        print(f"USDT wallet={bal['wallet']:.2f} available={bal['available']:.2f}")
        for p in client.position_risk(cfg.symbol):
            if float(p["positionAmt"]) != 0:
                print(f"{p['symbol']} amt={p['positionAmt']} entry={p['entryPrice']} "
                      f"uPnL={p['unRealizedProfit']} liq={p.get('liquidationPrice')}")

    elif args.cmd == "close":
        client.sync_time()
        from bot.broker import LiveBroker
        filters = SymbolFilters.from_exchange_info(client.symbol_info(cfg.symbol))
        LiveBroker(client, cfg.symbol, filters).close(0, "manual_close")
        print("All orders cancelled and position closed.")


if __name__ == "__main__":
    main()
