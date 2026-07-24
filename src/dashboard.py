from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import List, Dict

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live


class TerminalDashboard:
    def __init__(self):
        self.console = Console()
        self.live = None

    def render(self, universe: List[dict], positions: List[dict], recent_trades: List, equity: float, cash: float):
        table = Table(title="Crypto Scalper Paper Bot")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Updated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
        table.add_row("Equity", f"{equity:,.2f} USDT")
        table.add_row("Cash", f"{cash:,.2f} USDT")
        table.add_row("Open positions", str(len(positions)))
        table.add_row("Universe", ", ".join(c.get("symbol", "").upper() for c in universe[:20]))

        pos = Table(title="Open Positions")
        for col in ["Symbol", "Entry", "Current", "Qty", "PnL %", "Stop", "TP"]:
            pos.add_column(col)
        for p in positions:
            pos.add_row(
                p["symbol"], f"{p['entry_price']:.6g}", f"{p['current_price']:.6g}", f"{p['qty']:.5g}",
                f"{p['unrealized_pnl_pct']:.2f}%", f"{p['stop_loss']:.6g}", f"{p['take_profit']:.6g}"
            )

        trades = Table(title="Recent Closed Trades")
        for col in ["Time", "Symbol", "Entry", "Exit", "PnL", "Reason"]:
            trades.add_column(col)
        for t in recent_trades[-8:]:
            trades.add_row(t.timestamp[:19], t.symbol, f"{t.entry_price:.6g}", f"{t.exit_price:.6g}", f"{t.profit_loss:.2f} ({t.profit_loss_pct:.2f}%)", t.reason[:40])

        return Panel.fit(table, title="Status"), pos, trades

    def update(self, universe, positions, recent_trades, equity, cash):
        renderables = self.render(universe, positions, recent_trades, equity, cash)
        group = "\n".join("")
        self.console.clear()
        for item in renderables:
            self.console.print(item)


def write_html_dashboard(path: str, universe: List[dict], positions: List[dict], recent_trades: List, equity: float, cash: float):
    pos_rows = "".join(
        f"<tr><td>{escape(p['symbol'])}</td><td>{p['entry_price']:.8g}</td><td>{p['current_price']:.8g}</td><td>{p['qty']:.6g}</td><td>{p['unrealized_pnl_pct']:.2f}%</td><td>{p['stop_loss']:.8g}</td><td>{p['take_profit']:.8g}</td></tr>"
        for p in positions
    ) or "<tr><td colspan='7'>No open positions</td></tr>"
    trade_rows = "".join(
        f"<tr><td>{escape(t.timestamp[:19])}</td><td>{escape(t.symbol)}</td><td>{t.entry_price:.8g}</td><td>{t.exit_price:.8g}</td><td>{t.profit_loss:.2f}</td><td>{t.profit_loss_pct:.2f}%</td><td>{escape(t.reason)}</td></tr>"
        for t in recent_trades[-25:]
    ) or "<tr><td colspan='7'>No closed trades yet</td></tr>"
    coins = ", ".join(escape(c.get("symbol", "").upper()) for c in universe)
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><meta http-equiv='refresh' content='30'>
<title>Crypto Scalper Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; background:#0f172a; color:#e2e8f0; margin:24px; }}
.card {{ background:#111827; padding:18px; border-radius:16px; margin-bottom:18px; box-shadow:0 8px 24px rgba(0,0,0,.25); }}
table {{ width:100%; border-collapse:collapse; }} th,td {{ border-bottom:1px solid #334155; padding:8px; text-align:left; }}
.badge {{ display:inline-block; background:#1f2937; padding:6px 10px; border-radius:999px; margin:4px; }}
</style></head><body>
<h1>Crypto Scalper Paper Bot</h1>
<div class='card'><b>Updated:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}<br>
<b>Equity:</b> {equity:,.2f} USDT &nbsp; <b>Cash:</b> {cash:,.2f} USDT<br>
<b>Universe:</b> {coins}</div>
<div class='card'><h2>Open Positions</h2><table><tr><th>Symbol</th><th>Entry</th><th>Current</th><th>Qty</th><th>PnL %</th><th>Stop</th><th>TP</th></tr>{pos_rows}</table></div>
<div class='card'><h2>Recent Trades</h2><table><tr><th>Time</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>PnL</th><th>PnL %</th><th>Reason</th></tr>{trade_rows}</table></div>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
