"""Rotating text log plus append-only CSV logs (orders, cycles, heartbeats)."""
import csv
import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str, name: str = "bot.log") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    fmt.converter = __import__("time").gmtime
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        fh = RotatingFileHandler(os.path.join(log_dir, name), maxBytes=5_000_000, backupCount=10, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(fh)
        root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return root


class CsvLogger:
    def __init__(self, path: str, fields: list):
        self.path, self.fields = path, fields
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, row: dict):
        new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in self.fields})


ORDER_FIELDS = ["timestamp", "pair", "side", "type", "price", "quantity", "collateral", "order_id",
                "mode", "reason", "response"]
CYCLE_FIELDS = ["timestamp", "bar_open_utc", "mode", "equity", "usd_free", "usd_lock", "gross",
                "risk_reason", "size_mult", "peak", "ref_peak", "cooldown_until", "signals",
                "target_weights", "current_weights", "trades_planned", "orders_sent", "price_source",
                "collateral_in_lock", "rate_limit_used", "note"]
HEARTBEAT_FIELDS = ["timestamp", "mode", "equity", "usd_free", "gross", "n_longs", "n_shorts",
                    "next_cycle_utc", "note"]
