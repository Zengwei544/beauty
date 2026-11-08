// 倉位計算、交易所數量/價格取整、單日虧損上限

const decimals = (step) => {
  const s = String(step);
  return s.includes(".") ? s.replace(/0+$/, "").split(".")[1].length : 0;
};

export const DEFAULT_FILTERS = { stepSize: "0.001", minQty: "0.001", tickSize: "0.1", minNotional: "5" };

export function filtersFromSymbolInfo(info) {
  const f = { ...DEFAULT_FILTERS };
  for (const flt of info.filters || []) {
    if (flt.filterType === "LOT_SIZE") { f.stepSize = flt.stepSize; f.minQty = flt.minQty; }
    else if (flt.filterType === "PRICE_FILTER") f.tickSize = flt.tickSize;
    else if (flt.filterType === "MIN_NOTIONAL") f.minNotional = flt.notional ?? flt.minNotional ?? "5";
  }
  return f;
}

// 回傳字串，避免浮點誤差送出 0.30000000004 這種數量
export function roundQty(qty, f) {
  const step = Number(f.stepSize);
  const n = Math.floor(qty / step + 1e-9);
  return (n * step).toFixed(decimals(f.stepSize));
}

export function roundPrice(price, f) {
  const tick = Number(f.tickSize);
  return (Math.round(price / tick) * tick).toFixed(decimals(f.tickSize));
}

export function positionSize(balance, entry, stopLoss, cfg, f) {
  const dist = Math.abs(entry - stopLoss);
  if (balance <= 0 || entry <= 0 || dist <= 0) return "0";
  const byRisk = (balance * cfg.riskPerTradePct) / 100 / dist;
  const byCap = (balance * cfg.leverage * cfg.maxPositionFraction) / entry;
  const q = roundQty(Math.min(byRisk, byCap), f);
  if (Number(q) < Number(f.minQty) || Number(q) * entry < Number(f.minNotional)) return "0";
  return q;
}

export function utcDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

// guard = { day, startBalance }，會原地更新
export function updateGuard(guard, balance, nowMs) {
  const d = utcDay(nowMs);
  if (guard.day !== d) { guard.day = d; guard.startBalance = balance; }
}

export function canTrade(guard, balance, maxDailyLossPct) {
  if (!guard.startBalance || guard.startBalance <= 0) return true;
  return ((guard.startBalance - balance) / guard.startBalance) * 100 < maxDailyLossPct;
}
