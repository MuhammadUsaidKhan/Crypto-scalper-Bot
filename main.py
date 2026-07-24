from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict

import yaml

from src.data import CoinGeckoClient, BinancePublicClient
from src.dashboard import TerminalDashboard, write_html_dashboard
from src.indicators import add_indicators
from src.logger import TradeLogger
from src.paper_broker import PaperBroker
from src.risk import size_position
from src.strategies import combined_signal


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_utc():
    return datetime.now(timezone.utc)


def symbol_for_binance(coin_symbol: str, quote="USDT") -> str:
    return f"{coin_symbol.upper()}{quote.upper()}"


def main():
    cfg = load_config()
    print("1. Config loaded")
    cg = CoinGeckoClient()
    print("2. CoinGecko client OK")
    bn = BinancePublicClient()
    print("3. Binance client OK")
    broker = PaperBroker(cfg["account"]["starting_balance_usdt"], cfg["runtime"]["paper_fee_pct"])
    logger = TradeLogger(cfg["runtime"]["csv_trade_log"], cfg["runtime"]["csv_equity_log"], cfg["sheets"])
    dash = TerminalDashboard()
    last_trade_time: Dict[str, datetime] = {}

    print("Starting crypto scalper paper bot. Press Ctrl+C to stop.")

    while True:
        cycle_started = now_utc()
        prices = {}
        try:
            print("4. Fetching universe...")
            universe = cg.mid_cap_universe(
                cfg["universe"]["min_market_cap_usd"],
                cfg["universe"]["max_market_cap_usd"],
                cfg["universe"]["top_n"],
                cfg["universe"].get("excluded_symbols", []),
            )
            print(f"5. Found {len(universe)} coins")
        except Exception as exc:
            print(f"Universe fetch failed: {exc}")
            universe = []

        for coin in universe:
            coin_symbol = coin["symbol"].upper()
            market_symbol = symbol_for_binance(coin_symbol, cfg["universe"]["quote_asset"])
            print(f"Checking {market_symbol}")
            if not bn.has_symbol(market_symbol):
                continue
            try:
                df = bn.klines(market_symbol, cfg["runtime"]["candle_interval"], cfg["runtime"]["candle_limit"])
                print(type(df))
                print(df.head())
                print(df.shape)
                df = add_indicators(df).dropna()
                if df.empty:
                    continue
                price = float(df.iloc[-1]["close"])
                prices[market_symbol] = price
                imbalance = bn.orderbook_imbalance(market_symbol)
                signal, score, reason, raw_signals = combined_signal(df, imbalance, cfg["signals"]["min_total_score_to_enter"])

                # Manage existing position first.
                pos = broker.positions.get(market_symbol)
                if pos:
                    broker.maybe_update_trailing(market_symbol, price, cfg["risk"]["trailing_stop_pct"])
                    pos = broker.positions.get(market_symbol)
                    exit_reason = None
                    if price <= pos.stop_loss:
                        exit_reason = "Stop-loss hit"
                    elif price >= pos.take_profit:
                        exit_reason = "Take-profit hit"
                    elif price <= pos.trailing_stop:
                        exit_reason = "Trailing stop hit"
                    elif signal == "SELL":
                        exit_reason = f"Sell signal: {reason}"
                    if exit_reason:
                        trade = broker.sell(market_symbol, price, exit_reason)
                        if trade:
                            logger.log_trade(trade)
                            last_trade_time[market_symbol] = now_utc()
                    continue

                # Entry filters.
                if signal != "BUY":
                    continue
                if len(broker.positions) >= cfg["account"]["max_open_positions"]:
                    continue
                cooldown_until = last_trade_time.get(market_symbol, datetime.min.replace(tzinfo=timezone.utc)) + timedelta(minutes=cfg["risk"]["cooldown_after_trade_minutes"])
                if now_utc() < cooldown_until:
                    continue

                equity = broker.equity(prices)
                stop_pct = cfg["risk"]["default_stop_loss_pct"]
                take_profit_pct = cfg["risk"]["default_take_profit_pct"]
                sizing = size_position(
                    balance=equity,
                    price=price,
                    risk_per_trade_pct=cfg["account"]["risk_per_trade_pct"],
                    stop_loss_pct=stop_pct,
                    max_allocation_pct=cfg["account"]["max_coin_allocation_pct"],
                )
                broker.buy(
                    symbol=market_symbol,
                    coin_id=coin["id"],
                    price=price,
                    qty=sizing.qty,
                    strategy="COMBINED_SCALP_SCORE",
                    stop_loss_pct=stop_pct,
                    take_profit_pct=take_profit_pct,
                    trailing_stop_pct=cfg["risk"]["trailing_stop_pct"],
                    reason=f"Score {score}: {reason}",
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"{market_symbol} skipped: {exc}")

        # Dashboard + equity logging.
        print("6. Entering dashboard section")
        latest_prices = {**prices}
        for symbol, pos in broker.positions.items():
            latest_prices.setdefault(symbol, pos.entry_price)
        equity = broker.equity(latest_prices)
        logger.log_equity(now_utc().isoformat(), equity, broker.cash, len(broker.positions))
        positions = broker.position_rows(latest_prices)
        dash.update(universe, positions, broker.closed_trades, equity, broker.cash)
        print("Writing dashboard...")
        write_html_dashboard(cfg["runtime"]["dashboard_html"], universe, positions, broker.closed_trades, equity, broker.cash)
        print("Dashboard written successfully.")
        elapsed = (now_utc() - cycle_started).total_seconds()
        sleep_for = max(5, cfg["runtime"]["cycle_seconds"] - elapsed)
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Bot stopped by user.")
