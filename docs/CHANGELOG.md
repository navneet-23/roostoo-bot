# Changelog

Every change to the bot's behaviour, dated. The competition rules forbid manual intervention,
so this file plus the commit history is the complete record of what changed and why.

## 2026-10-06 - Fix portfolio vol targeting to match the declared 25% target (sizing bug)

**What was wrong.** The design declares a portfolio volatility target of 25% annualised. The
code sized each coin as `weight_i = signal_i * (25% / 8) / vol_i`. That divides the target by
the number of coins and ignores correlation, which is only correct if all eight coins were
held at once and were perfectly correlated. In practice one to four coins have a signal at a
time, so the book ran at a mean gross exposure of 15% and a realised vol of about 10%, well
below the declared 25%.

**What changed.** `bot/strategy/sizing.py::target_weights` now sizes at the portfolio level:
`raw_i = signal_i / vol_i`, the 30-day covariance matrix of 4h returns (annualised with 2190
bars per year) is estimated with the same listwise rule in the backtest and the live bot
(`bot/strategy/signals.py::cov_matrix`), and the raw vector is scaled so that the ex-ante
portfolio vol `sqrt(w' Sigma w)` equals 25%. The existing caps (25% per coin, 95% gross) are
applied afterwards; when a cap binds the book runs below target rather than re-levering. No
leverage. All-zero signals give cash. The half-size rule after a drawdown stop still
multiplies the final weights by 0.5. The old formula is kept as `target_weights_legacy` for
the comparison below and is not used by the bot.

Nothing else changed: signals, EMA 100, universe, caps, 3% band and the drawdown stop are
as before. This is a correction of the implementation to the declared design, not a tuned
parameter: the 25% target was stated before any backtest was run and the fix does not pick
a value from results.

**Before / after** (EMA 100, 2022-01 to 2026-10-05, same data, fees, slippage, next-open fills;
full tables in `backtest/RESULTS.md`, the original report in
`backtest/RESULTS_2026-10-06_legacy_sizing.md`):

| 2022-2025, 105 windows | Median ret | Mean ret | Positive | Median composite | Max DD | Mean gross | Realised vol | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|
| Old sizing | +0.00% | +0.27% | 48% | 0.00 | -12.2% | 15% | 9.9% | 2967 | $16,018 |
| Fixed sizing | +0.02% | +0.38% | 51% | 0.08 | -29.2% | 37% | 20.5% | 7548 | $58,504 |
| BTC buy-and-hold | +0.45% | +1.18% | 54% | 0.49 | -67.2% | 100% | 50.3% | 0 | $0 |

| 2026 holdout, 19 windows | Median ret | Mean ret | Positive | Median composite | Max DD | Mean gross | Realised vol | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|
| Old sizing | -0.16% | +0.31% | 42% | -0.87 | -6.4% | 13% | 6.5% | 533 | $2,724 |
| Fixed sizing | -0.39% | +0.70% | 47% | -0.67 | -15.1% | 36% | 15.5% | 1508 | $13,286 |
| BTC buy-and-hold | +1.13% | +0.03% | 58% | 1.13 | -40.0% | 100% | 42.0% | 0 | $0 |

**Does it run at 25% now?** At full size the ex-ante vol of the target book is exactly 25% in
77% of active bars and lower in the rest because the 25% per-coin cap binds when only one or
two coins have a signal. The realised vol is 19.9% on active bars rather than 25% for a
reason that is part of the declared design, not of this fix: after a drawdown stop the book
runs at half size until equity makes a new all-time peak, and with 17 stops over the period
that is the case in 95% of active bars (89% under the old sizing too). Realised vol is 42% in
the few full-size bars (early 2022, a crash) and 17% at half size.

**Caveat added to the backtest.** The universe is today's top 8 by volume, which is
look-ahead and survivorship bias in the historical numbers (SUI only trades from mid-2023).
It does not affect the live bot, whose universe is fixed now for the future.

**Outcome.** The book now carries the risk it was declared to carry. The strategy still trails
BTC buy-and-hold on the competition's ranking metric in a typical window. No other change was
made.

## 2026-10-06 - Final pre-deployment change set (turnover rule, drawdown re-entry)

Two mechanical problems were found in the d214693 backtest. Signals, EMA 100, universe, the
25% vol target, the caps and the 8% stop level are untouched; the pre-declared decision rule
below was fixed before the numbers were seen.

**Diagnostic, A = d214693, fee drag.** 2022-2025: median 14-day return +0.02% net vs +0.20%
gross of fees, mean +0.38% net vs +0.70% gross, median composite 0.08 net vs 0.54 gross.
2026: median -0.39% net vs +0.17% gross, median composite -0.67 net vs 0.53 gross. Fees per
window: mean $580 (0.58% of the $100k start); turnover 4.4x equity per window. Fee drag is
+0.32% per window on 2022-2025.

**Problem 1, turnover.** Positions were resized at every 4h bar whenever the target moved by
more than 3% of equity, and vol-targeted weights move with every covariance estimate, so the
book churned on noise: 7,548 trades and $58.5k in fees over 2022-2025. Rule now: trade a
coin only if (a) its signal changed, or (b) |current - target| > max(3% of equity, 30% of
|target|). This is a mechanical filter on when to act on an unchanged signal, not a change
of what the signal says or how large the book should be.

**Problem 2, drawdown re-entry.** "Half size until a new all-time peak" meant one stop could
leave the bot at half size indefinitely; in the backtest it was at half size in 95% of active
bars, so the book never ran at its declared risk. Rule now: stop at -8% from the running
peak, 24h flat, then half size for 72h, then full size, with the running peak reset to the
equity at re-entry. The stop stays armed throughout. Mechanical again: it changes how the
book returns to its declared size, not the stop level or the sizing.

**Before / after** (EMA 100, vol-targeted sizing, same data, fees, slippage and fills; full
tables including the 2026 holdout and the attribution of each change in `backtest/RESULTS.md`;
the previous report is kept as `backtest/RESULTS_2026-10-06_sizing_fix.md`):

| 2022-2025, 105 windows | Median ret net | Mean ret net | Median ret gross | Mean ret gross | Positive | Median composite | Max DD | Mean gross | Realised vol | Trades | Fees | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A (d214693) | +0.02% | +0.38% | +0.20% | +0.70% | 51% | 0.08 | -29.2% | 37% | 20.5% | 7548 | $58,504 | 14 |
| B (this change set) | +0.01% | +0.37% | +0.49% | +0.91% | 50% | 0.11 | -37.2% | 61% | 31.7% | 9764 | $107,563 | 42 |
| BTC buy-and-hold | +0.45% | +1.18% | +0.45% | +1.18% | 54% | 0.49 | -67.2% | 100% | 50.3% | 0 | $0 | 0 |

| 2026, 19 windows (holdout viewed three times, no longer clean) | Median ret net | Mean ret net | Median ret gross | Positive | Median composite | Max DD | Mean gross | Realised vol | Trades | Fees | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A (d214693) | -0.39% | +0.70% | +0.17% | 47% | -0.67 | -15.1% | 36% | 15.5% | 1508 | $13,286 | 3 |
| B (this change set) | -0.51% | +0.97% | +0.28% | 42% | -0.52 | -23.1% | 60% | 24.5% | 1863 | $22,115 | 5 |
| BTC buy-and-hold | +1.13% | +0.03% | +1.13% | 58% | 1.13 | -40.0% | 100% | 42.0% | 0 | $0 | 0 |

**Decision rule (pre-declared): keep B if its 2022-2025 median composite >= A's.** B = 0.11,
A = 0.08, so B is kept and the live bot runs with `TURNOVER_RULE = "signal"` and
`REENTRY = "timed"`.

**What the numbers actually say, stated plainly.**
- The turnover rule on its own did *not* reduce trades or fees (8,070 trades and $60.4k vs
  7,548 and $58.5k). It stops the resizing on noise but forces a trade on every signal change
  however small the position, and those small trades outnumber the resizings saved. Its
  median composite on its own is 0.25, from positions tracking their signals, not from costs.
- The timed re-entry is what moves the book to its declared risk (mean gross 61%, realised
  vol ~31% against 20% for A) and, with it, doubles fees, raises the maximum drawdown from
  -29% to -37% and triples the number of stops (42 vs 14). B's realised vol is now above the
  25% target because the 30-day covariance forecast is biased low in crypto.
- B's edge over A on the decision metric is 0.03 of composite on 105 windows, which is inside
  the noise of that metric. The rule was pre-declared, so B is kept, but this is not evidence
  that B is better.
- Whichever version runs, the strategy still trails BTC buy-and-hold on the ranking metric in
  a typical window, with a smaller maximum drawdown.
