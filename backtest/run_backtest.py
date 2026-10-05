"""Phase 2 backtest: both EMA variants, 2022-01 to the latest closed bar, 14-day windows.

    python -m backtest.run_backtest            # writes backtest/RESULTS.md and backtest/out/*.csv
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
SELECT_UNTIL = "2026-01-01"   # variant chosen on windows before this; 2026 is the holdout
OUT = os.path.join(S.ROOT, "backtest", "out")


def pct(x, d=2):
    return "n/a" if not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def num(x):
    return "n/a" if not np.isfinite(x) else f"{x:.2f}"


def main():
    os.makedirs(OUT, exist_ok=True)
    opn, cls = load_panel(S.UNIVERSE, START, refresh="--refresh" in sys.argv)
    t_from = pd.Timestamp(TRADE_FROM, tz="UTC")
    t_sel = pd.Timestamp(SELECT_UNTIL, tz="UTC")
    print(f"panel: {len(cls)} bars {cls.index[0]} .. {cls.index[-1]}")

    results, curves = {}, {}
    for n in S.EMA_VARIANTS:
        sim = Simulator(S.FEE_TAKER, S.SLIPPAGE, n, S.RET_LOOKBACK, S.VOL_LOOKBACK, S.BARS_PER_YEAR,
                        S.TARGET_VOL, S.MAX_WEIGHT, S.MAX_GROSS, S.NO_TRADE_BAND,
                        S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE)
        curve = sim.run(opn, cls, t_from)
        curve.to_csv(os.path.join(OUT, f"equity_ema{n}.csv"))
        win = windows_table(curve["equity"], t_from)
        win.to_csv(os.path.join(OUT, f"windows_ema{n}.csv"), index=False)
        results[n] = (curve, win)
        print(f"EMA {n}: done, {len(win)} windows, trades {int(curve['trades_cum'].iloc[-1])}")

    # BTC buy-and-hold on the same bars (close-to-close, no fees: the benchmark is a reference)
    btc = cls["BTC/USD"].copy()
    btc.index = btc.index + pd.Timedelta(hours=4)
    btc = btc[btc.index >= t_from]
    btc_curve = 100_000.0 * btc / btc.iloc[0]
    btc_win = windows_table(btc_curve, t_from)
    btc_win.to_csv(os.path.join(OUT, "windows_btc.csv"), index=False)

    def block(curve, win, label, mask):
        w = win[mask]
        s = summarize(w)
        e = curve[(curve.index >= w["start"].min()) & (curve.index <= w["end"].max())]
        trades = int(e["trades_cum"].iloc[-1] - e["trades_cum"].iloc[0]) if "trades_cum" in e else 0
        fees = float(e["fees_cum"].iloc[-1] - e["fees_cum"].iloc[0]) if "fees_cum" in e else 0.0
        tot = float(e.iloc[-1] / e.iloc[0] - 1) if isinstance(e, pd.Series) else float(e["equity"].iloc[-1] / e["equity"].iloc[0] - 1)
        eq = e if isinstance(e, pd.Series) else e["equity"]
        return (f"| {label} | {s['windows']} | {pct(s['median_ret'])} | {pct(s['mean_ret'])} | "
                f"{s['pos_share'] * 100:.0f}% | {num(s['median_composite'])} | {num(s['mean_composite'])} | "
                f"{pct(tot)} | {pct(max_drawdown(eq.values))} | {trades} | ${fees:,.0f} |")

    header = ("| Run | Windows | Median window ret | Mean window ret | Positive | Median composite | "
              "Mean composite | Period return | Max DD | Trades | Fees |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|")

    L = ["# Backtest results (Phase 2)\n",
         f"Panel: Binance 4h klines for {len(S.UNIVERSE)} coins, trading from {TRADE_FROM} to "
         f"{cls.index[-1] + pd.Timedelta(hours=4):%Y-%m-%d %H:%M} UTC (last closed bar). Fills at the next bar's "
         f"open, {S.FEE_TAKER * 100:.2f}% fee per leg plus {S.SLIPPAGE * 100:.2f}% slippage; shorts at 1x with "
         f"collateral = notional and 0.1% on open and close. Starting capital $100,000, one continuous "
         f"equity curve with the 8% drawdown stop active.\n",
         "Windows are consecutive 14-day blocks from 2022-01-01. Per-window Sharpe and Sortino use daily "
         "(00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window return over its max "
         "drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar with undefined ratios counted as 0. "
         "BTC buy-and-hold is close-to-close with no fees.\n",
         "## Selection period: 2022-01-01 to 2025-12-31\n", header]
    sel_scores = {}
    for n, (curve, win) in results.items():
        m = win["start"] < t_sel
        L.append(block(curve, win, f"EMA {n}", m))
        sel_scores[n] = float(win[m]["composite"].median())
    L.append(block(btc_curve, btc_win, "BTC buy-and-hold", btc_win["start"] < t_sel))
    chosen = max(sel_scores, key=lambda k: (sel_scores[k], -k))
    L.append(f"\n**Chosen variant: EMA {chosen}** (higher median window composite on 2022-2025: "
             + ", ".join(f"EMA {k} = {v:.2f}" for k, v in sel_scores.items()) + ").\n")

    L += ["## Holdout: 2026-01-01 to the latest window\n", header]
    for n, (curve, win) in results.items():
        L.append(block(curve, win, f"EMA {n}", win["start"] >= t_sel))
    L.append(block(btc_curve, btc_win, "BTC buy-and-hold", btc_win["start"] >= t_sel))

    L += ["\n## By year (chosen variant vs BTC)\n",
          "| Year | Windows | Median ret | Mean ret | Positive | Median composite | BTC median ret | BTC median composite |",
          "|---|---|---|---|---|---|---|---|"]
    curve, win = results[chosen]
    for y in sorted(win["start"].dt.year.unique()):
        w = win[win["start"].dt.year == y]
        b = btc_win[btc_win["start"].dt.year == y]
        L.append(f"| {y} | {len(w)} | {pct(w['ret'].median())} | {pct(w['ret'].mean())} | "
                 f"{(w['ret'] > 0).mean() * 100:.0f}% | {num(w['composite'].median())} | "
                 f"{pct(b['ret'].median())} | {num(b['composite'].median())} |")

    stops = int((curve["risk"] == "stop").sum())
    flat_bars = int(curve["risk"].isin(["stop", "cooldown"]).sum())
    sel_w = win[win["start"] < t_sel]
    btc_sel = btc_win[btc_win["start"] < t_sel]
    L += ["\n## Honest reading\n",
          f"- The chosen variant's median 14-day window composite on 2022-2025 is "
          f"{sel_w['composite'].median():.2f} against {btc_sel['composite'].median():.2f} for BTC buy-and-hold, "
          f"and its median window return is {pct(sel_w['ret'].median())} against {pct(btc_sel['ret'].median())}. "
          "The strategy does not beat holding BTC on the competition's ranking metric in a typical window; "
          "what it buys is a far smaller drawdown.",
          f"- Mean gross exposure is only {curve['gross'].mean() * 100:.0f}% of equity: with a 25% portfolio "
          "vol target split over 8 coins whose own vol is 50-100%, each position is a few percent of equity "
          "and the book is often flat. Returns per window are therefore small in both directions. This is the "
          "pre-declared design; no parameter was changed after seeing these numbers.",
          f"- {len(win)} windows is a modest sample and the per-window composite is noisy (Sortino and Calmar "
          "blow up on near-flat windows), so the EMA 50 vs 100 choice rests on a small difference."]
    L += ["\n## Risk stop activity (chosen variant)\n",
          f"- Stops fired: {stops}; bars spent flat in a cooldown: {flat_bars} of {len(curve)} "
          f"({flat_bars / len(curve) * 100:.1f}%).",
          f"- Mean gross exposure: {curve['gross'].mean() * 100:.0f}% of equity.",
          f"- Total trades: {int(curve['trades_cum'].iloc[-1])}; total fees: ${curve['fees_cum'].iloc[-1]:,.0f}.",
          "\n## Files\n",
          "- `backtest/out/equity_ema{50,100}.csv`: 4h equity, gross exposure and risk state.",
          "- `backtest/out/windows_ema{50,100}.csv`, `windows_btc.csv`: every 14-day window's metrics.",
          "\nRe-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars)."]
    with open(os.path.join(S.ROOT, "backtest", "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
