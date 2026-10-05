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


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    return np.log(close).diff()


def realized_vol(close: pd.DataFrame, lookback: int, bars_per_year: int) -> pd.DataFrame:
    """Annualised standard deviation of log bar returns over the trailing window."""
    return log_returns(close).rolling(lookback, min_periods=lookback).std() * np.sqrt(bars_per_year)


def cov_matrix(lr_window: np.ndarray, bars_per_year: int, min_rows: int = 2) -> np.ndarray:
    """Annualised covariance of the bar returns in `lr_window` (rows = bars, cols = coins).

    Rows with any NaN are dropped (listwise), so every pair is estimated on the same bars. The
    whole matrix is NaN if fewer than `min_rows` complete rows remain; callers then fall back
    to the diagonal. Used identically by the backtest and the live bot.
    """
    x = np.asarray(lr_window, dtype=float)
    n = x.shape[1]
    ok = np.all(np.isfinite(x), axis=1)
    if ok.sum() < min_rows:
        return np.full((n, n), np.nan)
    return np.cov(x[ok], rowvar=False, ddof=1) * bars_per_year
