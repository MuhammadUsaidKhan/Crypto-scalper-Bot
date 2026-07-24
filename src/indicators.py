from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    return (typical * vol).cumsum() / vol.cumsum()


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return mid, upper, lower


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema9"] = ema(df["close"], 9)
    df["ema21"] = ema(df["close"], 21)
    df["rsi14"] = rsi(df["close"], 14)
    df["vwap"] = vwap(df)
    df["bb_mid"], df["bb_upper"], df["bb_lower"] = bollinger(df["close"], 20, 2.0)
    df["atr14"] = atr(df, 14)
    df["donchian_high"] = df["high"].rolling(20).max()
    df["donchian_low"] = df["low"].rolling(20).min()
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    return df
