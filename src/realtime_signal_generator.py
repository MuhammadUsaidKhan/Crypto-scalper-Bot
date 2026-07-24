from __future__ import annotations

"""
Live signal generator.

Streams public Binance market data (order-book deltas, trade prints, 1m
klines) over WebSocket for a set of symbols, runs the existing technical
strategies (indicators.py / strategies.py) on the live candle series, and
layers in MicrostructureDetector so a BUY signal is suppressed if the
book looks like it's showing spoofed/fake liquidity rather than real
demand at that moment.

This only reads public market data. It never places, cancels, or amends
any order on any exchange.

Usage:
    pip install websockets pandas requests
    python realtime_signal_generator.py BTCUSDT ETHUSDT SOLUSDT
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

try:
    import websockets
except ImportError as exc:  # pragma: no cover
    raise ImportError("This module needs the 'websockets' package: pip install websockets") from exc

from indicators import add_indicators
from strategies import combined_signal
from microstructure import MicrostructureDetector, MicrostructureFlags

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream?streams="


@dataclass
class LiveSignal:
    symbol: str
    timestamp: float
    side: str  # BUY / SELL / HOLD
    technical_score: int
    technical_reason: str
    orderbook_imbalance: Optional[float]
    micro: MicrostructureFlags
    vetoed: bool
    veto_reason: str


class _SymbolState:
    def __init__(self, symbol: str, kline_history: int = 200):
        self.symbol = symbol
        self.detector = MicrostructureDetector(symbol)
        self.candles: List[dict] = []
        self.kline_history = kline_history

    def ohlcv_df(self) -> Optional[pd.DataFrame]:
        if len(self.candles) < 30:
            return None
        return add_indicators(pd.DataFrame(self.candles))


class RealtimeSignalGenerator:
    def __init__(
        self,
        symbols: List[str],
        on_signal: Optional[Callable[[LiveSignal], None]] = None,
        min_score: int = 2,
        spoof_veto_threshold: float = 0.5,
        stuffing_veto_threshold: float = 0.6,
        fake_depth_veto_threshold: float = 12.0,
    ):
        if not symbols:
            raise ValueError("Provide at least one symbol, e.g. ['BTCUSDT']")
        self.symbols = [s.lower() for s in symbols]
        self.on_signal = on_signal or self._default_on_signal
        self.min_score = min_score
        self.spoof_veto_threshold = spoof_veto_threshold
        self.stuffing_veto_threshold = stuffing_veto_threshold
        self.fake_depth_veto_threshold = fake_depth_veto_threshold
        self.state: Dict[str, _SymbolState] = {s: _SymbolState(s) for s in self.symbols}

    # ---------------- default output ----------------

    def _default_on_signal(self, signal: LiveSignal):
        tag = " [VETOED]" if signal.vetoed else ""
        ts = time.strftime("%H:%M:%S", time.localtime(signal.timestamp))
        imb = f"{signal.orderbook_imbalance:.2f}" if signal.orderbook_imbalance is not None else "n/a"
        print(
            f"{ts} {signal.symbol.upper():<10} {signal.side:<4} score={signal.technical_score:+d}{tag}  "
            f"imbalance={imb}  spoof={signal.micro.spoof_score}  stuffing={signal.micro.quote_stuffing_score}  "
            f"fake_depth={signal.micro.fake_depth_ratio}  iceberg={signal.micro.iceberg_score}"
        )
        if signal.vetoed:
            print(f"    veto: {signal.veto_reason}")
        elif signal.side != "HOLD":
            print(f"    reason: {signal.technical_reason}")
        for note in signal.micro.notes:
            print(f"    flag: {note}")

    # ---------------- connection ----------------

    def _stream_url(self) -> str:
        streams: List[str] = []
        for s in self.symbols:
            streams += [f"{s}@depth@100ms", f"{s}@trade", f"{s}@kline_1m"]
        return BINANCE_WS_BASE + "/".join(streams)

    async def run(self):
        url = self._stream_url()
        async for ws in websockets.connect(url, ping_interval=15, ping_timeout=10):
            try:
                async for raw in ws:
                    self._handle_message(json.loads(raw))
            except websockets.ConnectionClosed:
                continue  # library reconnects automatically on the next loop iteration

    # ---------------- message handling ----------------

    def _handle_message(self, msg: dict):
        stream = msg.get("stream", "")
        data = msg.get("data", {})
        if not stream:
            return
        symbol = stream.split("@")[0]
        state = self.state.get(symbol)
        if state is None:
            return

        now = time.time()
        if "@depth" in stream:
            state.detector.on_depth_update(data.get("b", []), data.get("a", []), ts=now)
        elif "@trade" in stream:
            state.detector.on_trade(float(data["p"]), float(data["q"]), ts=now)
        elif "@kline" in stream:
            k = data.get("k", {})
            if k.get("x"):  # candle closed
                state.candles.append(
                    {
                        "timestamp": pd.to_datetime(k["t"], unit="ms", utc=True),
                        "open": float(k["o"]),
                        "high": float(k["h"]),
                        "low": float(k["l"]),
                        "close": float(k["c"]),
                        "volume": float(k["v"]),
                    }
                )
                state.candles = state.candles[-state.kline_history:]
                self._evaluate(symbol, state)

    def _evaluate(self, symbol: str, state: _SymbolState):
        df = state.ohlcv_df()
        if df is None:
            return

        bid_notional = sum(p * q for p, q in state.detector.bids.items())
        ask_notional = sum(p * q for p, q in state.detector.asks.items())
        total = bid_notional + ask_notional
        imbalance = (bid_notional / total) if total > 0 else None

        side, score, reason, _ = combined_signal(df, imbalance, self.min_score)
        micro = state.detector.snapshot()

        vetoed, veto_reason = False, ""
        if side == "BUY" and micro.spoof_score >= self.spoof_veto_threshold:
            vetoed, veto_reason = True, "High spoofing/layering activity detected on the book"
        elif side == "BUY" and micro.quote_stuffing_score >= self.stuffing_veto_threshold:
            vetoed, veto_reason = True, "Abnormal quote-stuffing activity detected"
        elif side == "BUY" and micro.fake_depth_ratio > self.fake_depth_veto_threshold:
            vetoed, veto_reason = True, "Displayed depth looks disconnected from real trading flow"

        signal = LiveSignal(
            symbol=symbol,
            timestamp=time.time(),
            side=side if not vetoed else "HOLD",
            technical_score=score,
            technical_reason=reason,
            orderbook_imbalance=imbalance,
            micro=micro,
            vetoed=vetoed,
            veto_reason=veto_reason,
        )
        self.on_signal(signal)


async def _main(symbols: List[str]):
    generator = RealtimeSignalGenerator(symbols=symbols)
    print(f"Streaming live signals for: {', '.join(symbols)} (Ctrl+C to stop)\n")
    await generator.run()


if __name__ == "__main__":
    syms = [s.upper() for s in sys.argv[1:]] or ["BTCUSDT"]
    try:
        asyncio.run(_main(syms))
    except KeyboardInterrupt:
        print("\nStopped.")
