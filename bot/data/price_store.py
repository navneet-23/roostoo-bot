"""Fallback price history: Roostoo LastPrice recorded once per 4h bar in state/roostoo_prices.csv.

Used only if Binance klines cannot be fetched. It accumulates from the moment the bot first
runs, so it is a thin safety net rather than a full substitute."""
import csv
import os

import pandas as pd


class PriceStore:
    FIELDS = ["bar_close_ms", "pair", "last_price"]

    def __init__(self, path: str):
        self.path = path

    def record(self, bar_close_ms: int, ticker: dict):
        new = not os.path.exists(self.path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            if new:
                w.writeheader()
            for pair, t in ticker.items():
                w.writerow({"bar_close_ms": bar_close_ms, "pair": pair, "last_price": t.get("LastPrice", "")})

    def close_panel(self, pairs: list) -> pd.DataFrame:
        """Close panel indexed by bar OPEN time (UTC) like the Binance panel, columns = pairs."""
        if not os.path.exists(self.path):
            return pd.DataFrame(columns=pairs)
        df = pd.read_csv(self.path)
        df = df[df["pair"].isin(pairs)].drop_duplicates(["bar_close_ms", "pair"], keep="last")
        panel = df.pivot(index="bar_close_ms", columns="pair", values="last_price").sort_index()
        panel.index = pd.to_datetime(panel.index - 4 * 3600 * 1000, unit="ms", utc=True)
        return panel.reindex(columns=pairs)
