from __future__ import annotations
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional

import pandas as pd
import requests


class CoinGeckoClient:
    BASE = "https://api.coingecko.com/api/v3"

    def __init__(self, min_delay: float = 1.2):
        self.session = requests.Session()
        self.min_delay = min_delay
        self._last_call = 0.0

    def _get(self, path: str, params: dict):
        elapsed = time.time() - self._last_call
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        url = f"{self.BASE}{path}"
        r = self.session.get(url, params=params, timeout=20)
        self._last_call = time.time()
        r.raise_for_status()
        return r.json()

    def mid_cap_universe(self, min_cap: int, max_cap: int, top_n: int, excluded_symbols: List[str]) -> List[dict]:
        coins = []
        for page in range(1, 6):
            data = self._get(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": 250,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h",
                },
            )
            for coin in data:
                cap = coin.get("market_cap") or 0
                symbol = (coin.get("symbol") or "").upper()
                if min_cap <= cap <= max_cap and symbol not in excluded_symbols:
                    coins.append(coin)
            if len(coins) >= top_n:
                break
        return coins[:top_n]


class BinancePublicClient:
    BASE = "https://api.binance.com"

    def __init__(self):
        self.session = requests.Session()
        self._symbols_cache = None

    def exchange_symbols(self) -> set:
        if self._symbols_cache is not None:
            return self._symbols_cache
        r = self.session.get(f"{self.BASE}/api/v3/exchangeInfo", timeout=20)
        r.raise_for_status()
        self._symbols_cache = {s["symbol"] for s in r.json()["symbols"] if s.get("status") == "TRADING"}
        return self._symbols_cache

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self.exchange_symbols()

    def klines(self, symbol: str, interval: str = "1m", limit: int = 120) -> pd.DataFrame:
        print(f"Downloading candles for {symbol}")
        r = self.session.get(
            f"{self.BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=20,
        )
        print(f"Response received for {symbol}")
        r.raise_for_status()
        print(f"Status OK for {symbol}")
        print("Before JSON")
        rows = r.json()
        print("After JSON")
        print("Creating DataFrame")
        df = pd.DataFrame(rows, columns=[
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        print("DataFrame created")
        numeric_cols = ["open", "high", "low", "close", "volume", "quote_volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        print("Numeric conversion done")

        print("Checking open_time...")
        print(df["open_time"].head())
        print("dtype:", df["open_time"].dtype)

        # Convert open_time to numeric first
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")

        print("After numeric conversion:")
        print(df["open_time"].head())
        print("dtype:", df["open_time"].dtype)

        print("Building timestamps manually...")
        df["timestamp"] = [
            datetime.fromtimestamp(int(x) / 1000, tz=timezone.utc)
            for x in df["open_time"].tolist()
        ]
        print("Timestamp conversion done")

        print("Timestamp conversion done")

        return df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume"]]

    def orderbook_imbalance(self, symbol: str, limit: int = 50) -> Optional[float]:
        try:
            print(f"Downloading orderbook for {symbol}")
            r = self.session.get(f"{self.BASE}/api/v3/depth", params={"symbol": symbol, "limit": limit}, timeout=10)
            print(f"Orderbook received for {symbol}")
            r.raise_for_status()
            data = r.json()
            bid_notional = sum(float(p) * float(q) for p, q in data.get("bids", []))
            ask_notional = sum(float(p) * float(q) for p, q in data.get("asks", []))
            total = bid_notional + ask_notional
            return bid_notional / total if total > 0 else None
        except Exception:
            return None
