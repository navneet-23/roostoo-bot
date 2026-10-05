# Backtest results (final pre-deployment change set)

EMA 100 trend signal, vol-targeted sizing (25%), Binance 4h klines for 8 coins, trading from 2022-01-01 to 2026-10-05 20:00 UTC (last closed bar). Fills at the next bar's open, 0.10% fee per leg plus 0.05% slippage; shorts at 1x with collateral = notional and 0.1% on open and close. $100,000 start, one continuous equity curve, 25% per-coin and 95% gross caps, 8% drawdown stop.

**A** is the behaviour of commit d214693: trade whenever |current - target| > 3% of equity; after a stop, 24h flat then half size until equity makes a new all-time peak. **B** is the final change set: trade only if the coin's signal changed or |current - target| > max(3% of equity, 30% of |target|); after a stop, 24h flat, then half size for 72h, then full size, with the running peak reset to the equity at re-entry. Signals, EMA, universe, vol target, caps and the 8% stop level are identical.

Windows are consecutive 14-day blocks from 2022-01-01. Net returns are from the simulated equity; gross returns add the cumulative fees paid back to equity (slippage is still included). Per-window Sharpe and Sortino use daily (00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window return over its max drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar (net) with undefined ratios counted as 0. Realised vol is the annualised standard deviation of 4h equity returns. Turnover is traded notional in the window over equity at its start. BTC buy-and-hold is close-to-close, no fees.

**The 2026 holdout is no longer clean.** It has now been looked at three times (Phase 2, the sizing fix, this change set). It is reported for completeness, not as out-of-sample evidence.

## Diagnostic: fee drag of A (d214693)

- 2022-2025: median window return +0.02% net vs +0.20% gross; mean +0.38% net vs +0.70% gross; median composite 0.08 net vs 0.54 gross.
- 2026: median -0.39% net vs +0.17% gross; mean +0.70% net vs +0.80% gross; median composite -0.67 net vs 0.53 gross.
- Fees per 14-day window: mean $580, median $545 (0.58% of the $100k start per window); turnover per window: mean 4.40x equity, median 4.12x. Fee drag is mean gross minus mean net return: +0.32% per window on 2022-2025.

## 2022-01-01 to 2025-12-31

| Run | Windows | Median ret net | Mean ret net | Median ret gross | Mean ret gross | Positive | Median composite | Period return | Max DD | Mean gross exp. | Realised vol | Trades | Fees | Fees / window | Turnover / window | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 105 | +0.02% | +0.38% | +0.20% | +0.70% | 51% | 0.08 | +37.34% | -29.15% | 37% | +20.5% | 7548 | $58,504 | $558 | 4.32x | 14 |
| B | 105 | +0.01% | +0.37% | +0.49% | +0.91% | 50% | 0.11 | +23.98% | -37.18% | 61% | +31.7% | 9764 | $107,563 | $1,030 | 8.29x | 42 |
| BTC buy-and-hold | 105 | +0.45% | +1.18% | +0.45% | +1.18% | 54% | 0.49 | +96.12% | -67.21% | 100% | +50.3% | 0 | $0 | $0 | 0.00x | 0 |

## 2026 holdout (viewed more than once)

| Run | Windows | Median ret net | Mean ret net | Median ret gross | Mean ret gross | Positive | Median composite | Period return | Max DD | Mean gross exp. | Realised vol | Trades | Fees | Fees / window | Turnover / window | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 19 | -0.39% | +0.70% | +0.17% | +0.80% | 47% | -0.67 | +12.98% | -15.12% | 36% | +15.5% | 1508 | $13,286 | $699 | 4.83x | 3 |
| B | 19 | -0.51% | +0.97% | +0.28% | +0.94% | 42% | -0.52 | +16.63% | -23.05% | 60% | +24.5% | 1863 | $22,115 | $1,164 | 8.43x | 5 |
| BTC buy-and-hold | 19 | +1.13% | +0.03% | +1.13% | +0.03% | 58% | 1.13 | -6.76% | -39.98% | 100% | +42.0% | 0 | $0 | $0 | 0.00x | 0 |

## By year

| Year | Windows | A median ret | A median comp | B median ret | B positive | B median comp | BTC median ret | BTC median comp |
|---|---|---|---|---|---|---|---|---|
| 2022 | 27 | +0.58% | 1.01 | +0.97% | 59% | 0.68 | -1.87% | -1.62 |
| 2023 | 26 | -0.91% | -2.54 | -2.30% | 35% | -2.48 | +1.67% | 1.39 |
| 2024 | 26 | +0.34% | 1.08 | +0.33% | 54% | 0.71 | +1.17% | 1.05 |
| 2025 | 26 | -0.05% | 0.03 | +0.11% | 54% | 0.22 | +0.15% | 0.25 |
| 2026 | 19 | -0.39% | -0.67 | -0.51% | 42% | -0.52 | +1.13% | 1.13 |

## Attribution: each change on its own (2022-2025)

| Run | Windows | Median ret net | Mean ret net | Median ret gross | Mean ret gross | Positive | Median composite | Period return | Max DD | Mean gross exp. | Realised vol | Trades | Fees | Fees / window | Turnover / window | Stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 105 | +0.02% | +0.38% | +0.20% | +0.70% | 51% | 0.08 | +37.34% | -29.15% | 37% | +20.5% | 7548 | $58,504 | $558 | 4.32x | 14 |
| A + turnover rule only | 105 | +0.08% | +0.40% | +0.27% | +0.73% | 50% | 0.25 | +39.89% | -27.80% | 37% | +20.6% | 8070 | $60,444 | $577 | 4.46x | 14 |
| A + timed re-entry only | 105 | -0.37% | +0.43% | +0.34% | +0.99% | 46% | -0.28 | +32.50% | -32.56% | 62% | +32.1% | 11196 | $118,890 | $1,139 | 8.79x | 42 |
| B | 105 | +0.01% | +0.37% | +0.49% | +0.91% | 50% | 0.11 | +23.98% | -37.18% | 61% | +31.7% | 9764 | $107,563 | $1,030 | 8.29x | 42 |

**The turnover rule did not cut trades or fees.** It removes the 4-hourly resizing on covariance noise, but it also forces a trade on every signal change however small the position (a +1 -> 0 on a 1% holding is now sold; a 0 -> +1 with a 2% target is now bought, both of which the 3% band used to skip), and those small trades outnumber the resizings it saves. Its effect on the median composite is positive, which comes from positions tracking their signals, not from lower costs. **The timed re-entry is what raises fees and risk:** it keeps the book at full size instead of half size for most of the period (A was at half size in 95% of active bars), so every trade is about twice as large, realised vol rises to ~31%, and it fires three times as many stops, each a full liquidation plus a re-entry. B inherits both effects.

**A (d214693: band only, half size until new peak):** 17 stops; half size in 95% of active bars; flat in cooldown 1.0% of bars; mean gross 36%; realised vol 19.8%; 9071 trades; $71,979 fees.

**B (final: signal/relative band, timed re-entry):** 47 stops; half size in 6% of active bars; flat in cooldown 2.7% of bars; mean gross 61%; realised vol 30.7%; 11640 trades; $129,832 fees.

## Pre-declared decision rule

Keep B if its 2022-2025 median composite is >= A's. A = 0.08, B = 0.11 -> **keep B**. The live bot's settings (`TURNOVER_RULE`, `REENTRY` in `bot/config/settings.py`) are "signal" / "timed" accordingly.

## Honest reading

- B's 2022-2025 median composite is 0.11 against 0.08 for A and 0.49 for BTC buy-and-hold. Whichever version is kept, the strategy still trails holding BTC on the competition's ranking metric in a typical window; what it offers is a much smaller maximum drawdown.
- **Universe look-ahead.** The 8 coins are today's top 8 by 30-day volume. That is survivorship and look-ahead bias in these historical numbers (SUI only trades from mid-2023); the live bot is unaffected because its universe is fixed now, for the future.
- 124 windows is a modest sample and the per-window composite is noisy (Sortino and Calmar blow up on near-flat windows). The A-vs-B difference should be read with that in mind; the decision rule was declared before the numbers were seen.

## Files

- `backtest/out/equity_{A,B}.csv`: 4h equity (net and gross of fees), gross exposure, risk state, ex-ante vol, size multiplier, traded notional (git-ignored).
- `backtest/out/windows_{A,B}.csv`, `windows_btc.csv`: every 14-day window's net metrics.
- `backtest/RESULTS_2026-10-06_legacy_sizing.md`: the Phase 2 report (EMA 50 vs 100, old sizing).
- `backtest/RESULTS_2026-10-06_sizing_fix.md`: the report after the sizing fix (old vs fixed sizing).

Re-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars).
