from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class StrategySignal:
    name: str
    side: str  # BUY, SELL, HOLD
    score: int
    reason: str


def _last_two(df: pd.DataFrame):
    if len(df) < 30:
        return None, None
    return df.iloc[-2], df.iloc[-1]


def ema_vwap_rsi(df: pd.DataFrame) -> StrategySignal:
    prev, row = _last_two(df)
    if row is None:
        return StrategySignal("EMA_VWAP_RSI", "HOLD", 0, "Not enough candles")

    crossed_up = prev["ema9"] <= prev["ema21"] and row["ema9"] > row["ema21"]
    trend_ok = row["close"] > row["vwap"] and row["rsi14"] < 70
    crossed_down = prev["ema9"] >= prev["ema21"] and row["ema9"] < row["ema21"]

    if crossed_up and trend_ok:
        return StrategySignal("EMA_VWAP_RSI", "BUY", 1, "EMA9 crossed above EMA21, price above VWAP, RSI below 70")
    if crossed_down or row["rsi14"] > 78:
        return StrategySignal("EMA_VWAP_RSI", "SELL", -1, "EMA momentum faded or RSI overheated")
    return StrategySignal("EMA_VWAP_RSI", "HOLD", 0, "No clean trend signal")


def bollinger_rsi_reversion(df: pd.DataFrame) -> StrategySignal:
    _, row = _last_two(df)
    if row is None:
        return StrategySignal("BB_RSI_REVERSION", "HOLD", 0, "Not enough candles")

    if row["close"] < row["bb_lower"] and row["rsi14"] < 32:
        return StrategySignal("BB_RSI_REVERSION", "BUY", 1, "Price below lower Bollinger Band and RSI oversold")
    if row["close"] > row["bb_mid"] or row["rsi14"] > 62:
        return StrategySignal("BB_RSI_REVERSION", "SELL", -1, "Mean reversion target reached or RSI normalized")
    return StrategySignal("BB_RSI_REVERSION", "HOLD", 0, "No mean-reversion setup")


def breakout_orderbook(df: pd.DataFrame, orderbook_imbalance: Optional[float]) -> StrategySignal:
    prev, row = _last_two(df)
    if row is None:
        return StrategySignal("BREAKOUT_ORDERBOOK", "HOLD", 0, "Not enough candles")

    previous_high = df["high"].iloc[-21:-1].max()
    volume_ok = row["volume"] > 1.25 * row["volume_ma20"] if row["volume_ma20"] > 0 else False
    imbalance_ok = orderbook_imbalance is not None and orderbook_imbalance >= 0.58
    breakdown = row["close"] < df["low"].iloc[-21:-1].min()

    if row["close"] > previous_high and volume_ok and (imbalance_ok or orderbook_imbalance is None):
        reason = "20-candle breakout with volume confirmation"
        if imbalance_ok:
            reason += f" and bid imbalance {orderbook_imbalance:.2f}"
        return StrategySignal("BREAKOUT_ORDERBOOK", "BUY", 1, reason)
    if breakdown or (orderbook_imbalance is not None and orderbook_imbalance <= 0.42):
        return StrategySignal("BREAKOUT_ORDERBOOK", "SELL", -1, "Breakdown or ask-side order-book pressure")
    return StrategySignal("BREAKOUT_ORDERBOOK", "HOLD", 0, "No breakout setup")


def combined_signal(df: pd.DataFrame, orderbook_imbalance: Optional[float], min_score: int):
    signals = [
        ema_vwap_rsi(df),
        bollinger_rsi_reversion(df),
        breakout_orderbook(df, orderbook_imbalance),
    ]
    total = sum(s.score for s in signals)
    buy_reasons = [s.reason for s in signals if s.side == "BUY"]
    sell_reasons = [s.reason for s in signals if s.side == "SELL"]

    if total >= min_score:
        return "BUY", total, "; ".join(buy_reasons), signals
    if total <= -1:
        return "SELL", total, "; ".join(sell_reasons), signals
    return "HOLD", total, "Strategies not aligned", signals
