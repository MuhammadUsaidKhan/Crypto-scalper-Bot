from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionSizingResult:
    qty: float
    notional: float
    stop_loss_pct: float
    take_profit_pct: float


def size_position(balance: float, price: float, risk_per_trade_pct: float, stop_loss_pct: float, max_allocation_pct: float) -> PositionSizingResult:
    risk_amount = balance * (risk_per_trade_pct / 100)
    stop_distance = price * (stop_loss_pct / 100)
    qty_by_risk = risk_amount / stop_distance if stop_distance > 0 else 0
    max_notional = balance * (max_allocation_pct / 100)
    qty_by_allocation = max_notional / price if price > 0 else 0
    qty = max(0, min(qty_by_risk, qty_by_allocation))
    return PositionSizingResult(qty=qty, notional=qty * price, stop_loss_pct=stop_loss_pct, take_profit_pct=0.0)
