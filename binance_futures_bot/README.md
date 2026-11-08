# 幣安合約自動交易系統（Binance USDT-M Futures Bot）

用 Python 寫的幣安 **U 本位永續合約** 自動交易機器人，內建策略、倉位計算、止損止盈、風控、紙上交易和回測。

> ⚠️ **風險警告**：合約交易有槓桿，可能在短時間內虧掉全部保證金。本程式只是工具，**不保證獲利**。
> 請先在 **測試網 + 紙上交易** 跑一段時間，並先做回測，再考慮投入真實資金，且只投入你虧得起的金額。

## 功能

| 模組 | 說明 |
|---|---|
| `bot/strategy.py` | EMA 交叉趨勢策略 + RSI 過濾，ATR 計算止損止盈 |
| `bot/risk.py` | 依「每筆最多虧損帳戶 X%」計算下單數量；依交易所規則取整；單日虧損上限 |
| `bot/broker.py` | `PaperBroker`（本機模擬）與 `LiveBroker`（真實下單，自動掛止損/止盈單） |
| `bot/client.py` | 幣安合約 REST API（HMAC 簽名、時間同步、限流重試、條件單自動切換 Algo Order 介面） |
| `bot/trader.py` | 主迴圈：只在 K 線收盤後判斷，避免假訊號 |
| `bot/backtest.py` | 回測（下一根開盤成交、含手續費、計算勝率/回撤/獲利因子） |

### 策略規則
- **做多**：快線 EMA(20) 上穿慢線 EMA(50) 且 RSI > 50
- **做空**：快線 EMA(20) 下穿慢線 EMA(50) 且 RSI < 50
- **止損** = 進場價 ∓ 1.5 × ATR；**止盈** = 進場價 ± 3 × ATR（風報比 1:2）
- 出現反向訊號時平倉並反手
- 止損/止盈單直接掛在交易所（`closePosition`，用標記價格觸發），程式當機也有保護

## 安裝

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
```

**2. 紙上交易**：`.env` 設 `DRY_RUN=true`，用真實行情、模擬下單
```bash
python main.py run
```

**3. 測試網真實下單**：到 <https://testnet.binancefuture.com> 申請測試 API Key，
`.env` 設 `USE_TESTNET=true`、`DRY_RUN=false`，填入 Key 後執行 `python main.py run`。

**4. 正式網**（真錢）：`USE_TESTNET=false`、`DRY_RUN=false`。啟動時需輸入 `YES` 確認。

### 其他指令
```bash
python main.py status    # 查看餘額與持倉
python main.py close     # 緊急：取消所有掛單並市價平倉
```

## 重要設定與注意事項

- **API Key 權限**：只開「讀取」+「合約交易」，**絕對不要開提現**，並綁定 IP 白名單。
- **持倉模式**必須是「單向持倉 (One-way)」，雙向模式會拒絕啟動。
- 一個程式只交易一個幣種；同一幣種不要同時手動下單，以免互相干擾。
- `.env` 已加入 `.gitignore`，**不要把 API Key 上傳到 GitHub**。
- 日誌寫在 `logs/bot.log`。
- 建議放在 VPS 上用 `tmux` / `systemd` 長時間執行。

## 調整參數

全部在 `.env` 中：`SYMBOL`、`INTERVAL`（如 `5m`、`15m`、`1h`、`4h`）、`LEVERAGE`、
`EMA_FAST/EMA_SLOW`、`SL_ATR_MULT/TP_ATR_MULT`、`RISK_PER_TRADE_PCT`、`MAX_DAILY_LOSS_PCT` 等。
改參數後先回測再上線。

想換策略：在 `bot/strategy.py` 寫一個有 `evaluate(candles) -> Signal | None` 方法的類別即可。

## 測試

```bash
python -m unittest -v
```
