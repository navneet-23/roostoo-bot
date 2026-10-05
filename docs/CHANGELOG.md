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
