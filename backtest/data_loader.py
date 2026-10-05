"""Build the 4h open/close panel for the backtest.

Primary source: the cached Binance Vision klines in ../hk/cache/4h/raw/<SYMBOL>.parquet
(columns ts, open, close, bvol, qvol; ts = bar open time in ms). Whatever is missing after
the cache's last bar is topped up from Binance's public API, so the panel runs to the
latest closed bar. The merged panel is cached under backtest/data/ (git-ignored).
"""
import os

import pandas as pd

from bot.config import settings as S
from bot.data.binance import fetch_klines

HK_CACHE = os.path.join(S.ROOT, "..", "hk", "cache", "4h", "raw")
OUT_DIR = os.path.join(S.ROOT, "backtest", "data")


def load_symbol(symbol: str, start_ms: int) -> pd.DataFrame:
    f = os.path.join(HK_CACHE, f"{symbol}.parquet")
    if os.path.exists(f):
        df = pd.read_parquet(f)[["ts", "open", "close"]]
        df = df[df["ts"] >= start_ms]
        last = int(df["ts"].max())
        top = fetch_klines(symbol, start_ms=last + S.BAR_MS)
        if len(top):
            df = pd.concat([df, top[["ts", "open", "close"]]], ignore_index=True)
    else:
        top = fetch_klines(symbol, start_ms=start_ms)
        df = top[["ts", "open", "close"]]
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def load_panel(universe: dict, start: str, refresh: bool = False):
    """Returns (open, close) DataFrames indexed by UTC bar open time, columns = Roostoo pairs."""
    os.makedirs(OUT_DIR, exist_ok=True)
    f = os.path.join(OUT_DIR, f"panel_{start}.parquet")
    if os.path.exists(f) and not refresh:
        panel = pd.read_parquet(f)
    else:
        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        frames = []
        for pair, symbol in universe.items():
            df = load_symbol(symbol, start_ms)
            df["pair"] = pair
            frames.append(df)
        panel = pd.concat(frames, ignore_index=True)
        panel.to_parquet(f, index=False)
    idx = pd.to_datetime(sorted(panel["ts"].unique()), unit="ms", utc=True)
    opn = panel.pivot(index="ts", columns="pair", values="open")
    cls = panel.pivot(index="ts", columns="pair", values="close")
    opn.index = pd.to_datetime(opn.index, unit="ms", utc=True)
    cls.index = pd.to_datetime(cls.index, unit="ms", utc=True)
    # a regular grid; a coin listed later is NaN before its first bar
    opn = opn.reindex(idx)
    cls = cls.reindex(idx)
    return opn[list(universe)], cls[list(universe)]
