"""Trend signal: +1 long, -1 short, 0 flat, per coin and bar.

long  if close > EMA(N) and the 14-day return > 0
short if close < EMA(N) and the 14-day return < 0
flat  otherwise, and whenever either input is undefined.
"""
import numpy as np
import pandas as pd


def ema(close: pd.DataFrame, n: int) -> pd.DataFrame:
    return close.ewm(span=n, adjust=False, min_periods=n).mean()


def trend_signal(close: pd.DataFrame, n: int, ret_lookback: int) -> pd.DataFrame:
    e = ema(close, n)
    r = close / close.shift(ret_lookback) - 1.0
    up = (close > e) & (r > 0)
    dn = (close < e) & (r < 0)
    sig = np.where(up, 1, np.where(dn, -1, 0))
    sig = pd.DataFrame(sig, index=close.index, columns=close.columns)
    sig = sig.where(~(e.isna() | r.isna()), 0)
    return sig.astype(int)


def realized_vol(close: pd.DataFrame, lookback: int, bars_per_year: int) -> pd.DataFrame:
    """Annualised standard deviation of log bar returns over the trailing window."""
    lr = np.log(close).diff()
    return lr.rolling(lookback, min_periods=lookback).std() * np.sqrt(bars_per_year)
