#!/usr/bin/env python3
"""幣安 U 本位合約自動交易系統。

用法：
    python main.py run                          # 開始交易（依 DRY_RUN / USE_TESTNET 設定）
    python main.py backtest --days 60           # 用真實歷史行情回測
    python main.py backtest --csv data.csv      # 用 CSV 的 K 線回測
    python main.py backtest --synthetic         # 用模擬資料離線回測
    python main.py status                       # 查看餘額與持倉
    python main.py close                        # 緊急：取消掛單並平倉
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
from bot.text import chinese_argparse, chinese_log_levels, reason as zh_reason, side as zh_side
from bot.trader import Trader


def setup_logging(verbose: bool) -> None:
    chinese_log_levels()
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s【%(levelname)s】%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler("logs/bot.log", encoding="utf-8")],
    )


def confirm_mainnet(cfg: Config) -> None:
    if not cfg.dry_run and not cfg.use_testnet:
        print("\n⚠️  你即將在【正式網】使用【真實資金】下單！")
        if input("確定要繼續請輸入「確定」：").strip() != "確定":
            sys.exit("已取消。")


def main() -> None:
    chinese_argparse()
    ap = argparse.ArgumentParser(description="幣安 U 本位合約自動交易系統")
    ap.add_argument("-v", "--verbose", action="store_true", help="顯示除錯訊息")
    ap.add_argument("--env", default=".env", metavar="路徑", help=".env 設定檔路徑（預設 .env）")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="指令")

    r = sub.add_parser("run", help="開始自動交易", description="開始自動交易")
    r.add_argument("--poll", type=int, default=10, metavar="秒", help="每幾秒檢查一次（預設 10）")

    b = sub.add_parser("backtest", help="回測策略", description="回測策略")
    src = b.add_mutually_exclusive_group()
    src.add_argument("--days", type=int, default=60, metavar="天數", help="下載最近幾天的行情（預設 60）")
    src.add_argument("--csv", metavar="檔案", help="使用 CSV 格式的 K 線檔案")
    src.add_argument("--synthetic", action="store_true", help="使用模擬資料（不需網路）")
    b.add_argument("--trades", action="store_true", help="列出每一筆交易")
    b.add_argument("--strategy", choices=["macd_rsi", "ema_cross"],
                   help="指定策略：macd_rsi（MACD + RSI）或 ema_cross（EMA 交叉）")

    sub.add_parser("status", help="查看餘額與持倉", description="查看餘額與持倉")
    sub.add_parser("close", help="緊急：取消所有掛單並市價平倉", description="緊急：取消所有掛單並市價平倉")

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
        sys.exit("這個指令需要在 .env 填入 BINANCE_API_KEY 和 BINANCE_API_SECRET")

    if args.cmd == "run":
        confirm_mainnet(cfg)
        try:
            Trader(cfg, client).run(args.poll)
        except KeyboardInterrupt:
            log.info("已手動停止。若還有持倉，交易所上的止損/止盈單仍然有效。")

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
        strat = {"macd_rsi": "MACD + RSI", "ema_cross": "EMA 交叉"}[cfg.strategy]
        log.info("回測中：共 %d 根 K 線，策略=%s…", len(candles), strat)
        res = run_backtest(cfg, candles, filters)
        if args.trades:
            for t in res.trades:
                print(f"{zh_side(t.side)} 進場={t.entry:.2f} 出場={t.exit:.2f} 損益={t.pnl:+.2f}（{zh_reason(t.reason)}）")
        print(res.summary())

    elif args.cmd == "status":
        client.sync_time()
        bal = client.usdt_balance()
        print(f"USDT 錢包餘額={bal['wallet']:.2f} 可用餘額={bal['available']:.2f}")
        for p in client.position_risk(cfg.symbol):
            if float(p["positionAmt"]) != 0:
                print(f"{p['symbol']} 持倉數量={p['positionAmt']} 開倉價={p['entryPrice']} "
                      f"未實現損益={p['unRealizedProfit']} 強平價={p.get('liquidationPrice')}")

    elif args.cmd == "close":
        client.sync_time()
        from bot.broker import LiveBroker
        filters = SymbolFilters.from_exchange_info(client.symbol_info(cfg.symbol))
        LiveBroker(client, cfg.symbol, filters).close(0, "manual_close")
        print("已取消所有掛單並平倉。")


if __name__ == "__main__":
    import requests
    from bot.client import BinanceAPIError
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n已停止。")
    except ValueError as e:
        sys.exit(f"設定錯誤：{e}")
    except BinanceAPIError as e:
        sys.exit(f"幣安回應錯誤：{e}")
    except requests.RequestException as e:
        sys.exit(f"無法連線到幣安，請檢查網路（{type(e).__name__}）")
    except RuntimeError as e:
        sys.exit(f"錯誤：{e}")
