# Crypto Mid-Cap Scalping Paper Trading Bot

A free-tier paper trading bot for monitoring crypto assets with market caps between $50M and $200M. It dynamically selects up to 20 coins using CoinGecko market-cap data, then uses public exchange data for candles/order-book analysis where available.

> Educational paper-trading tool only. It is not financial advice and does not guarantee profit.

## Strategies Included

1. **EMA + VWAP + RSI trend scalp**
   - Long when fast EMA crosses above slow EMA, price is above VWAP, and RSI is not overbought.

2. **Bollinger Band + RSI mean reversion scalp**
   - Long when price stretches below the lower band and RSI shows oversold conditions.

3. **Donchian breakout + volume + order-book imbalance scalp**
   - Long when price breaks recent highs with volume confirmation and bid-side depth pressure.

The bot combines these into a score. A paper buy happens when enough strategies agree and risk limits allow it. Exits occur by stop-loss, take-profit, trailing stop, sell signal, or strategy reversal.

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The bot runs every `cycle_seconds` from `config.yaml`.

## Google Sheets Logging

CSV logging works automatically. To also log into Google Sheets:

1. Create a Google Cloud project.
2. Enable **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account** and download its JSON key.
4. Save it as `service_account.json` in this project folder.
5. Create a Google Sheet named exactly as `sheets.spreadsheet_name` in `config.yaml`.
6. Share that sheet with the service account email from the JSON file.
7. Set:

```yaml
sheets:
  enabled: true
```

## Dashboard

- Terminal dashboard: shown live with Rich.
- HTML dashboard: generated as `dashboard.html`. Open it in your browser and refresh, or use a browser extension for auto-refresh.

## Going Live Later

This project intentionally uses a `PaperBroker`. To go live:

1. Add an exchange client module such as `ccxt` or the official Binance/Bybit client.
2. Replace `PaperBroker.buy()` and `PaperBroker.sell()` with real order calls.
3. Use testnet first.
4. Add API keys through environment variables only.
5. Add exchange min-notional/step-size validation.
6. Add slippage, network failure handling, order reconciliation, and kill switches.

Never go live until you have backtested, forward-tested, and reviewed logs for several weeks.
