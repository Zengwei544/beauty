import unittest
from decimal import Decimal

from bot.backtest import run_backtest, synthetic_candles
from bot.broker import LiveBroker, PaperBroker
from bot.client import BinanceAPIError, ERR_USE_ALGO_ORDER, BinanceFuturesClient
from bot.config import Config
from bot.indicators import atr, ema, macd, rsi
from bot.risk import DailyLossGuard, SymbolFilters, position_size
from bot.strategy import Candle, EmaCrossStrategy, MacdRsiStrategy, Signal, make_strategy
from bot.trader import Trader


def cfg(**kw):
    c = Config(**kw)
    c.validate()
    return c


class IndicatorTests(unittest.TestCase):
    def test_ema_constant_series(self):
        out = ema([5.0] * 30, 10)
        self.assertIsNone(out[8])
        self.assertAlmostEqual(out[-1], 5.0)

    def test_ema_matches_manual(self):
        out = ema([1, 2, 3, 4, 5], 3)
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], 3.0)   # 4*0.5 + 2*0.5
        self.assertAlmostEqual(out[4], 4.0)

    def test_rsi_bounds(self):
        up = rsi([float(i) for i in range(50)], 14)
        down = rsi([float(50 - i) for i in range(50)], 14)
        self.assertEqual(up[-1], 100.0)
        self.assertEqual(down[-1], 0.0)

    def test_atr_constant_range(self):
        n = 40
        out = atr([11.0] * n, [9.0] * n, [10.0] * n, 14)
        self.assertAlmostEqual(out[-1], 2.0)


    def test_macd_matches_manual_ema(self):
        closes = [100 + (i % 7) - i * 0.3 for i in range(60)]
        line, sig, hist = macd(closes, 12, 26, 9)
        ef, es = ema(closes, 12), ema(closes, 26)
        self.assertIsNone(line[24])
        self.assertAlmostEqual(line[-1], ef[-1] - es[-1])
        valid = [v for v in line if v is not None]
        self.assertAlmostEqual(sig[-1], ema(valid, 9)[-1])
        self.assertAlmostEqual(hist[-1], line[-1] - sig[-1])
        self.assertIsNone(sig[25 + 7])           # signal needs 9 MACD values
        self.assertIsNotNone(sig[25 + 8])


class RiskTests(unittest.TestCase):
    def test_round_qty_and_price(self):
        f = SymbolFilters(step_size=Decimal("0.001"), tick_size=Decimal("0.1"))
        self.assertEqual(f.round_qty(0.12399), Decimal("0.123"))
        self.assertEqual(f.round_price(60000.06), Decimal("60000.1"))

    def test_position_size_risk_based(self):
        f = SymbolFilters()
        # 1% of 10000 = 100 USDT risk; stop 500 away -> 0.2 BTC
        q = position_size(10000, 60000, 59500, 1.0, 10, 1.0, f)
        self.assertEqual(q, Decimal("0.200"))

    def test_position_size_capped_by_leverage(self):
        f = SymbolFilters()
        # tiny stop -> risk sizing huge, capped at 1000*5*0.5/60000 = 0.0416 -> 0.041
        q = position_size(1000, 60000, 59999, 1.0, 5, 0.5, f)
        self.assertEqual(q, Decimal("0.041"))

    def test_position_size_below_minimum(self):
        self.assertEqual(position_size(10, 60000, 59000, 1.0, 5, 0.5, SymbolFilters()), 0)

    def test_daily_loss_guard(self):
        import datetime as dt
        g = DailyLossGuard(5.0)
        g.update(1000, dt.date(2026, 1, 1))
        self.assertTrue(g.can_trade(960))
        self.assertFalse(g.can_trade(949))
        g.update(949, dt.date(2026, 1, 2))   # new day resets
        self.assertTrue(g.can_trade(949))


def make_candles(closes):
    return [Candle(i, c, c * 1.001, c * 0.999, c, 1, i + 1) for i, c in enumerate(closes)]


class StrategyTests(unittest.TestCase):
    def test_long_signal_on_cross_up(self):
        c = cfg(ema_fast=5, ema_slow=10, rsi_period=5, atr_period=5)
        closes = [100 - i * 0.5 for i in range(30)] + [85 + i * 2 for i in range(10)]
        strat = EmaCrossStrategy(c)
        sigs = [strat.evaluate(make_candles(closes[:n])) for n in range(15, len(closes) + 1)]
        longs = [s for s in sigs if s and s.side == "LONG"]
        self.assertEqual(len(longs), 1)
        s = longs[0]
        self.assertLess(s.stop_loss, s.entry)
        self.assertGreater(s.take_profit, s.entry)

    def test_no_signal_without_enough_data(self):
        self.assertIsNone(EmaCrossStrategy(cfg()).evaluate(make_candles([1.0] * 10)))


class MacdRsiStrategyTests(unittest.TestCase):
    @staticmethod
    def wave(drift, n=200):
        import math
        return [100 + drift * i + 4 * math.sin(i / 8) for i in range(n)]

    def signals(self, closes, **kw):
        strat = MacdRsiStrategy(cfg(**kw))
        out = []
        for n in range(strat.warmup, len(closes) + 1):
            s = strat.evaluate(make_candles(closes[:n]))
            if s:
                out.append((n - 1, s))
        return out

    def test_uptrend_longs_only(self):
        # MACD crosses up with RSI ~53-60 (allowed); crosses down with RSI ~90 (blocked)
        sigs = self.signals(self.wave(0.15))
        self.assertEqual([i for i, _ in sigs], [41, 93, 143, 193])
        self.assertTrue(all(s.side == "LONG" for _, s in sigs))
        s = sigs[0][1]
        self.assertIn("MACD crossed above", s.reason)
        self.assertLess(s.stop_loss, s.entry)
        self.assertGreater(s.take_profit, s.entry)

    def test_downtrend_shorts_only(self):
        # crosses down with RSI ~40 (allowed); crosses up with RSI ~8 (blocked)
        sigs = self.signals(self.wave(-0.15))
        self.assertEqual([i for i, _ in sigs], [68, 118, 168])
        self.assertTrue(all(s.side == "SHORT" for _, s in sigs))
        self.assertGreater(sigs[0][1].stop_loss, sigs[0][1].entry)

    def test_rsi_filter_blocks_extremes(self):
        # pure sine: crosses happen at RSI ~6 / ~94 -> all filtered by default
        self.assertEqual(self.signals(self.wave(0, 160)), [])
        wide = self.signals(self.wave(0, 160), rsi_long_min=0, rsi_long_max=100,
                            rsi_short_min=0, rsi_short_max=100)
        self.assertEqual([s.side for _, s in wide], ["LONG", "SHORT", "LONG", "SHORT", "LONG"])

    def test_factory_and_default(self):
        self.assertIsInstance(make_strategy(cfg()), MacdRsiStrategy)
        self.assertIsInstance(make_strategy(cfg(strategy="ema_cross")), EmaCrossStrategy)
        with self.assertRaises(ValueError):
            cfg(strategy="nope")


class PaperBrokerTests(unittest.TestCase):
    def test_stop_loss_hit(self):
        b = PaperBroker(1000, fee=0)
        b.open(Signal("LONG", 100, 95, 110, 2, ""), Decimal("1"), 100)
        t = b.on_candle(Candle(0, 99, 101, 94, 96, 1, 1))
        self.assertEqual(t.reason, "stop_loss")
        self.assertAlmostEqual(t.pnl, -5)
        self.assertAlmostEqual(b.balance, 995)

    def test_short_take_profit_and_fees(self):
        b = PaperBroker(1000, fee=0.001)
        b.open(Signal("SHORT", 100, 105, 90, 2, ""), Decimal("1"), 100)
        t = b.on_candle(Candle(0, 98, 99, 89, 90, 1, 1))
        self.assertEqual(t.reason, "take_profit")
        self.assertAlmostEqual(t.pnl, 10 - 0.1 - 0.09)
        self.assertAlmostEqual(b.balance, 1000 + t.pnl)

    def test_sl_tp_reanchored_to_fill(self):
        b = PaperBroker(1000, fee=0)
        b.open(Signal("LONG", 100, 95, 110, 2, ""), Decimal("1"), 102)
        self.assertAlmostEqual(b.position.stop_loss, 97)
        self.assertAlmostEqual(b.position.take_profit, 112)


class BacktestTests(unittest.TestCase):
    def test_backtest_runs_and_is_consistent(self):
        for name in ("macd_rsi", "ema_cross"):
            with self.subTest(strategy=name):
                res = run_backtest(cfg(paper_balance=10000, strategy=name), synthetic_candles(2000))
                self.assertGreater(len(res.trades), 5)
                self.assertAlmostEqual(res.end_balance, 10000 + sum(t.pnl for t in res.trades), places=6)
                self.assertGreaterEqual(res.max_drawdown_pct, 0)


# ---------------------------------------------------------------- fake exchange
class FakeClient:
    """Mimics the parts of BinanceFuturesClient the trader uses."""

    def __init__(self, candles, algo_only=False):
        self.candles = candles
        self.visible = 0
        self._time_offset = 0
        self.position_amt = 0.0
        self.entry = 0.0
        self.orders = []
        self.algo_only = algo_only

    def sync_time(self): pass
    def symbol_info(self, s): return {"filters": []}
    def is_hedge_mode(self): return False
    def set_margin_type(self, *a): pass
    def set_leverage(self, *a): pass
    def usdt_balance(self): return {"wallet": 10000.0, "available": 10000.0}

    def klines(self, symbol, interval, limit, **kw):
        cs = self.candles[: self.visible][-limit:]
        return [[c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time] for c in cs]

    def position_risk(self, symbol):
        return [{"positionSide": "BOTH", "positionAmt": str(self.position_amt), "entryPrice": str(self.entry)}]

    def cancel_all(self, symbol): self.orders.append(("CANCEL",))

    def market_order(self, symbol, side, qty, reduce_only=False):
        q = float(qty) * (1 if side == "BUY" else -1)
        self.position_amt = round(self.position_amt + q, 8)
        self.entry = self.candles[self.visible - 1].close
        self.orders.append(("MARKET", side, qty, reduce_only))
        return {"orderId": len(self.orders), "avgPrice": str(self.entry)}

    def close_position_stop(self, symbol, side, typ, price):
        self.orders.append((typ, side, price))
        return {}


class TraderTests(unittest.TestCase):
    def _run(self, client, n):
        c = cfg(dry_run=False, api_key="k", api_secret="s", paper_balance=10000)
        t = Trader(c, client)
        t.setup()
        import bot.trader as tr
        orig = tr.time.time
        tr.time.time = lambda: 10 ** 13  # every candle is "closed"
        try:
            for i in range(60, n):
                client.visible = i
                t.step()
        finally:
            tr.time.time = orig
        return t

    def test_live_loop_places_market_and_protective_orders(self):
        client = FakeClient(synthetic_candles(1500))
        self._run(client, 1500)
        kinds = [o[0] for o in client.orders]
        self.assertIn("MARKET", kinds)
        self.assertIn("STOP_MARKET", kinds)
        self.assertIn("TAKE_PROFIT_MARKET", kinds)
        # every entry is followed by a SL and TP
        for i, o in enumerate(client.orders):
            if o[0] == "MARKET" and not o[3]:
                self.assertEqual(client.orders[i + 1][0], "STOP_MARKET")
                self.assertEqual(client.orders[i + 2][0], "TAKE_PROFIT_MARKET")
        # never more than one position's worth open (one-way, no pyramiding)
        self.assertLess(abs(client.position_amt), 10)


class ClientTests(unittest.TestCase):
    def test_signature_and_algo_fallback(self):
        c = BinanceFuturesClient("key", "secret", "https://example.invalid")
        calls = []

        def fake_request(method, path, params=None, signed=False, retries=3):
            calls.append((path, params))
            if path == "/fapi/v1/order":
                raise BinanceAPIError(400, ERR_USE_ALGO_ORDER, "use algo")
            return {"algoId": 1}

        c._request = fake_request
        c.close_position_stop("BTCUSDT", "SELL", "STOP_MARKET", "59000.0")
        self.assertEqual(calls[1][0], "/fapi/v1/algoOrder")
        self.assertEqual(calls[1][1]["algoType"], "CONDITIONAL")
        self.assertEqual(calls[1][1]["triggerPrice"], "59000.0")

    def test_hmac_signature_matches_binance_docs_example(self):
        # Example from Binance API docs (HMAC SHA256).
        import hashlib, hmac
        secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
        query = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
                 "&recvWindow=5000&timestamp=1499827319559")
        sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(sig, "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71")


if __name__ == "__main__":
    unittest.main()
