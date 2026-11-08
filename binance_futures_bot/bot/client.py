"""Thin REST client for Binance USDT-M Futures (HMAC-SHA256 signed)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

# Binance moved conditional orders (STOP_MARKET / TAKE_PROFIT_MARKET ...) to the
# Algo Order service; the legacy endpoint answers with this code once migrated.
ERR_USE_ALGO_ORDER = -4120
ERR_NO_NEED_TO_CHANGE_MARGIN = -4046


class BinanceAPIError(Exception):
    def __init__(self, status: int, code: int, msg: str):
        super().__init__(f"HTTP {status} code={code} msg={msg}")
        self.status, self.code, self.msg = status, code, msg


class BinanceFuturesClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str,
                 recv_window: int = 5000, timeout: float = 10.0):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout = timeout
        self.session = requests.Session()
        if api_key:
            self.session.headers["X-MBX-APIKEY"] = api_key
        self._time_offset = 0

    # ------------------------------------------------------------------ core
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                 signed: bool = False, retries: int = 3) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in range(1, retries + 1):
            p = dict(params)
            if signed:
                p["timestamp"] = int(time.time() * 1000) + self._time_offset
                p["recvWindow"] = self.recv_window
                query = urlencode(p)
                sig = hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()
                query = f"{query}&signature={sig}"
            else:
                query = urlencode(p)
            url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
            try:
                resp = self.session.request(method, url, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == retries:
                    raise
                log.warning("Network error %s %s: %s (retry %d)", method, path, e, attempt)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            try:
                body = resp.json()
                code, msg = int(body.get("code", 0)), body.get("msg", resp.text)
            except ValueError:
                code, msg = 0, resp.text

            # Clock drift -> resync and retry
            if code == -1021 and attempt < retries:
                self.sync_time()
                continue
            # Rate limit / server errors -> back off and retry
            if resp.status_code in (429, 418) or resp.status_code >= 500:
                if attempt < retries:
                    wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                    log.warning("HTTP %s on %s, sleeping %ss", resp.status_code, path, wait)
                    time.sleep(wait)
                    continue
            raise BinanceAPIError(resp.status_code, code, msg)
        raise RuntimeError("unreachable")

    def sync_time(self) -> None:
        server = self._request("GET", "/fapi/v1/time")["serverTime"]
        self._time_offset = int(server) - int(time.time() * 1000)
        log.debug("Time offset vs server: %d ms", self._time_offset)

    # --------------------------------------------------------------- market
    def exchange_info(self) -> dict:
        return self._request("GET", "/fapi/v1/exchangeInfo")

    def symbol_info(self, symbol: str) -> dict:
        for s in self.exchange_info()["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise ValueError(f"Symbol {symbol} not found on exchange")

    def klines(self, symbol: str, interval: str, limit: int = 500,
               start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[list]:
        return self._request("GET", "/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
            "startTime": start_time, "endTime": end_time,
        })

    def mark_price(self, symbol: str) -> float:
        return float(self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})["markPrice"])

    # -------------------------------------------------------------- account
    def usdt_balance(self) -> Dict[str, float]:
        for b in self._request("GET", "/fapi/v2/balance", signed=True):
            if b["asset"] == "USDT":
                return {"wallet": float(b["balance"]), "available": float(b["availableBalance"])}
        return {"wallet": 0.0, "available": 0.0}

    def position_risk(self, symbol: str) -> List[dict]:
        return self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)

    def is_hedge_mode(self) -> bool:
        return bool(self._request("GET", "/fapi/v1/positionSide/dual", signed=True)["dualSidePosition"])

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        return self._request("POST", "/fapi/v1/leverage",
                             {"symbol": symbol, "leverage": leverage}, signed=True)

    def set_margin_type(self, symbol: str, margin_type: str) -> None:
        try:
            self._request("POST", "/fapi/v1/marginType",
                          {"symbol": symbol, "marginType": margin_type}, signed=True)
        except BinanceAPIError as e:
            if e.code != ERR_NO_NEED_TO_CHANGE_MARGIN:
                raise

    # --------------------------------------------------------------- orders
    def market_order(self, symbol: str, side: str, quantity: str, reduce_only: bool = False) -> dict:
        return self._request("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity,
            "reduceOnly": "true" if reduce_only else None,
            "newOrderRespType": "RESULT",
        }, signed=True)

    def close_position_stop(self, symbol: str, side: str, order_type: str, trigger_price: str) -> dict:
        """Place a STOP_MARKET / TAKE_PROFIT_MARKET that closes the whole position.

        Tries the legacy order endpoint first and falls back to the Algo Order
        endpoint when Binance replies that conditional orders were migrated.
        """
        try:
            return self._request("POST", "/fapi/v1/order", {
                "symbol": symbol, "side": side, "type": order_type,
                "stopPrice": trigger_price, "closePosition": "true",
                "workingType": "MARK_PRICE",
            }, signed=True)
        except BinanceAPIError as e:
            if e.code != ERR_USE_ALGO_ORDER:
                raise
        return self._request("POST", "/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": symbol, "side": side, "type": order_type,
            "triggerPrice": trigger_price, "closePosition": "true",
            "workingType": "MARK_PRICE",
        }, signed=True)

    def cancel_all(self, symbol: str) -> None:
        for path in ("/fapi/v1/allOpenOrders", "/fapi/v1/algoOpenOrders"):
            try:
                self._request("DELETE", path, {"symbol": symbol}, signed=True)
            except BinanceAPIError as e:
                log.debug("cancel via %s ignored: %s", path, e)
