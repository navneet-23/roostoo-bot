"""Per-window competition metrics from an equity curve.

Within each 14-day window the equity is sampled daily (00:00 UTC closes). Sharpe and Sortino
are annualised from those daily returns with sqrt(365); Calmar is the window's return over
its maximum drawdown (unannualised: annualising a 14-day return makes the ratio meaningless).
Composite = 0.4 * Sortino + 0.3 * Sharpe + 0.3 * Calmar, with any undefined ratio counted as 0.
"""
import numpy as np
import pandas as pd


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def window_stats(daily_equity: np.ndarray) -> dict:
    if len(daily_equity) < 3:
        return {"ret": np.nan, "sharpe": np.nan, "sortino": np.nan, "calmar": np.nan, "composite": np.nan}
    r = np.diff(daily_equity) / daily_equity[:-1]
    ret = daily_equity[-1] / daily_equity[0] - 1.0
    sd = r.std(ddof=1)
    dd = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))
    mdd = max_drawdown(daily_equity)
    sharpe = r.mean() / sd * np.sqrt(365) if sd > 0 else np.nan
    sortino = r.mean() / dd * np.sqrt(365) if dd > 0 else np.nan
    calmar = ret / abs(mdd) if mdd < 0 else np.nan
    nz = lambda x: 0.0 if not np.isfinite(x) else x
    comp = 0.4 * nz(sortino) + 0.3 * nz(sharpe) + 0.3 * nz(calmar)
    return {"ret": ret, "sharpe": sharpe, "sortino": sortino, "calmar": calmar, "composite": comp}


def daily_samples(equity: pd.Series) -> pd.Series:
    """Equity at 00:00 UTC bar closes."""
    idx = equity.index
    mask = (idx.hour == 0) & (idx.minute == 0)
    return equity[mask]


def windows_table(equity: pd.Series, start: pd.Timestamp, days: int = 14) -> pd.DataFrame:
    """One row per consecutive `days`-day window from `start`, computed on daily samples."""
    d = daily_samples(equity)
    rows = []
    w0 = start
    end = d.index[-1]
    while w0 + pd.Timedelta(days=days) <= end + pd.Timedelta(hours=1):
        w1 = w0 + pd.Timedelta(days=days)
        seg = d[(d.index >= w0) & (d.index <= w1)]
        st = window_stats(seg.values)
        st.update({"start": w0, "end": w1, "n_days": len(seg)})
        rows.append(st)
        w0 = w1
    return pd.DataFrame(rows)


def summarize(win: pd.DataFrame) -> dict:
    return {
        "windows": len(win),
        "median_ret": float(win["ret"].median()),
        "mean_ret": float(win["ret"].mean()),
        "pos_share": float((win["ret"] > 0).mean()),
        "median_composite": float(win["composite"].median()),
        "mean_composite": float(win["composite"].mean()),
    }
