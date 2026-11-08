// 技術指標（與 Python 版 bot/indicators.py 相同演算法）

export function ema(values, period) {
  const out = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = 0;
  for (let i = 0; i < period; i++) prev += values[i];
  prev /= period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

function rsiValue(g, l) {
  if (l === 0) return g > 0 ? 100 : 50;
  return 100 - 100 / (1 + g / l);
}

export function rsi(closes, period = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let g = 0, l = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    g += Math.max(d, 0); l += Math.max(-d, 0);
  }
  g /= period; l /= period;
  out[period] = rsiValue(g, l);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    g = (g * (period - 1) + Math.max(d, 0)) / period;
    l = (l * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = rsiValue(g, l);
  }
  return out;
}

export function atr(highs, lows, closes, period = 14) {
  const n = closes.length;
  const out = new Array(n).fill(null);
  if (n <= period) return out;
  const trs = [highs[0] - lows[0]];
  for (let i = 1; i < n; i++) {
    trs.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - closes[i - 1]), Math.abs(lows[i] - closes[i - 1])));
  }
  let prev = 0;
  for (let i = 1; i <= period; i++) prev += trs[i];
  prev /= period;
  out[period] = prev;
  for (let i = period + 1; i < n; i++) {
    prev = (prev * (period - 1) + trs[i]) / period;
    out[i] = prev;
  }
  return out;
}

export function macd(closes, fast = 12, slow = 26, signal = 9) {
  const n = closes.length;
  const ef = ema(closes, fast), es = ema(closes, slow);
  const line = ef.map((v, i) => (v === null || es[i] === null ? null : v - es[i]));
  const sig = new Array(n).fill(null), hist = new Array(n).fill(null);
  const start = line.findIndex((v) => v !== null);
  if (start < 0) return { line, sig, hist };
  const part = ema(line.slice(start), signal);
  part.forEach((v, j) => {
    sig[start + j] = v;
    if (v !== null) hist[start + j] = line[start + j] - v;
  });
  return { line, sig, hist };
}
