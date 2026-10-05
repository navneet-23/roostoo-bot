# Backtest results (Phase 2)

Panel: Binance 4h klines for 8 coins, trading from 2022-01-01 to 2026-10-05 20:00 UTC (last closed bar). Fills at the next bar's open, 0.10% fee per leg plus 0.05% slippage; shorts at 1x with collateral = notional and 0.1% on open and close. Starting capital $100,000, one continuous equity curve with the 8% drawdown stop active.

Windows are consecutive 14-day blocks from 2022-01-01. Per-window Sharpe and Sortino use daily (00:00 UTC) equity samples annualised with sqrt(365); Calmar is the window return over its max drawdown; composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar with undefined ratios counted as 0. BTC buy-and-hold is close-to-close with no fees.

## Selection period: 2022-01-01 to 2025-12-31

| Run | Windows | Median window ret | Mean window ret | Positive | Median composite | Mean composite | Period return | Max DD | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|---|
| EMA 50 | 105 | -0.02% | +0.22% | 44% | -0.18 | 0.50 | +24.17% | -13.39% | 3244 | $15,578 |
| EMA 100 | 105 | +0.00% | +0.27% | 48% | 0.00 | 0.92 | +30.96% | -12.24% | 2967 | $16,018 |
| BTC buy-and-hold | 105 | +0.45% | +1.18% | 54% | 0.49 | 3.43 | +96.12% | -67.21% | 0 | $0 |

**Chosen variant: EMA 100** (higher median window composite on 2022-2025: EMA 50 = -0.18, EMA 100 = 0.00).

## Holdout: 2026-01-01 to the latest window

| Run | Windows | Median window ret | Mean window ret | Positive | Median composite | Mean composite | Period return | Max DD | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|---|
| EMA 50 | 19 | -0.14% | +0.04% | 37% | -0.35 | -0.49 | +0.37% | -13.34% | 1054 | $5,850 |
| EMA 100 | 19 | -0.16% | +0.31% | 42% | -0.87 | 0.91 | +5.80% | -6.39% | 533 | $2,724 |
| BTC buy-and-hold | 19 | +1.13% | +0.03% | 58% | 1.13 | 1.91 | -6.76% | -39.98% | 0 | $0 |

## By year (chosen variant vs BTC)

| Year | Windows | Median ret | Mean ret | Positive | Median composite | BTC median ret | BTC median composite |
|---|---|---|---|---|---|---|---|
| 2022 | 27 | +0.65% | +0.86% | 63% | 1.88 | -1.87% | -1.62 |
| 2023 | 26 | -0.50% | -0.09% | 27% | -2.59 | +1.67% | 1.39 |
| 2024 | 26 | +0.00% | +0.33% | 46% | 0.00 | +1.17% | 1.05 |
| 2025 | 26 | +0.03% | -0.03% | 54% | 0.22 | +0.15% | 0.25 |
| 2026 | 19 | -0.16% | +0.31% | 42% | -0.87 | +1.13% | 1.13 |

## Honest reading

- The chosen variant's median 14-day window composite on 2022-2025 is 0.00 against 0.49 for BTC buy-and-hold, and its median window return is +0.00% against +0.45%. The strategy does not beat holding BTC on the competition's ranking metric in a typical window; what it buys is a far smaller drawdown.
- Mean gross exposure is only 15% of equity: with a 25% portfolio vol target split over 8 coins whose own vol is 50-100%, each position is a few percent of equity and the book is often flat. Returns per window are therefore small in both directions. This is the pre-declared design; no parameter was changed after seeing these numbers.
- 124 windows is a modest sample and the per-window composite is noisy (Sortino and Calmar blow up on near-flat windows), so the EMA 50 vs 100 choice rests on a small difference.

## Risk stop activity (chosen variant)

- Stops fired: 2; bars spent flat in a cooldown: 12 of 10433 (0.1%).
- Mean gross exposure: 15% of equity.
- Total trades: 3504; total fees: $18,763.

## Files

- `backtest/out/equity_ema{50,100}.csv`: 4h equity, gross exposure and risk state.
- `backtest/out/windows_ema{50,100}.csv`, `windows_btc.csv`: every 14-day window's metrics.

Re-run with `python -m backtest.run_backtest` (add `--refresh` to re-download the top-up bars).
