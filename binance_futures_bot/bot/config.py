"""Configuration loaded from environment variables / a local .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (no external dependency). Existing env vars win."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    return float(v) if v not in (None, "") else default


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v not in (None, "") else default


@dataclass
class Config:
    api_key: str = ""
    api_secret: str = ""
    use_testnet: bool = True
    dry_run: bool = True

    symbol: str = "BTCUSDT"
    interval: str = "15m"
    leverage: int = 5
    margin_type: str = "ISOLATED"

    strategy: str = "macd_rsi"       # "macd_rsi" or "ema_cross"
    ema_fast: int = 20
    ema_slow: int = 50
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_long_min: float = 50.0       # long only if RSI in [min, max]
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0      # short only if RSI in [min, max]
    rsi_short_max: float = 50.0
    rsi_period: int = 14
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0

    risk_per_trade_pct: float = 1.0
    max_position_fraction: float = 0.5
    max_daily_loss_pct: float = 5.0
    paper_balance: float = 1000.0

    @property
    def base_url(self) -> str:
        return (
            "https://testnet.binancefuture.com"
            if self.use_testnet
            else "https://fapi.binance.com"
        )

    @classmethod
    def from_env(cls, dotenv_path: str | Path = ".env") -> "Config":
        load_dotenv(dotenv_path)
        cfg = cls(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
            use_testnet=_bool("USE_TESTNET", True),
            dry_run=_bool("DRY_RUN", True),
            symbol=os.getenv("SYMBOL", "BTCUSDT").upper(),
            interval=os.getenv("INTERVAL", "15m"),
            leverage=_int("LEVERAGE", 5),
            margin_type=os.getenv("MARGIN_TYPE", "ISOLATED").upper(),
            strategy=os.getenv("STRATEGY", "macd_rsi").strip().lower(),
            macd_fast=_int("MACD_FAST", 12),
            macd_slow=_int("MACD_SLOW", 26),
            macd_signal=_int("MACD_SIGNAL", 9),
            rsi_long_min=_float("RSI_LONG_MIN", 50.0),
            rsi_long_max=_float("RSI_LONG_MAX", 70.0),
            rsi_short_min=_float("RSI_SHORT_MIN", 30.0),
            rsi_short_max=_float("RSI_SHORT_MAX", 50.0),
            ema_fast=_int("EMA_FAST", 20),
            ema_slow=_int("EMA_SLOW", 50),
            rsi_period=_int("RSI_PERIOD", 14),
            atr_period=_int("ATR_PERIOD", 14),
            sl_atr_mult=_float("SL_ATR_MULT", 1.5),
            tp_atr_mult=_float("TP_ATR_MULT", 3.0),
            risk_per_trade_pct=_float("RISK_PER_TRADE_PCT", 1.0),
            max_position_fraction=_float("MAX_POSITION_FRACTION", 0.5),
            max_daily_loss_pct=_float("MAX_DAILY_LOSS_PCT", 5.0),
            paper_balance=_float("PAPER_BALANCE", 1000.0),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.strategy not in ("macd_rsi", "ema_cross"):
            raise ValueError("STRATEGY 只能是 macd_rsi 或 ema_cross")
        if self.macd_fast >= self.macd_slow or self.macd_signal <= 0:
            raise ValueError("MACD_FAST 必須小於 MACD_SLOW，且 MACD_SIGNAL 必須大於 0")
        if not (0 <= self.rsi_long_min < self.rsi_long_max <= 100
                and 0 <= self.rsi_short_min < self.rsi_short_max <= 100):
            raise ValueError("RSI_*_MIN 必須小於 RSI_*_MAX，且都在 0 到 100 之間")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("EMA_FAST 必須小於 EMA_SLOW")
        if not 1 <= self.leverage <= 125:
            raise ValueError("LEVERAGE 槓桿必須在 1 到 125 之間")
        if self.margin_type not in ("ISOLATED", "CROSSED"):
            raise ValueError("MARGIN_TYPE 只能是 ISOLATED（逐倉）或 CROSSED（全倉）")
        if not 0 < self.risk_per_trade_pct <= 10:
            raise ValueError("RISK_PER_TRADE_PCT 必須大於 0 且不超過 10")
        if self.sl_atr_mult <= 0 or self.tp_atr_mult <= 0:
            raise ValueError("SL_ATR_MULT / TP_ATR_MULT 必須大於 0")
        if not self.dry_run and (not self.api_key or not self.api_secret):
            raise ValueError("DRY_RUN=false 時必須在 .env 填入 BINANCE_API_KEY 和 BINANCE_API_SECRET")
