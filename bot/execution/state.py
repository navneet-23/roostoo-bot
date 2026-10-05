"""Persistent bot state (state/state.json), written atomically so a crash mid-write cannot
leave a truncated file. Holds the drawdown-stop state, the last processed bar and the
collateral-accounting finding. Restarts never reset any of it."""
import json
import os
import time

from bot.strategy.risk import RiskState


class BotState:
    def __init__(self, path: str):
        self.path = path
        self.risk = RiskState()
        self.last_bar_ts = 0            # ms open time of the last bar acted on
        self.collateral_in_lock = None  # None = not yet observed; see docs/DECISIONS.md
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            d = json.load(f)
        self.risk = RiskState.from_dict(d.get("risk", {}))
        self.last_bar_ts = int(d.get("last_bar_ts", 0))
        self.collateral_in_lock = d.get("collateral_in_lock")

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        d = {"risk": self.risk.to_dict(), "last_bar_ts": self.last_bar_ts,
             "collateral_in_lock": self.collateral_in_lock,
             "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, self.path)
