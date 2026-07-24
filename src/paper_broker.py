from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class Position:
    symbol: str
    coin_id: str
    entry_time: str
    entry_price: float
    qty: float
    strategy: str
    stop_loss: float
    take_profit: float
    trailing_stop: float
    highest_price: float
    reason: str


@dataclass
class ClosedTrade:
    timestamp: str
    coin: str
    symbol: str
    entry_price: float
    exit_price: float
    qty: float
    strategy_used: str
    profit_loss: float
    profit_loss_pct: float
    reason: str


class PaperBroker:
    def __init__(self, starting_balance: float, fee_pct: float):
        self.cash = starting_balance
        self.starting_balance = starting_balance
        self.fee_pct = fee_pct
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[ClosedTrade] = []

    def equity(self, prices: Dict[str, float]) -> float:
        pos_value = sum(p.qty * prices.get(p.symbol, p.entry_price) for p in self.positions.values())
        return self.cash + pos_value

    def buy(self, symbol: str, coin_id: str, price: float, qty: float, strategy: str, stop_loss_pct: float, take_profit_pct: float, trailing_stop_pct: float, reason: str) -> Optional[Position]:
        if symbol in self.positions or qty <= 0:
            return None
        notional = qty * price
        fee = notional * (self.fee_pct / 100)
        if self.cash < notional + fee:
            return None
        self.cash -= notional + fee
        pos = Position(
            symbol=symbol,
            coin_id=coin_id,
            entry_time=datetime.now(timezone.utc).isoformat(),
            entry_price=price,
            qty=qty,
            strategy=strategy,
            stop_loss=price * (1 - stop_loss_pct / 100),
            take_profit=price * (1 + take_profit_pct / 100),
            trailing_stop=price * (1 - trailing_stop_pct / 100),
            highest_price=price,
            reason=reason,
        )
        self.positions[symbol] = pos
        return pos

    def maybe_update_trailing(self, symbol: str, price: float, trailing_stop_pct: float):
        pos = self.positions.get(symbol)
        if not pos:
            return
        if price > pos.highest_price:
            pos.highest_price = price
            pos.trailing_stop = max(pos.trailing_stop, price * (1 - trailing_stop_pct / 100))

    def sell(self, symbol: str, price: float, reason: str) -> Optional[ClosedTrade]:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        gross = pos.qty * price
        fee = gross * (self.fee_pct / 100)
        self.cash += gross - fee
        entry_notional = pos.qty * pos.entry_price
        exit_notional_after_fee = gross - fee
        entry_fee = entry_notional * (self.fee_pct / 100)
        pnl = exit_notional_after_fee - entry_notional - entry_fee
        pnl_pct = (pnl / entry_notional) * 100 if entry_notional else 0
        trade = ClosedTrade(
            timestamp=datetime.now(timezone.utc).isoformat(),
            coin=pos.coin_id,
            symbol=symbol,
            entry_price=pos.entry_price,
            exit_price=price,
            qty=pos.qty,
            strategy_used=pos.strategy,
            profit_loss=pnl,
            profit_loss_pct=pnl_pct,
            reason=reason,
        )
        self.closed_trades.append(trade)
        return trade

    def position_rows(self, prices: Dict[str, float]):
        rows = []
        for p in self.positions.values():
            price = prices.get(p.symbol, p.entry_price)
            pnl = (price - p.entry_price) * p.qty
            pnl_pct = ((price - p.entry_price) / p.entry_price) * 100 if p.entry_price else 0
            d = asdict(p)
            d.update({"current_price": price, "unrealized_pnl": pnl, "unrealized_pnl_pct": pnl_pct})
            rows.append(d)
        return rows
