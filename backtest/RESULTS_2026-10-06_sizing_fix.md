# Backtest results

EMA 100 trend signal on Binance 4h klines for 8 coins, trading from 2022-01-01 to 2026-10-05 20:00 UTC (last closed bar). Fills at the next bar's open, 0.10% fee per leg plus 0.05% slippage; shorts at 1x with collateral = notional and 0.1% on open and close. $100,000 start, one continuous equity curve, the 8% drawdown stop active, 3% no-trade band, 25% per-coin and 95% gross caps.

Two sizings are shown. **Fixed** (live since 2026-10-06): raw_i = signal_i / vol_i scaled so the ex-ante portfolio vol sqrt(w'Sigma w) is 25%, with Sigma the annualised 30-day covariance of 4h returns, caps applied after. **Old** (per-coin formula weight_i = signal_i * (25% / 8) / vol_i): what the code did before the fix; it ran the book at ~15% gross and far below the declared 25% vol. See docs/CHANGELOG.md.

Windows are consecutive 14-day blocks from 2022-01-01. Per-window Sharpe and Sortino use daily (00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window return over its max drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar with undefined ratios counted as 0. Realised vol is the annualised standard deviation of 4h equity returns; 'active bars' are bars entered with gross exposure above 1%. BTC buy-and-hold is close-to-close with no fees.

## 2022-01-01 to 2025-12-31

| Run | Windows | Median ret | Mean ret | Positive | Median composite | Period return | Max DD | Mean gross | Realised vol (all bars) | Realised vol (active bars) | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Fixed sizing | 105 | +0.02% | +0.38% | 51% | 0.08 | +37.34% | -29.15% | 37% | +20.5% | +20.6% | 7548 | $58,504 |
| Old sizing | 105 | +0.00% | +0.27% | 48% | 0.00 | +30.96% | -12.24% | 15% | +9.9% | +10.2% | 2967 | $16,018 |
| BTC buy-and-hold | 105 | +0.45% | +1.18% | 54% | 0.49 | +96.12% | -67.21% | 100% | +50.3% | +50.3% | 0 | $0 |

## Holdout: 2026-01-01 to the latest window

| Run | Windows | Median ret | Mean ret | Positive | Median composite | Period return | Max DD | Mean gross | Realised vol (all bars) | Realised vol (active bars) | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Fixed sizing | 19 | -0.39% | +0.70% | 47% | -0.67 | +12.98% | -15.12% | 36% | +15.5% | +15.6% | 1508 | $13,286 |
| Old sizing | 19 | -0.16% | +0.31% | 42% | -0.87 | +5.80% | -6.39% | 13% | +6.5% | +6.5% | 533 | $2,724 |
| BTC buy-and-hold | 19 | +1.13% | +0.03% | 58% | 1.13 | -6.76% | -39.98% | 100% | +42.0% | +42.0% | 0 | $0 |

## By year, fixed sizing vs old sizing vs BTC

| Year | Windows | Fixed median ret | Fixed positive | Fixed median comp | Old median ret | Old median comp | BTC median ret | BTC median comp |
|---|---|---|---|---|---|---|---|---|
| 2022 | 27 | +0.58% | 59% | 1.01 | +0.65% | 1.88 | -1.87% | -1.62 |
| 2023 | 26 | -0.91% | 35% | -2.54 | -0.50% | -2.59 | +1.67% | 1.39 |
| 2024 | 26 | +0.34% | 62% | 1.08 | +0.00% | 0.00 | +1.17% | 1.05 |
| 2025 | 26 | -0.05% | 50% | 0.03 | +0.03% | 0.22 | +0.15% | 0.25 |
| 2026 | 19 | -0.39% | 47% | -0.67 | -0.16% | -0.87 | +1.13% | 1.13 |

## Does the fixed sizing run at its target?

- Ex-ante vol of the target book at full size, when any signal is active: median 25.0%, mean 23.6%; exactly on the 25% target in 77% of those bars, below it in the rest because the 25% per-coin cap binds when only one or two coins have a signal (a single coin with 50% vol can contribute at most 12.5%). No re-levering, as specified.
- The drawdown rule halves the book after a stop until equity makes a new peak. The fixed sizing fires 17 stops, and the book runs at half size in 95% of active bars (old sizing: 89%). Median ex-ante vol actually targeted, including that halving: 12.5%.
- Realised vol of the fixed-sizing equity: 19.9% on active bars (42.4% at full size, 16.9% at half size; all bars 19.8%). Old sizing on active bars: 9.7%.
- Mean gross exposure: fixed 36%, old 15%. Share of bars with no position: fixed 1%, old 4%.
- Realised vol exceeds the ex-ante figure: the 30-day covariance is a noisy and, in crypto, low-biased forecast, and the 3% band leaves the held book away from its target between rebalances.

**Risk stop, fixed sizing (vol-targeted):** 17 stops; 102 bars flat in cooldown (1.0%); 9071 trades; $71,979 fees.

**Risk stop, old sizing (per-coin):** 2 stops; 12 bars flat in cooldown (0.1%); 3504 trades; $18,763 fees.

## Honest reading

- With the fixed sizing the median 14-day composite on 2022-2025 is 0.08 (old sizing 0.00) against 0.49 for BTC buy-and-hold; the median window return is +0.02% (old +0.00%) against +0.45%. The fix makes the book run at the declared risk; it does not create an edge the signal does not have, and the strategy still trails holding BTC on the ranking metric in a typical window while taking a smaller maximum drawdown.
- **Universe look-ahead.** The 8 coins are today's top 8 by 30-day volume. Choosing them with today's knowledge is survivorship and look-ahead bias in this backtest: SUI only trades from mid-2023, and coins that were liquid in 2022 but faded are absent. The live bot is unaffected (its universe is fixed now, for the future), but the historical numbers above are flattered by the selection.
- 124 windows is a modest sample and the per-window composite is noisy (Sortino and Calmar blow up on near-flat windows). Nothing other than the sizing formula was changed; the EMA 50 vs 100 choice stands as made in `backtest/RESULTS_2026-10-06_legacy_sizing.md`.

## Files

- `backtest/out/equity_ema100_{cov,legacy}.csv`: 4h equity, gross, risk state, ex-ante vol (git-ignored).
- `backtest/out/windows_ema100_{cov,legacy}.csv`, `windows_btc.csv`: every 14-day window's metrics.
- `backtest/RESULTS_2026-10-06_legacy_sizing.md`: the original Phase 2 report (EMA 50 vs 100 under the old sizing).

Re-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars).
