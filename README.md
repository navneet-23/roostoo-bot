# roostoo-bot

Autonomous volatility-scaled trend-following bot for the Roostoo Quant Trading Hackathon
(live round 4-17 October 2026). Long, short or flat on eight liquid crypto majors, rebalanced
at every 4-hour bar close, with a coded drawdown stop. No manual intervention: every change
in behaviour is a commit in this repository.

- Rules the bot is built against: [`docs/RULES.md`](docs/RULES.md)
- Every judgement call made along the way: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Backtest: [`backtest/RESULTS.md`](backtest/RESULTS.md)
- Deployment, step by step: [`DEPLOY.md`](DEPLOY.md)

## Architecture

```
bot/main.py                 loop: one cycle ~1 min after each 4h close UTC, heartbeat every 15 min
  bot/data/binance.py       closed 4h klines from Binance public API (two hosts)
  bot/data/price_store.py   fallback: Roostoo LastPrice recorded every cycle
  bot/strategy/signals.py   EMA trend + 14-day return sign  ->  {-1, 0, +1} per coin
  bot/strategy/sizing.py    vol-scaled weights, 25% per coin, 95% gross cap
  bot/strategy/risk.py      8% drawdown stop, 24h flat, half size until a new peak
  bot/strategy/rebalance.py 3% no-trade band
  bot/execution/portfolio.py  balances + short positions + MaxBid -> equity and current weights
  bot/execution/orders.py     weight changes -> market orders / short open / short close
  bot/execution/roostoo_client.py  signed REST client, Success check, retries
  bot/execution/rate_limiter.py    20 calls/min global limiter (limit is 30)
  bot/execution/state.py           state/state.json, written atomically
bot/config/settings.py      every parameter, fixed
backtest/                   simulator with the same strategy code; RESULTS.md
tests/                      37 unit tests (signing vector from the docs included)
logs/                       bot.log (rotating), orders.csv, cycles.csv, heartbeat.csv
```

Each cycle: fetch closed 4h bars → read the account from the API (never from memory) →
update the drawdown stop with current equity → compute signals, vols and target weights →
diff against current weights with the band → send closes and reductions, then opens and
increases → log everything → persist state.

## Strategy

**Universe.** The 8 most liquid Roostoo crypto pairs by Binance 30-day USDT volume
(stablecoins and tokenised stocks excluded; BTC and ETH required): BTC, ETH, ZEC, SOL, XRP,
NEAR, BNB, SUI. Fixed in `bot/config/settings.py`.

**Entry and exit (per coin, on 4h closes).** Long when close > EMA(100) and the 14-day
return > 0; short when close < EMA(100) and the 14-day return < 0; flat otherwise. A
position is exited when its signal turns flat and reversed when it flips. EMA(100) was
chosen over EMA(50) in the backtest; those two were the only pre-declared variants.

**Sizing (portfolio vol targeting).** `raw_i = signal_i / realised_vol_i`, with realised vol
the annualised 30-day standard deviation of 4h returns (2190 bars per year). The raw vector
is scaled so that the ex-ante portfolio vol `sqrt(w' Sigma w)` is 25%, where Sigma is the
annualised 30-day covariance matrix of 4h returns. Then the caps: each coin at most 25% of
equity, gross exposure (longs plus short collateral) at most 95%; if a cap binds the book
runs below target, it is never re-levered. No leverage. A short weight means collateral of
that fraction of equity at 1x. All signals zero means cash. (Until 2026-10-06 the code used a
per-coin formula that ran far below the declared target; see `docs/CHANGELOG.md`.)

**Rebalancing.** At every 4h close, a coin is traded only if its signal changed, or its
target weight differs from its current weight by more than max(3% of equity, 30% of the
target). Otherwise the position is left alone even if the vol estimates moved. Market orders
for spot, `/v6/short_open` and `/v6/short_close` for shorts; a flip closes the old side first.

**Risk rules (all coded, all autonomous).**
- Drawdown stop: if equity falls 8% below its running peak, close everything and stay flat
  for 24 hours, then trade at half size for 72 hours, then return to full size. The running
  peak is reset to the equity at re-entry. Peak, cooldown, half-size period and the previous
  signals live in `state/state.json` and survive restarts.
- Orders never exceed the free USD reported by the exchange; quantities are rounded down to
  the pair's precision and orders below the minimum size are skipped.
- If price data is unavailable the bot holds its positions and logs why.
- All exceptions are caught; the process is kept alive by systemd as well.

## Backtest summary (2022-01 to 2026-10, 4h bars, 0.1% fee + 0.05% slippage)

| Run (EMA 100, vol-targeted sizing) | 14-day windows | Median ret net | Median ret gross of fees | Positive | Median composite | Max DD | Mean gross | Realised vol | Trades | Fees |
|---|---|---|---|---|---|---|---|---|---|---|
| Live rules (B), 2022-2025 | 105 | +0.01% | +0.49% | 50% | 0.11 | -37.2% | 61% | 31.7% | 9764 | $107,563 |
| Previous rules (A, d214693), 2022-2025 | 105 | +0.02% | +0.20% | 51% | 0.08 | -29.2% | 37% | 20.5% | 7548 | $58,504 |
| BTC buy-and-hold, 2022-2025 | 105 | +0.45% | +0.45% | 54% | 0.49 | -67.2% | 100% | 50.3% | 0 | $0 |
| Live rules (B), 2026 | 19 | -0.51% | +0.28% | 42% | -0.52 | -23.1% | 60% | 24.5% | 1863 | $22,115 |
| BTC buy-and-hold, 2026 | 19 | +1.13% | +1.13% | 58% | 1.13 | -40.0% | 100% | 42.0% | 0 | $0 |

Composite = 0.4 Sortino + 0.3 Sharpe + 0.3 Calmar on daily equity within each window. The
honest reading, in full in `backtest/RESULTS.md` and `docs/CHANGELOG.md`: the strategy does
not beat holding BTC on the ranking metric in a typical window, with a smaller maximum
drawdown. Fees cost about 0.3 to 0.5 percentage points per 14-day window. The live rules
were kept by a pre-declared decision rule (B's 2022-2025 median composite 0.11 vs A's 0.08),
a difference inside the metric's noise. The 2026 column is not a clean holdout any more.
The universe is today's top 8 by volume, which flatters the backtest (look-ahead) but not the
live bot. Earlier reports are kept as `backtest/RESULTS_2026-10-06_*.md`.

## How to run

```bash
pip install -r requirements.txt
cp .env.example .env                 # fill in ROOSTOO_API_KEY, ROOSTOO_SECRET_KEY, MODE
python -m pytest -q tests            # 37 tests
python -m backtest.run_backtest      # regenerates backtest/RESULTS.md (needs ../hk/cache or downloads)
MODE=dry_run python -m bot.main      # computes and logs target trades, sends nothing
MODE=live    python -m bot.main      # trades
python -m scripts.endpoint_check [--trade]   # TEST key only: exercise every endpoint
```

With no key in `.env`, `dry_run` uses a flat $100k paper account so the whole pipeline can be
exercised against the public endpoints. See `DEPLOY.md` for the EC2 + systemd setup.
