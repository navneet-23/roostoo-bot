"""4h klines from Binance's public REST API (no key needed).

Tries api.binance.com first, then data-api.binance.vision. Returns only CLOSED bars.
"""
import logging
import time

import pandas as pd
import requests

from bot.config import settings as S

log = logging.getLogger(__name__)

COLUMNS = ["ts", "open", "high", "low", "close", "volume", "close_ts", "qvol"]


def _get(path, params):
    last_err = None
    for base in S.BINANCE_URLS:
        for attempt in range(S.MAX_RETRIES):
            try:
                r = requests.get(base + path, params=params, timeout=S.HTTP_TIMEOUT_SEC)
                if r.status_code == 200:
                    return r.json()
                last_err = f"HTTP {r.status_code} from {base}: {r.text[:200]}"
            except requests.RequestException as e:  # network error, timeout, bad JSON
                last_err = f"{type(e).__name__}: {e}"
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Binance klines unavailable: {last_err}")


def fetch_klines(symbol: str, interval: str = S.BAR, limit: int = S.HISTORY_BARS,
                 start_ms: int = None, end_ms: int = None) -> pd.DataFrame:
    """Up to `limit` bars ending now (or at end_ms), or paginated forward from start_ms."""
    frames = []
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    while True:
        raw = _get("/api/v3/klines", params)
        if not raw:
            break
        df = pd.DataFrame([[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                            float(k[5]), int(k[6]), float(k[7])] for k in raw], columns=COLUMNS)
        frames.append(df)
        if start_ms is None or len(raw) < params["limit"]:
            break
        params["startTime"] = int(raw[-1][0]) + 1   # next page
        if end_ms is not None and params["startTime"] > end_ms:
            break
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(frames, ignore_index=True).drop_duplicates("ts").sort_values("ts")
    now_ms = int(time.time() * 1000)
    out = out[out["close_ts"] < now_ms]            # drop the bar still in progress
    return out.reset_index(drop=True)


def fetch_close_panel(universe: dict, limit: int = S.HISTORY_BARS) -> pd.DataFrame:
    """Closed-bar close prices, index = bar open time (UTC), columns = Roostoo pairs."""
    cols = {}
    for pair, symbol in universe.items():
        df = fetch_klines(symbol, limit=limit)
        cols[pair] = df.set_index("ts")["close"]
    panel = pd.DataFrame(cols)
    panel.index = pd.to_datetime(panel.index, unit="ms", utc=True)
    return panel.sort_index()
