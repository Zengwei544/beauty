// 交易策略：MACD + RSI（預設）與 EMA 交叉，只在 K 線收盤後判斷
import { atr, ema, macd, rsi } from "./indicators.js";

function makeSignal(cfg, side, price, a, reason) {
  const d = side === "LONG" ? 1 : -1;
  return {
    side, entry: price, atr: a, reason,
    stopLoss: price - d * a * cfg.slAtrMult,
    takeProfit: price + d * a * cfg.tpAtrMult,
  };
}

export function warmup(cfg) {
  if (cfg.strategy === "ema_cross") return Math.max(cfg.emaSlow, cfg.rsiPeriod, cfg.atrPeriod) + 2;
  return Math.max(cfg.macdSlow + cfg.macdSignal, cfg.rsiPeriod, cfg.atrPeriod) + 2;
}

export function evaluate(cfg, candles) {
  if (candles.length < warmup(cfg)) return null;
  const closes = candles.map((c) => c.close);
  const a = atr(candles.map((c) => c.high), candles.map((c) => c.low), closes, cfg.atrPeriod).at(-1);
  const r = rsi(closes, cfg.rsiPeriod).at(-1);
  const price = closes.at(-1);

  if (cfg.strategy === "ema_cross") {
    const f = ema(closes, cfg.emaFast), s = ema(closes, cfg.emaSlow);
    const [f0, f1, s0, s1] = [f.at(-2), f.at(-1), s.at(-2), s.at(-1)];
    if ([f0, f1, s0, s1, r, a].includes(null) || a <= 0) return null;
    if (f0 <= s0 && f1 > s1 && r > 50)
      return makeSignal(cfg, "LONG", price, a, `EMA${cfg.emaFast} 上穿 EMA${cfg.emaSlow}，RSI=${r.toFixed(1)}`);
    if (f0 >= s0 && f1 < s1 && r < 50)
      return makeSignal(cfg, "SHORT", price, a, `EMA${cfg.emaFast} 下穿 EMA${cfg.emaSlow}，RSI=${r.toFixed(1)}`);
    return null;
  }

  const { line, sig, hist } = macd(closes, cfg.macdFast, cfg.macdSlow, cfg.macdSignal);
  const h0 = hist.at(-2), h1 = hist.at(-1);
  if ([h0, h1, r, a].includes(null) || a <= 0) return null;
  const info = `MACD=${line.at(-1).toFixed(4)} 訊號線=${sig.at(-1).toFixed(4)} RSI=${r.toFixed(1)}`;
  if (h0 <= 0 && 0 < h1 && cfg.rsiLongMin < r && r < cfg.rsiLongMax)
    return makeSignal(cfg, "LONG", price, a, "MACD 金叉（快線上穿訊號線），" + info);
  if (h0 >= 0 && 0 > h1 && cfg.rsiShortMin < r && r < cfg.rsiShortMax)
    return makeSignal(cfg, "SHORT", price, a, "MACD 死叉（快線下穿訊號線），" + info);
  return null;
}
