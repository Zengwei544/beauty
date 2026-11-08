// 幣安 U 本位合約 REST 介面（HMAC-SHA256 簽名，使用 Web Crypto）
import { binanceError } from "./text.js";

export const ERR_USE_ALGO_ORDER = -4120;
const ERR_NO_NEED_TO_CHANGE_MARGIN = -4046;

export class BinanceAPIError extends Error {
  constructor(status, code, msg) {
    super(`HTTP ${status}，${binanceError(code, msg)}`);
    this.status = status; this.code = code; this.msg = msg;
  }
}

const enc = new TextEncoder();

export class BinanceClient {
  constructor(apiKey, apiSecret, baseUrl, fetchImpl = fetch) {
    this.apiKey = apiKey; this.apiSecret = apiSecret; this.baseUrl = baseUrl;
    this.fetch = fetchImpl; this.timeOffset = 0; this._key = null;
  }

  async sign(query) {
    if (!this._key) {
      this._key = await crypto.subtle.importKey("raw", enc.encode(this.apiSecret),
        { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    }
    const sig = await crypto.subtle.sign("HMAC", this._key, enc.encode(query));
    return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async request(method, path, params = {}, signed = false) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) p.append(k, String(v));
    if (signed) {
      p.append("timestamp", String(Date.now() + this.timeOffset));
      p.append("recvWindow", "5000");
    }
    let query = p.toString();
    if (signed) query += `&signature=${await this.sign(query)}`;
    const url = this.baseUrl + path + (query ? `?${query}` : "");
    const headers = signed || this.apiKey ? { "X-MBX-APIKEY": this.apiKey } : {};
    const resp = await this.fetch(url, { method, headers });
    const text = await resp.text();
    if (resp.ok) return JSON.parse(text);
    let code = 0, msg = text.slice(0, 200);
    try { const j = JSON.parse(text); code = Number(j.code ?? 0); msg = j.msg ?? msg; } catch {}
    if (resp.status === 403 && !code) msg = "連線被幣安拒絕（可能是所在地區受限制）";
    if (resp.status === 451) msg = "所在地區受幣安限制，無法連線";
    throw new BinanceAPIError(resp.status, code, msg);
  }

  async serverTime() {
    const t = (await this.request("GET", "/fapi/v1/time")).serverTime;
    this.timeOffset = t - Date.now();
    return t;
  }

  klines(symbol, interval, limit = 300) {
    return this.request("GET", "/fapi/v1/klines", { symbol, interval, limit });
  }

  async symbolInfo(symbol) {
    const info = await this.request("GET", "/fapi/v1/exchangeInfo");
    const s = info.symbols.find((x) => x.symbol === symbol);
    if (!s) throw new Error(`交易所找不到交易對 ${symbol}`);
    return s;
  }

  async usdtBalance() {
    const b = (await this.request("GET", "/fapi/v2/balance", {}, true)).find((x) => x.asset === "USDT");
    return b ? { wallet: Number(b.balance), available: Number(b.availableBalance) } : { wallet: 0, available: 0 };
  }

  positionRisk(symbol) { return this.request("GET", "/fapi/v2/positionRisk", { symbol }, true); }

  async isHedgeMode() {
    return !!(await this.request("GET", "/fapi/v1/positionSide/dual", {}, true)).dualSidePosition;
  }

  setLeverage(symbol, leverage) { return this.request("POST", "/fapi/v1/leverage", { symbol, leverage }, true); }

  async setMarginType(symbol, marginType) {
    try { await this.request("POST", "/fapi/v1/marginType", { symbol, marginType }, true); }
    catch (e) { if (e.code !== ERR_NO_NEED_TO_CHANGE_MARGIN) throw e; }
  }

  marketOrder(symbol, side, quantity, reduceOnly = false) {
    return this.request("POST", "/fapi/v1/order", {
      symbol, side, type: "MARKET", quantity,
      reduceOnly: reduceOnly ? "true" : undefined, newOrderRespType: "RESULT",
    }, true);
  }

  // 掛「全部平倉」的止損 / 止盈單；舊介面被拒絕時改用 Algo Order 介面
  async closePositionStop(symbol, side, type, triggerPrice) {
    try {
      return await this.request("POST", "/fapi/v1/order", {
        symbol, side, type, stopPrice: triggerPrice, closePosition: "true", workingType: "MARK_PRICE",
      }, true);
    } catch (e) {
      if (e.code !== ERR_USE_ALGO_ORDER) throw e;
    }
    return this.request("POST", "/fapi/v1/algoOrder", {
      algoType: "CONDITIONAL", symbol, side, type, triggerPrice, closePosition: "true", workingType: "MARK_PRICE",
    }, true);
  }

  async cancelAll(symbol) {
    for (const path of ["/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"]) {
      try { await this.request("DELETE", path, { symbol }, true); } catch {}
    }
  }
}
