"""Phase 2 backtest, re-run after the 2026-10-06 sizing fix.

    python -m backtest.run_backtest            # writes backtest/RESULTS.md and backtest/out/*.csv

Runs the chosen EMA 100 with the fixed sizing (portfolio vol targeting) and with the legacy
per-coin formula, 2022-01 to the latest closed bar, and reports 2022-2025 and the 2026
holdout separately against BTC buy-and-hold. The EMA 50 vs 100 selection was made under the
legacy sizing and is preserved in backtest/RESULTS_2026-10-06_legacy_sizing.md.
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
SELECT_UNTIL = "2026-01-01"   # 2022-2025 in-sample for the EMA choice; 2026 is the holdout
OUT = os.path.join(S.ROOT, "backtest", "out")
RUNS = {"fixed sizing (vol-targeted)": "cov", "old sizing (per-coin)": "legacy"}


def pct(x, d=2):
    return "n/a" if not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def num(x):
    return "n/a" if not np.isfinite(x) else f"{x:.2f}"


def realized_vol(equity: pd.Series, mask=None) -> float:
    r = equity.pct_change().dropna()
    if mask is not None:
        r = r[mask.reindex(r.index).fillna(False).astype(bool)]
    return float(r.std(ddof=1) * np.sqrt(S.BARS_PER_YEAR)) if len(r) > 2 else float("nan")


HEADER = ("| Run | Windows | Median ret | Mean ret | Positive | Median composite | Period return | Max DD | "
          "Mean gross | Realised vol (all bars) | Realised vol (active bars) | Trades | Fees |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def row(label, curve, win, mask):
    w = win[mask]
    s = summarize(w)
    lo, hi = w["start"].min(), w["end"].max()
    if isinstance(curve, pd.Series):                                   # BTC
        e = curve[(curve.index >= lo) & (curve.index <= hi)]
        tot, mdd, gross, rv, rva, trades, fees = e.iloc[-1] / e.iloc[0] - 1, max_drawdown(e.values), 1.0, \
            realized_vol(e), realized_vol(e), 0, 0.0
    else:
        e = curve[(curve.index >= lo) & (curve.index <= hi)]
        eq = e["equity"]
        tot, mdd = eq.iloc[-1] / eq.iloc[0] - 1, max_drawdown(eq.values)
        gross = e["gross"].mean()
        rv, rva = realized_vol(eq), realized_vol(eq, e["gross"].shift(1) > 0.01)
        trades = int(e["trades_cum"].iloc[-1] - e["trades_cum"].iloc[0])
        fees = float(e["fees_cum"].iloc[-1] - e["fees_cum"].iloc[0])
    return (f"| {label} | {s['windows']} | {pct(s['median_ret'])} | {pct(s['mean_ret'])} | {s['pos_share'] * 100:.0f}% | "
            f"{num(s['median_composite'])} | {pct(tot)} | {pct(mdd)} | {gross * 100:.0f}% | {pct(rv, 1)} | "
            f"{pct(rva, 1)} | {trades} | ${fees:,.0f} |")


def main():
    os.makedirs(OUT, exist_ok=True)
    opn, cls = load_panel(S.UNIVERSE, START, refresh="--refresh" in sys.argv)
    t_from, t_sel = pd.Timestamp(TRADE_FROM, tz="UTC"), pd.Timestamp(SELECT_UNTIL, tz="UTC")
    print(f"panel: {len(cls)} bars {cls.index[0]} .. {cls.index[-1]}")

    results = {}
    for label, mode in RUNS.items():
        sim = Simulator(S.FEE_TAKER, S.SLIPPAGE, S.EMA_N, S.RET_LOOKBACK, S.VOL_LOOKBACK, S.BARS_PER_YEAR,
                        S.TARGET_VOL, S.MAX_WEIGHT, S.MAX_GROSS, S.NO_TRADE_BAND,
                        S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE, sizing=mode)
        curve = sim.run(opn, cls, t_from)
        curve.to_csv(os.path.join(OUT, f"equity_ema{S.EMA_N}_{mode}.csv"))
        win = windows_table(curve["equity"], t_from)
        win.to_csv(os.path.join(OUT, f"windows_ema{S.EMA_N}_{mode}.csv"), index=False)
        results[label] = (curve, win)
        print(f"{label}: {len(win)} windows, trades {int(curve['trades_cum'].iloc[-1])}")

    btc = cls["BTC/USD"].copy()
    btc.index = btc.index + pd.Timedelta(hours=4)
    btc = btc[btc.index >= t_from]
    btc_curve = 100_000.0 * btc / btc.iloc[0]
    btc_win = windows_table(btc_curve, t_from)
    btc_win.to_csv(os.path.join(OUT, "windows_btc.csv"), index=False)

    fixed_curve, fixed_win = results["fixed sizing (vol-targeted)"]
    old_curve, old_win = results["old sizing (per-coin)"]
    last_close = cls.index[-1] + pd.Timedelta(hours=4)

    L = ["# Backtest results\n",
         f"EMA {S.EMA_N} trend signal on Binance 4h klines for {len(S.UNIVERSE)} coins, trading from {TRADE_FROM} "
         f"to {last_close:%Y-%m-%d %H:%M} UTC (last closed bar). Fills at the next bar's open, "
         f"{S.FEE_TAKER * 100:.2f}% fee per leg plus {S.SLIPPAGE * 100:.2f}% slippage; shorts at 1x with collateral = "
         "notional and 0.1% on open and close. $100,000 start, one continuous equity curve, the 8% drawdown stop "
         "active, 3% no-trade band, 25% per-coin and 95% gross caps.\n",
         "Two sizings are shown. **Fixed** (live since 2026-10-06): raw_i = signal_i / vol_i scaled so the ex-ante "
         "portfolio vol sqrt(w'Sigma w) is 25%, with Sigma the annualised 30-day covariance of 4h returns, caps applied after. "
         "**Old** (per-coin formula weight_i = signal_i * (25% / 8) / vol_i): what the code did before the fix; it "
         "ran the book at ~15% gross and far below the declared 25% vol. See docs/CHANGELOG.md.\n",
         "Windows are consecutive 14-day blocks from 2022-01-01. Per-window Sharpe and Sortino use daily "
         "(00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window return over its max "
         "drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar with undefined ratios counted as 0. "
         "Realised vol is the annualised standard deviation of 4h equity returns; 'active bars' are bars entered "
         "with gross exposure above 1%. BTC buy-and-hold is close-to-close with no fees.\n",
         "## 2022-01-01 to 2025-12-31\n", HEADER]
    m_sel = fixed_win["start"] < t_sel
    L.append(row("Fixed sizing", fixed_curve, fixed_win, m_sel))
    L.append(row("Old sizing", old_curve, old_win, m_sel))
    L.append(row("BTC buy-and-hold", btc_curve, btc_win, btc_win["start"] < t_sel))
    L += ["\n## Holdout: 2026-01-01 to the latest window\n", HEADER]
    m_hold = fixed_win["start"] >= t_sel
    L.append(row("Fixed sizing", fixed_curve, fixed_win, m_hold))
    L.append(row("Old sizing", old_curve, old_win, m_hold))
    L.append(row("BTC buy-and-hold", btc_curve, btc_win, btc_win["start"] >= t_sel))

    L += ["\n## By year, fixed sizing vs old sizing vs BTC\n",
          "| Year | Windows | Fixed median ret | Fixed positive | Fixed median comp | Old median ret | Old median comp | "
          "BTC median ret | BTC median comp |", "|---|---|---|---|---|---|---|---|---|"]
    for y in sorted(fixed_win["start"].dt.year.unique()):
        f, o, b = (w[w["start"].dt.year == y] for w in (fixed_win, old_win, btc_win))
        L.append(f"| {y} | {len(f)} | {pct(f['ret'].median())} | {(f['ret'] > 0).mean() * 100:.0f}% | "
                 f"{num(f['composite'].median())} | {pct(o['ret'].median())} | {num(o['composite'].median())} | "
                 f"{pct(b['ret'].median())} | {num(b['composite'].median())} |")

    act = fixed_curve["gross"].shift(1) > 0.01
    tgt = fixed_curve[fixed_curve["exante_vol"] > 0]
    full = tgt["exante_vol"] / tgt["size_mult"]                      # the target book at full size
    half_share = (tgt["size_mult"] < 1).mean()
    rv_full = realized_vol(fixed_curve["equity"], (fixed_curve["size_mult"].shift(1) == 1) & act)
    rv_half = realized_vol(fixed_curve["equity"], (fixed_curve["size_mult"].shift(1) < 1) & act)
    L += ["\n## Does the fixed sizing run at its target?\n",
          f"- Ex-ante vol of the target book at full size, when any signal is active: median {full.median() * 100:.1f}%, "
          f"mean {full.mean() * 100:.1f}%; exactly on the 25% target in {(full >= 0.249).mean() * 100:.0f}% of those "
          f"bars, below it in the rest because the 25% per-coin cap binds when only one or two coins have a signal "
          "(a single coin with 50% vol can contribute at most 12.5%). No re-levering, as specified.",
          f"- The drawdown rule halves the book after a stop until equity makes a new peak. The fixed sizing fires "
          f"{int((fixed_curve['risk'] == 'stop').sum())} stops, and the book runs at half size in {half_share * 100:.0f}% of "
          f"active bars (old sizing: {(old_curve.loc[old_curve['exante_vol'] > 0, 'size_mult'] < 1).mean() * 100:.0f}%). "
          f"Median ex-ante vol actually targeted, including that halving: {tgt['exante_vol'].median() * 100:.1f}%.",
          f"- Realised vol of the fixed-sizing equity: {realized_vol(fixed_curve['equity'], act) * 100:.1f}% on active "
          f"bars ({rv_full * 100:.1f}% at full size, {rv_half * 100:.1f}% at half size; all bars "
          f"{realized_vol(fixed_curve['equity']) * 100:.1f}%). Old sizing on active bars: "
          f"{realized_vol(old_curve['equity'], old_curve['gross'].shift(1) > 0.01) * 100:.1f}%.",
          f"- Mean gross exposure: fixed {fixed_curve['gross'].mean() * 100:.0f}%, old {old_curve['gross'].mean() * 100:.0f}%. "
          f"Share of bars with no position: fixed {(fixed_curve['gross'] < 0.01).mean() * 100:.0f}%, "
          f"old {(old_curve['gross'] < 0.01).mean() * 100:.0f}%.",
          "- Realised vol exceeds the ex-ante figure: the 30-day covariance is a noisy and, in crypto, low-biased "
          "forecast, and the 3% band leaves the held book away from its target between rebalances."]

    for label, (curve, win) in results.items():
        stops = int((curve["risk"] == "stop").sum())
        flat = int(curve["risk"].isin(["stop", "cooldown"]).sum())
        L += [f"\n**Risk stop, {label}:** {stops} stops; {flat} bars flat in cooldown "
              f"({flat / len(curve) * 100:.1f}%); {int(curve['trades_cum'].iloc[-1])} trades; "
              f"${curve['fees_cum'].iloc[-1]:,.0f} fees."]

    sel_f, sel_o, sel_b = fixed_win[m_sel], old_win[m_sel], btc_win[btc_win["start"] < t_sel]
    L += ["\n## Honest reading\n",
          f"- With the fixed sizing the median 14-day composite on 2022-2025 is {sel_f['composite'].median():.2f} "
          f"(old sizing {sel_o['composite'].median():.2f}) against {sel_b['composite'].median():.2f} for BTC "
          f"buy-and-hold; the median window return is {pct(sel_f['ret'].median())} (old {pct(sel_o['ret'].median())}) "
          f"against {pct(sel_b['ret'].median())}. The fix makes the book run at the declared risk; it does not "
          "create an edge the signal does not have, and the strategy still trails holding BTC on the ranking "
          "metric in a typical window while taking a smaller maximum drawdown.",
          "- **Universe look-ahead.** The 8 coins are today's top 8 by 30-day volume. Choosing them with today's "
          "knowledge is survivorship and look-ahead bias in this backtest: SUI only trades from mid-2023, and coins "
          "that were liquid in 2022 but faded are absent. The live bot is unaffected (its universe is fixed "
          "now, for the future), but the historical numbers above are flattered by the selection.",
          f"- {len(fixed_win)} windows is a modest sample and the per-window composite is noisy (Sortino and Calmar "
          "blow up on near-flat windows). Nothing other than the sizing formula was changed; the EMA 50 vs 100 "
          "choice stands as made in `backtest/RESULTS_2026-10-06_legacy_sizing.md`.",
          "\n## Files\n",
          f"- `backtest/out/equity_ema{S.EMA_N}_{{cov,legacy}}.csv`: 4h equity, gross, risk state, ex-ante vol (git-ignored).",
          f"- `backtest/out/windows_ema{S.EMA_N}_{{cov,legacy}}.csv`, `windows_btc.csv`: every 14-day window's metrics.",
          "- `backtest/RESULTS_2026-10-06_legacy_sizing.md`: the original Phase 2 report (EMA 50 vs 100 under the old sizing).",
          "\nRe-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars)."]
    with open(os.path.join(S.ROOT, "backtest", "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
