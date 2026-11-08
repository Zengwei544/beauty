# 幣安合約自動交易系統

用 Python 撰寫的幣安 **U 本位永續合約** 自動交易機器人，內建策略、倉位計算、止損止盈、風控、紙上交易和回測。

> ⚠️ **風險警告**：合約交易有槓桿，可能在短時間內虧掉全部保證金。本程式只是工具，**不保證獲利**。
> 請先在 **測試網 + 紙上交易** 跑一段時間，並先做回測，再考慮投入真實資金，且只投入你虧得起的金額。

## 功能

| 模組 | 說明 |
|---|---|
| `bot/strategy.py` | **MACD + RSI**（預設）與 EMA 交叉兩種策略，ATR 計算止損止盈 |
| `bot/risk.py` | 依「每筆最多虧損帳戶 X%」計算下單數量；依交易所規則取整；單日虧損上限 |
| `bot/broker.py` | 本機模擬下單與真實下單（自動掛止損/止盈單） |
| `bot/client.py` | 幣安合約介面（請求簽名、時間同步、限流重試、條件單自動切換到新的條件單介面） |
| `bot/trader.py` | 主迴圈：只在 K 線收盤後判斷，避免假訊號 |
| `bot/backtest.py` | 回測（下一根開盤成交、含手續費、計算勝率/回撤/獲利因子） |

### 策略規則：MACD + RSI（預設，`STRATEGY=macd_rsi`）
- **做多**：MACD(12,26,9) 快線**上穿**訊號線（金叉），且 **50 < RSI(14) < 70**
  （動能轉強、但還沒超買，避免追高）
- **做空**：MACD 快線**下穿**訊號線（死叉），且 **30 < RSI(14) < 50**
  （動能轉弱、但還沒超賣，避免追空）
- RSI 區間可在 `.env` 用 `RSI_LONG_MIN/MAX`、`RSI_SHORT_MIN/MAX` 調整

另有 EMA 交叉策略（`STRATEGY=ema_cross`）：EMA20 上/下穿 EMA50 且 RSI 在 50 之上/下。

兩種策略共通：
- **止損** = 進場價 ∓ 1.5 × ATR；**止盈** = 進場價 ± 3 × ATR（風報比 1:2）
- 出現反向訊號時平倉並反手
- 止損/止盈單直接掛在交易所（全部平倉、以標記價格觸發），程式當機也有保護

## 安裝

需要 Python 3.10 以上版本。

```bash
cd binance_futures_bot
pip install -r requirements.txt
cp .env.example .env      # 然後編輯 .env
```

## 使用步驟（建議照順序）

**1. 回測**（不需要 API Key）
```bash
python main.py backtest --days 90           # 下載最近 90 天真實 K 線回測
python main.py backtest --days 90 --trades  # 列出每筆交易
python main.py backtest --synthetic         # 離線用模擬資料測試
python main.py backtest --days 90 --strategy ema_cross   # 和 EMA 策略比較
```

**2. 紙上交易**：`.env` 設 `DRY_RUN=true`，用真實行情、模擬下單
```bash
python main.py run
```

**3. 測試網真實下單**：到 <https://testnet.binancefuture.com> 申請測試 API Key，
`.env` 設 `USE_TESTNET=true`、`DRY_RUN=false`，填入 Key 後執行 `python main.py run`。

**4. 正式網**（真錢）：`USE_TESTNET=false`、`DRY_RUN=false`。啟動時需輸入「確定」才會開始。

### 其他指令
```bash
python main.py status    # 查看餘額與持倉
python main.py close     # 緊急：取消所有掛單並市價平倉
```

## 重要設定與注意事項

- **API Key 權限**：只開「讀取」+「合約交易」，**絕對不要開提現**，並綁定 IP 白名單。
- **持倉模式**必須是「單向持倉」，雙向模式會拒絕啟動。
- 一個程式只交易一個幣種；同一幣種不要同時手動下單，以免互相干擾。
- `.env` 已加入 `.gitignore`，**不要把 API Key 上傳到任何網路空間**。
- 所有輸出與日誌都是繁體中文，日誌存在 `logs/bot.log`。
- 建議放在雲端主機上長時間執行（可用 `tmux` 或 `systemd` 讓它在背景運作）。

## 調整參數

全部在 `.env` 中：`SYMBOL`、`INTERVAL`（如 `5m`、`15m`、`1h`、`4h`）、`LEVERAGE`、
`STRATEGY`、`MACD_FAST/MACD_SLOW/MACD_SIGNAL`、`RSI_LONG_MIN/MAX`、`RSI_SHORT_MIN/MAX`、`SL_ATR_MULT/TP_ATR_MULT`、`RISK_PER_TRADE_PCT`、`MAX_DAILY_LOSS_PCT` 等。
改參數後先回測再上線。

想換策略：在 `bot/strategy.py` 新增一個策略類別（實作 `evaluate` 方法，回傳交易訊號或不回傳），再加進 `STRATEGIES` 即可。

## 程式測試

```bash
python -m unittest -v
```
