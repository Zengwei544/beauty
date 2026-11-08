// 中文文字
export const SIDE = { LONG: "做多", SHORT: "做空" };
export const REASON = {
  stop_loss: "止損", take_profit: "止盈", reverse_signal: "反向訊號平倉",
  manual_close: "手動平倉", protection_failed: "止損單掛單失敗，安全平倉",
  closed_on_exchange: "交易所止損/止盈已觸發",
};
export const side = (s) => SIDE[s] ?? s;
export const reason = (r) => REASON[r] ?? r;
export const STRATEGY_NAME = { macd_rsi: "MACD + RSI", ema_cross: "EMA 交叉" };

export const BINANCE_ERRORS = {
  [-1003]: "請求過於頻繁，被限流", [-1021]: "時間戳超出範圍", [-1022]: "簽名錯誤（請檢查 API Secret）",
  [-1102]: "缺少必要參數", [-1111]: "數量或價格精度錯誤", [-1121]: "交易對不存在",
  [-2010]: "下單被拒絕", [-2011]: "取消訂單失敗（訂單不存在）", [-2014]: "API Key 格式錯誤",
  [-2015]: "API Key 無效、IP 不在白名單，或沒有開合約權限", [-2019]: "保證金不足",
  [-2022]: "只減倉訂單被拒絕（目前沒有可減的倉位）", [-4003]: "數量必須大於 0",
  [-4046]: "保證金模式不需要變更", [-4120]: "條件單需改用 Algo Order 介面",
  [-4131]: "市價單價格偏離過大，被拒絕", [-4164]: "下單名目價值低於最小限制",
};
export function binanceError(code, msg) {
  const zh = BINANCE_ERRORS[code];
  return zh ? `${zh}（錯誤碼 ${code}，原始訊息：${msg}）` : `幣安錯誤碼 ${code}：${msg}`;
}
