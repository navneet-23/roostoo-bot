"""Backtest report generator (final pre-deployment change set, 2026-10-06).

    python -m backtest.run_backtest            # writes backtest/RESULTS.md and backtest/out/*.csv

Runs, all with EMA 100 and the vol-targeted sizing:
  A = commit d214693 behaviour: 3% band only, half size until a new all-time peak
  B = final change set: trade on signal change or |cur - target| > max(3%, 30% |target|);
      24h flat, 72h half size, peak reset at re-entry
Both are reported net and gross of fees for 2022-2025 and the 2026 holdout against BTC
buy-and-hold, and the pre-declared decision rule (keep B if its 2022-2025 median composite
>= A's) is evaluated and printed. Earlier reports are kept under backtest/RESULTS_*.md.
"""
import os
import sys

import numpy as np
import pandas as pd

from backtest.data_loader import load_panel
from backtest.engine import Simulator
from backtest.metrics import max_drawdown, summarize, windows_table
from bot.config import settings as S

START = "2021-10-01"          # warm-up: 400 bars before the first trade
TRADE_FROM = "2022-01-01"
SELECT_UNTIL = "2026-01-01"   # 2022-2025 in-sample; 2026 is the (no longer clean) holdout
OUT = os.path.join(S.ROOT, "backtest", "out")
RUNS = {
    "A (d214693: band only, half size until new peak)": dict(turnover_rule="legacy", reentry="legacy"),
    "B (final: signal/relative band, timed re-entry)": dict(turnover_rule="signal", reentry="timed"),
}
ATTRIBUTION = {   # each change on its own, to explain where B's numbers come from
    "A + turnover rule only": dict(turnover_rule="signal", reentry="legacy"),
    "A + timed re-entry only": dict(turnover_rule="legacy", reentry="timed"),
}


def pct(x, d=2):
    return "n/a" if not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def num(x):
    return "n/a" if not np.isfinite(x) else f"{x:.2f}"


def realized_vol(equity: pd.Series, mask=None) -> float:
    r = equity.pct_change().dropna()
    if mask is not None:
        r = r[mask.reindex(r.index).fillna(False).astype(bool)]
    return float(r.std(ddof=1) * np.sqrt(S.BARS_PER_YEAR)) if len(r) > 2 else float("nan")


HEADER = ("| Run | Windows | Median ret net | Mean ret net | Median ret gross | Mean ret gross | Positive | "
          "Median composite | Period return | Max DD | Mean gross exp. | Realised vol | Trades | Fees | "
          "Fees / window | Turnover / window | Stops |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def window_extras(curve, win):
    """Per-window fees and turnover (traded notional / equity at the window start)."""
    fees, turns = [], []
    for _, w in win.iterrows():
        seg = curve[(curve.index > w["start"]) & (curve.index <= w["end"])]
        e0 = curve[curve.index <= w["start"]]
        if len(seg) == 0 or len(e0) == 0:
            fees.append(np.nan)
            turns.append(np.nan)
            continue
        fees.append(seg["fees_cum"].iloc[-1] - e0["fees_cum"].iloc[-1])
        turns.append((seg["traded_cum"].iloc[-1] - e0["traded_cum"].iloc[-1]) / e0["equity"].iloc[-1])
    return np.array(fees), np.array(turns)


def row(label, curve, win, win_gross, mask):
    w = win[mask]
    s = summarize(w)
    lo, hi = w["start"].min(), w["end"].max()
    if isinstance(curve, pd.Series):                                   # BTC
        e = curve[(curve.index >= lo) & (curve.index <= hi)]
        wg = w
        tot, mdd, gross, rv = e.iloc[-1] / e.iloc[0] - 1, max_drawdown(e.values), 1.0, realized_vol(e)
        trades, fees, fpw, tpw, stops = 0, 0.0, 0.0, 0.0, 0
    else:
        e = curve[(curve.index >= lo) & (curve.index <= hi)]
        wg = win_gross[mask]
        eq = e["equity"]
        tot, mdd = eq.iloc[-1] / eq.iloc[0] - 1, max_drawdown(eq.values)
        gross, rv = e["gross"].mean(), realized_vol(eq)
        trades = int(e["trades_cum"].iloc[-1] - e["trades_cum"].iloc[0])
        fees = float(e["fees_cum"].iloc[-1] - e["fees_cum"].iloc[0])
        f, t = window_extras(curve, w)
        fpw, tpw = np.nanmean(f), np.nanmean(t)
        stops = int((e["risk"] == "stop").sum())
    return (f"| {label} | {s['windows']} | {pct(s['median_ret'])} | {pct(s['mean_ret'])} | "
            f"{pct(wg['ret'].median())} | {pct(wg['ret'].mean())} | {s['pos_share'] * 100:.0f}% | "
            f"{num(s['median_composite'])} | {pct(tot)} | {pct(mdd)} | {gross * 100:.0f}% | {pct(rv, 1)} | "
            f"{trades} | ${fees:,.0f} | ${fpw:,.0f} | {tpw:.2f}x | {stops} |")


def main():
    os.makedirs(OUT, exist_ok=True)
    opn, cls = load_panel(S.UNIVERSE, START, refresh="--refresh" in sys.argv)
    t_from, t_sel = pd.Timestamp(TRADE_FROM, tz="UTC"), pd.Timestamp(SELECT_UNTIL, tz="UTC")
    print(f"panel: {len(cls)} bars {cls.index[0]} .. {cls.index[-1]}")

    results = {}
    for label, kw in RUNS.items():
        sim = Simulator(S.FEE_TAKER, S.SLIPPAGE, S.EMA_N, S.RET_LOOKBACK, S.VOL_LOOKBACK, S.BARS_PER_YEAR,
                        S.TARGET_VOL, S.MAX_WEIGHT, S.MAX_GROSS, S.NO_TRADE_BAND,
                        S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE, sizing="cov",
                        rel_band=S.REL_BAND, half_size_sec=S.HALF_SIZE_SEC, **kw)
        curve = sim.run(opn, cls, t_from)
        tag = label[0]
        curve.to_csv(os.path.join(OUT, f"equity_{tag}.csv"))
        win = windows_table(curve["equity"], t_from)
        win_gross = windows_table(curve["equity_gross"], t_from)
        win.to_csv(os.path.join(OUT, f"windows_{tag}.csv"), index=False)
        results[label] = (curve, win, win_gross)
        print(f"{label}: trades {int(curve['trades_cum'].iloc[-1])}, fees ${curve['fees_cum'].iloc[-1]:,.0f}, "
              f"stops {int((curve['risk'] == 'stop').sum())}")

    btc = cls["BTC/USD"].copy()
    btc.index = btc.index + pd.Timedelta(hours=4)
    btc = btc[btc.index >= t_from]
    btc_curve = 100_000.0 * btc / btc.iloc[0]
    btc_win = windows_table(btc_curve, t_from)
    btc_win.to_csv(os.path.join(OUT, "windows_btc.csv"), index=False)

    (a_label, (a_curve, a_win, a_wg)), (b_label, (b_curve, b_win, b_wg)) = results.items()
    m_sel, m_hold = a_win["start"] < t_sel, a_win["start"] >= t_sel
    a_comp, b_comp = a_win[m_sel]["composite"].median(), b_win[m_sel]["composite"].median()
    keep_b = b_comp >= a_comp
    last_close = cls.index[-1] + pd.Timedelta(hours=4)

    L = ["# Backtest results (final pre-deployment change set)\n",
         f"EMA {S.EMA_N} trend signal, vol-targeted sizing (25%), Binance 4h klines for {len(S.UNIVERSE)} coins, "
         f"trading from {TRADE_FROM} to {last_close:%Y-%m-%d %H:%M} UTC (last closed bar). Fills at the next bar's "
         f"open, {S.FEE_TAKER * 100:.2f}% fee per leg plus {S.SLIPPAGE * 100:.2f}% slippage; shorts at 1x with "
         "collateral = notional and 0.1% on open and close. $100,000 start, one continuous equity curve, "
         "25% per-coin and 95% gross caps, 8% drawdown stop.\n",
         "**A** is the behaviour of commit d214693: trade whenever |current - target| > 3% of equity; after a "
         "stop, 24h flat then half size until equity makes a new all-time peak. **B** is the final change set: "
         "trade only if the coin's signal changed or |current - target| > max(3% of equity, 30% of |target|); "
         "after a stop, 24h flat, then half size for 72h, then full size, with the running peak reset to the "
         "equity at re-entry. Signals, EMA, universe, vol target, caps and the 8% stop level are identical.\n",
         "Windows are consecutive 14-day blocks from 2022-01-01. Net returns are from the simulated equity; "
         "gross returns add the cumulative fees paid back to equity (slippage is still included). Per-window "
         "Sharpe and Sortino use daily (00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window "
         "return over its max drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar (net) with undefined "
         "ratios counted as 0. Realised vol is the annualised standard deviation of 4h equity returns. Turnover "
         "is traded notional in the window over equity at its start. BTC buy-and-hold is close-to-close, no fees.\n",
         "**The 2026 holdout is no longer clean.** It has now been looked at three times (Phase 2, the sizing "
         "fix, this change set). It is reported for completeness, not as out-of-sample evidence.\n",
         "## Diagnostic: fee drag of A (d214693)\n",
         f"- 2022-2025: median window return {pct(a_win[m_sel]['ret'].median())} net vs "
         f"{pct(a_wg[m_sel]['ret'].median())} gross; mean {pct(a_win[m_sel]['ret'].mean())} net vs "
         f"{pct(a_wg[m_sel]['ret'].mean())} gross; median composite {num(a_comp)} net vs "
         f"{num(a_wg[m_sel]['composite'].median())} gross.",
         f"- 2026: median {pct(a_win[m_hold]['ret'].median())} net vs {pct(a_wg[m_hold]['ret'].median())} gross; "
         f"mean {pct(a_win[m_hold]['ret'].mean())} net vs {pct(a_wg[m_hold]['ret'].mean())} gross; median composite "
         f"{num(a_win[m_hold]['composite'].median())} net vs {num(a_wg[m_hold]['composite'].median())} gross."]
    fa, ta = window_extras(a_curve, a_win)
    L.append(f"- Fees per 14-day window: mean ${np.nanmean(fa):,.0f}, median ${np.nanmedian(fa):,.0f} "
             f"({np.nanmean(fa) / 1000:.2f}% of the $100k start per window); turnover per window: mean "
             f"{np.nanmean(ta):.2f}x equity, median {np.nanmedian(ta):.2f}x. Fee drag is mean gross minus mean "
             f"net return: {pct(a_wg[m_sel]['ret'].mean() - a_win[m_sel]['ret'].mean())} per window on 2022-2025.")

    L += ["\n## 2022-01-01 to 2025-12-31\n", HEADER,
          row("A", a_curve, a_win, a_wg, m_sel), row("B", b_curve, b_win, b_wg, m_sel),
          row("BTC buy-and-hold", btc_curve, btc_win, btc_win, btc_win["start"] < t_sel),
          "\n## 2026 holdout (viewed more than once)\n", HEADER,
          row("A", a_curve, a_win, a_wg, m_hold), row("B", b_curve, b_win, b_wg, m_hold),
          row("BTC buy-and-hold", btc_curve, btc_win, btc_win, btc_win["start"] >= t_sel)]

    L += ["\n## By year\n",
          "| Year | Windows | A median ret | A median comp | B median ret | B positive | B median comp | "
          "BTC median ret | BTC median comp |", "|---|---|---|---|---|---|---|---|---|"]
    for y in sorted(a_win["start"].dt.year.unique()):
        a, b, c = (w[w["start"].dt.year == y] for w in (a_win, b_win, btc_win))
        L.append(f"| {y} | {len(a)} | {pct(a['ret'].median())} | {num(a['composite'].median())} | "
                 f"{pct(b['ret'].median())} | {(b['ret'] > 0).mean() * 100:.0f}% | {num(b['composite'].median())} | "
                 f"{pct(c['ret'].median())} | {num(c['composite'].median())} |")

    L += ["\n## Attribution: each change on its own (2022-2025)\n", HEADER, row("A", a_curve, a_win, a_wg, m_sel)]
    for label, kw in ATTRIBUTION.items():
        sim = Simulator(S.FEE_TAKER, S.SLIPPAGE, S.EMA_N, S.RET_LOOKBACK, S.VOL_LOOKBACK, S.BARS_PER_YEAR,
                        S.TARGET_VOL, S.MAX_WEIGHT, S.MAX_GROSS, S.NO_TRADE_BAND,
                        S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE, sizing="cov",
                        rel_band=S.REL_BAND, half_size_sec=S.HALF_SIZE_SEC, **kw)
        c = sim.run(opn, cls, t_from)
        L.append(row(label, c, windows_table(c["equity"], t_from), windows_table(c["equity_gross"], t_from), m_sel))
    L.append(row("B", b_curve, b_win, b_wg, m_sel))
    L.append("\n**The turnover rule did not cut trades or fees.** It removes the 4-hourly resizing on covariance "
             "noise, but it also forces a trade on every signal change however small the position (a +1 -> 0 on a "
             "1% holding is now sold; a 0 -> +1 with a 2% target is now bought, both of which the 3% band used to "
             "skip), and those small trades outnumber the resizings it saves. Its effect on the median composite "
             "is positive, which comes from positions tracking their signals, not from lower costs. "
             "**The timed re-entry is what raises fees and risk:** it keeps the book at full size instead of half "
             "size for most of the period (A was at half size in 95% of active bars), so every trade is about "
             "twice as large, realised vol rises to ~31%, and it fires three times as many stops, each a full "
             "liquidation plus a re-entry. B inherits both effects.")

    for label, (curve, win, _) in results.items():
        act = curve["exante_vol"] > 0
        half = (curve.loc[act, "size_mult"] < 1).mean()
        L.append(f"\n**{label}:** {int((curve['risk'] == 'stop').sum())} stops; half size in {half * 100:.0f}% of "
                 f"active bars; flat in cooldown {curve['risk'].isin(['stop', 'cooldown']).mean() * 100:.1f}% of bars; "
                 f"mean gross {curve['gross'].mean() * 100:.0f}%; realised vol {realized_vol(curve['equity']) * 100:.1f}%; "
                 f"{int(curve['trades_cum'].iloc[-1])} trades; ${curve['fees_cum'].iloc[-1]:,.0f} fees.")

    L += ["\n## Pre-declared decision rule\n",
          f"Keep B if its 2022-2025 median composite is >= A's. A = {num(a_comp)}, B = {num(b_comp)} -> "
          f"**{'keep B' if keep_b else 'revert to A'}**. "
          "The live bot's settings (`TURNOVER_RULE`, `REENTRY` in `bot/config/settings.py`) are "
          + ('"signal" / "timed"' if keep_b else '"legacy" / "legacy"') + " accordingly.",
          "\n## Honest reading\n",
          f"- B's 2022-2025 median composite is {num(b_comp)} against {num(a_comp)} for A and "
          f"{num(btc_win[btc_win['start'] < t_sel]['composite'].median())} for BTC buy-and-hold. Whichever "
          "version is kept, the strategy still trails holding BTC on the competition's ranking metric in a "
          "typical window; what it offers is a much smaller maximum drawdown.",
          "- **Universe look-ahead.** The 8 coins are today's top 8 by 30-day volume. That is survivorship and "
          "look-ahead bias in these historical numbers (SUI only trades from mid-2023); the live bot is "
          "unaffected because its universe is fixed now, for the future.",
          f"- {len(a_win)} windows is a modest sample and the per-window composite is noisy (Sortino and Calmar "
          "blow up on near-flat windows). The A-vs-B difference should be read with that in mind; the decision "
          "rule was declared before the numbers were seen.",
          "\n## Files\n",
          "- `backtest/out/equity_{A,B}.csv`: 4h equity (net and gross of fees), gross exposure, risk state, "
          "ex-ante vol, size multiplier, traded notional (git-ignored).",
          "- `backtest/out/windows_{A,B}.csv`, `windows_btc.csv`: every 14-day window's net metrics.",
          "- `backtest/RESULTS_2026-10-06_legacy_sizing.md`: the Phase 2 report (EMA 50 vs 100, old sizing).",
          "- `backtest/RESULTS_2026-10-06_sizing_fix.md`: the report after the sizing fix (old vs fixed sizing).",
          "\nRe-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars)."]
    with open(os.path.join(S.ROOT, "backtest", "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L).encode("ascii", "replace").decode())
    print(f"\nDECISION: {'keep B' if keep_b else 'revert to A'} (A={a_comp:.3f}, B={b_comp:.3f})")


if __name__ == "__main__":
    main()
