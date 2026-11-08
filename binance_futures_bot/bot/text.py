"""程式輸出用的中文文字（方向、平倉原因、幣安錯誤碼、命令列說明）。"""
from __future__ import annotations

import argparse
import logging

SIDE = {"LONG": "做多", "SHORT": "做空"}

REASON = {
    "stop_loss": "止損",
    "take_profit": "止盈",
    "reverse_signal": "反向訊號平倉",
    "end_of_data": "回測結束平倉",
    "manual_close": "手動平倉",
    "protection_failed": "止損單掛單失敗，安全平倉",
}

# 常見幣安錯誤碼的中文說明
BINANCE_ERRORS = {
    -1003: "請求過於頻繁，被限流",
    -1021: "時間戳超出範圍（電腦時間不準）",
    -1022: "簽名錯誤（請檢查 API Secret）",
    -1102: "缺少必要參數",
    -1111: "數量或價格精度錯誤",
    -1121: "交易對不存在",
    -2010: "下單被拒絕",
    -2011: "取消訂單失敗（訂單不存在）",
    -2014: "API Key 格式錯誤",
    -2015: "API Key 無效、IP 不在白名單，或沒有開合約權限",
    -2019: "保證金不足",
    -2022: "只減倉訂單被拒絕（目前沒有可減的倉位）",
    -4003: "數量必須大於 0",
    -4046: "保證金模式不需要變更",
    -4059: "持倉模式不需要變更",
    -4120: "條件單需改用 Algo Order 介面",
    -4131: "市價單價格偏離過大，被拒絕",
    -4164: "下單名目價值低於最小限制",
}


def side(s: str) -> str:
    return SIDE.get(s, s)


def reason(r: str) -> str:
    return REASON.get(r, r)


def binance_error(code: int, msg: str) -> str:
    zh = BINANCE_ERRORS.get(code)
    return f"{zh}（錯誤碼 {code}，原始訊息：{msg}）" if zh else f"幣安錯誤碼 {code}：{msg}"


# ---------------------------------------------------------------- 日誌等級
LEVELS = {logging.DEBUG: "除錯", logging.INFO: "資訊", logging.WARNING: "警告",
          logging.ERROR: "錯誤", logging.CRITICAL: "嚴重"}


def chinese_log_levels() -> None:
    for lvl, name in LEVELS.items():
        logging.addLevelName(lvl, name)


# ---------------------------------------------------------------- 命令列說明
_ARGPARSE = {
    "usage: ": "用法：",
    "positional arguments": "子指令",
    "options": "選項",
    "optional arguments": "選項",
    "show this help message and exit": "顯示說明並離開",
    "the following arguments are required: %s": "缺少必要參數：%s",
    "unrecognized arguments: %s": "無法辨識的參數：%s",
    "not allowed with argument %s": "不能和參數 %s 一起使用",
    "expected one argument": "需要提供一個值",
    "invalid choice: %(value)r (choose from %(choices)s)": "無效的選項：%(value)r（可選：%(choices)s）",
    "invalid %(type)s value: %(value)r": "無效的數值：%(value)r",
    "argument %(argument_name)s: %(message)s": "參數 %(argument_name)s：%(message)s",
    "%(prog)s: error: %(message)s\n": "%(prog)s：錯誤：%(message)s\n",
}


def chinese_argparse() -> None:
    argparse._ = lambda s: _ARGPARSE.get(s, s)  # type: ignore[attr-defined]
