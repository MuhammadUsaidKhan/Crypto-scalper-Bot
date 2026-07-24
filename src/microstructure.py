from __future__ import annotations

"""
Heuristic order-book microstructure detector.

Flags statistical PATTERNS commonly associated with:
  - spoofing / layering  (large orders placed then pulled with little/no fill)
  - fake / phantom depth (displayed size far exceeds real traded flow)
  - quote stuffing       (book update rate far exceeds trade rate)
  - iceberg orders       (a price level keeps refilling after being eaten)

IMPORTANT LIMITS: public market data (Binance depth diffs / trade prints,
same shape for most exchanges) never exposes order IDs or trader
identity, only aggregated price-level quantities. So this module can only
say "this looks consistent with X" from statistics, not "trader Y did X".
Treat every score here as a probabilistic filter for YOUR OWN strategy
(e.g. don't buy into what looks like fake liquidity), never as a
market-manipulation accusation about a specific counterparty, and never
as a blueprint for producing this behavior yourself.
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple


@dataclass
class MicrostructureFlags:
    symbol: str
    timestamp: float
    spoof_score: float           # 0..1 — large orders placed & pulled with little/no fill
    quote_stuffing_score: float  # 0..1 — update rate vs trade rate, abnormally high
    fake_depth_ratio: float      # displayed notional / realized traded notional (>1 = thin real flow)
    iceberg_score: float         # 0..1 — repeated refilling of a depleted price level
    imbalance_flip_rate: float   # bid/ask dominance flips per minute (book "flicker")
    notes: List[str]


@dataclass
class _WatchedLevel:
    side: str
    price: float
    qty_added: float
    first_seen: float
    filled_notional: float = 0.0


class MicrostructureDetector:
    def __init__(
        self,
        symbol: str,
        large_order_usd: float = 25_000,
        spoof_window_sec: float = 8.0,
        spoof_fill_ratio_max: float = 0.15,
        stuffing_rate_threshold: float = 40.0,
        history_window_sec: float = 300.0,
        trade_price_tolerance: float = 0.0005,  # 5 bps, "same price level" for fill matching
    ):
        self.symbol = symbol
        self.large_order_usd = large_order_usd
        self.spoof_window_sec = spoof_window_sec
        self.spoof_fill_ratio_max = spoof_fill_ratio_max
        self.stuffing_rate_threshold = stuffing_rate_threshold
        self.history_window_sec = history_window_sec
        self.trade_price_tolerance = trade_price_tolerance

        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}

        self._watched: Dict[Tuple[str, float], _WatchedLevel] = {}
        self._recently_emptied: Dict[Tuple[str, float], float] = {}  # key -> ts it was emptied
        self._refill_counts: Dict[Tuple[str, float], int] = defaultdict(int)

        self._spoof_events: Deque[float] = deque()
        self._update_timestamps: Deque[float] = deque()
        self._trade_timestamps: Deque[float] = deque()
        self._flip_events: Deque[float] = deque()
        self._last_dominant_side: Optional[str] = None

    # ---------------- ingestion ----------------

    def on_depth_update(self, bid_updates: List[list], ask_updates: List[list], ts: Optional[float] = None):
        """bid_updates/ask_updates: [[price_str, qty_str], ...] deltas (Binance diff-depth shape).
        A qty of 0 means the price level was removed."""
        ts = ts if ts is not None else time.time()
        self._update_timestamps.append(ts)
        self._trim(self._update_timestamps, ts)

        for side, book, updates in (("bid", self.bids, bid_updates), ("ask", self.asks, ask_updates)):
            for price_s, qty_s in updates:
                price = float(price_s)
                qty = float(qty_s)
                prev_qty = book.get(price, 0.0)

                if qty == 0.0:
                    if price in book:
                        del book[price]
                    self._on_level_removed(side, price, ts)
                    continue

                added_notional = (qty - prev_qty) * price
                key = (side, price)
                if prev_qty == 0.0 and key in self._recently_emptied:
                    if ts - self._recently_emptied[key] <= self.spoof_window_sec:
                        self._refill_counts[key] += 1
                    del self._recently_emptied[key]
                if added_notional >= self.large_order_usd:
                    self._watched[(side, price)] = _WatchedLevel(
                        side=side, price=price, qty_added=qty - prev_qty, first_seen=ts
                    )
                book[price] = qty

        self._update_dominance(ts)

    def on_trade(self, price: float, qty: float, ts: Optional[float] = None):
        ts = ts if ts is not None else time.time()
        self._trade_timestamps.append(ts)
        self._trim(self._trade_timestamps, ts)
        notional = price * qty
        for level in self._watched.values():
            if level.price > 0 and abs(level.price - price) / level.price <= self.trade_price_tolerance:
                level.filled_notional += notional

    # ---------------- internals ----------------

    def _on_level_removed(self, side: str, price: float, ts: float):
        key = (side, price)
        self._recently_emptied[key] = ts
        # bound memory: drop stale entries
        if len(self._recently_emptied) > 500:
            cutoff = ts - self.history_window_sec
            self._recently_emptied = {k: v for k, v in self._recently_emptied.items() if v > cutoff}

        level = self._watched.pop(key, None)
        if level is None:
            return
        elapsed = ts - level.first_seen
        added_notional = level.qty_added * price
        fill_ratio = (level.filled_notional / added_notional) if added_notional > 0 else 1.0
        if (
            elapsed <= self.spoof_window_sec
            and fill_ratio <= self.spoof_fill_ratio_max
            and added_notional >= self.large_order_usd
        ):
            self._spoof_events.append(ts)
        self._trim(self._spoof_events, ts)

    def _update_dominance(self, ts: float):
        bid_notional = sum(p * q for p, q in self.bids.items())
        ask_notional = sum(p * q for p, q in self.asks.items())
        if bid_notional + ask_notional == 0:
            return
        side = "bid" if bid_notional >= ask_notional else "ask"
        if self._last_dominant_side is not None and side != self._last_dominant_side:
            self._flip_events.append(ts)
        self._last_dominant_side = side
        self._trim(self._flip_events, ts)

    def _trim(self, dq: Deque[float], now: float):
        while dq and now - dq[0] > self.history_window_sec:
            dq.popleft()

    # ---------------- output ----------------

    def snapshot(self) -> MicrostructureFlags:
        now = time.time()
        window = max(1.0, self.history_window_sec)

        spoof_score = min(1.0, len(self._spoof_events) / 5.0)

        update_rate = len(self._update_timestamps) / window
        trade_rate = max(1e-6, len(self._trade_timestamps) / window)
        quote_stuffing_score = min(1.0, (update_rate / trade_rate) / self.stuffing_rate_threshold)

        bid_notional = sum(p * q for p, q in self.bids.items())
        ask_notional = sum(p * q for p, q in self.asks.items())
        displayed_notional = bid_notional + ask_notional
        traded_notional_est = trade_rate * window
        fake_depth_ratio = round(displayed_notional / traded_notional_est, 2) if traded_notional_est > 0 else 0.0

        refill_events = sum(1 for c in self._refill_counts.values() if c >= 2)
        iceberg_score = min(1.0, refill_events / 5.0)

        flips_per_min = len(self._flip_events) / (window / 60.0)

        notes: List[str] = []
        if spoof_score > 0.4:
            notes.append("Repeated large orders placed and pulled with little/no fill — layering/spoofing pattern")
        if quote_stuffing_score > 0.5:
            notes.append("Book update rate far exceeds trade rate — possible quote stuffing")
        if fake_depth_ratio > 8:
            notes.append("Displayed depth is much larger than realized trading flow — liquidity may not be genuine")
        if iceberg_score > 0.4:
            notes.append("Price levels repeatedly refilling after depletion — iceberg-style order pattern")

        return MicrostructureFlags(
            symbol=self.symbol,
            timestamp=now,
            spoof_score=round(spoof_score, 3),
            quote_stuffing_score=round(quote_stuffing_score, 3),
            fake_depth_ratio=fake_depth_ratio,
            iceberg_score=round(iceberg_score, 3),
            imbalance_flip_rate=round(flips_per_min, 2),
            notes=notes,
        )
