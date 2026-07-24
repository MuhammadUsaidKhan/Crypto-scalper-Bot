from __future__ import annotations

import csv
import os
from dataclasses import asdict
from typing import Dict, Iterable


TRADE_HEADERS = ["timestamp", "coin", "symbol", "entry_price", "exit_price", "qty", "strategy_used", "profit_loss", "profit_loss_pct", "reason"]
EQUITY_HEADERS = ["timestamp", "equity", "cash", "open_positions"]


class TradeLogger:
    def __init__(self, csv_trade_log: str, csv_equity_log: str, sheets_config: dict):
        self.csv_trade_log = csv_trade_log
        self.csv_equity_log = csv_equity_log
        self.sheets_config = sheets_config
        self.sheet = None
        self._ensure_csv(self.csv_trade_log, TRADE_HEADERS)
        self._ensure_csv(self.csv_equity_log, EQUITY_HEADERS)
        if sheets_config.get("enabled"):
            self._setup_sheets()

    def _ensure_csv(self, path: str, headers: Iterable[str]):
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(list(headers))

    def _setup_sheets(self):
        try:
            import gspread
            gc = gspread.service_account(filename=self.sheets_config["service_account_json"])
            sh = gc.open(self.sheets_config["spreadsheet_name"])
            try:
                self.sheet = sh.worksheet(self.sheets_config["worksheet_name"])
            except gspread.WorksheetNotFound:
                self.sheet = sh.add_worksheet(title=self.sheets_config["worksheet_name"], rows=1000, cols=20)
                self.sheet.append_row(TRADE_HEADERS)
        except Exception as exc:
            print(f"Google Sheets disabled because setup failed: {exc}")
            self.sheet = None

    def log_trade(self, trade):
        row = asdict(trade)
        values = [row.get(h, "") for h in TRADE_HEADERS]
        with open(self.csv_trade_log, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(values)
        if self.sheet:
            self.sheet.append_row(values)

    def log_equity(self, timestamp: str, equity: float, cash: float, open_positions: int):
        with open(self.csv_equity_log, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([timestamp, equity, cash, open_positions])
