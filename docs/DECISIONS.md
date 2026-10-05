# Decisions

Choices made where the brief left room, in the order they came up.

1. **Repo location.** The brief's backtest reads `../hk/cache`, so this bot lives in a sibling
   folder of the `hk` research project (`SURP/roostoo-bot`) rather than inside it. The research
   project itself (with its 1.4 GB cache) is not part of this public repo.
2. **`logs/` and `state/` are tracked as empty folders** (a `.gitkeep` each) so a fresh clone
   has the directories the bot writes to, while their contents stay ignored.
3. **Universe snapshot.** The 8 coins were ranked by 30-day mean Binance USDT quote volume
   ending 2026-10-01 (the last bar in the research cache). Result, in order: BTC, ETH, ZEC,
   SOL, XRP, NEAR, BNB, SUI. Stablecoins, PAXG and the tokenised-stock pairs (AssetType
   "stock") were excluded first. The list is fixed in `bot/config/settings.py`.
4. **Drawdown stop needs two reference levels.** After a stop and cooldown the bot resumes
   below the old peak, so a stop measured against the all-time peak would re-fire on the next
   cycle and keep the bot flat forever. The stop is therefore measured against the running
   peak since the last resume (`ref_peak`), while the return to full size is tied to a new
   all-time peak (`peak`). Both live in `state/state.json`.
5. **Weights, not quantities, are the unit of the strategy.** A weight is a fraction of equity;
   a short weight of -0.10 means collateral equal to 10% of equity. The 3% no-trade band and
   the 25% / 95% caps are all in these units.
6. **MiniOrder is read as a minimum USD notional.** exchangeInfo gives `MiniOrder: 1` for
   every pair, including BTC with 5 decimals of quantity, which only makes sense as $1 of
   notional. Orders below it are skipped; a reduction that would leave less than it closes
   the whole position instead.
7. **Collateral accounting is detected, not assumed.** The docs say collateral is "locked",
   so the default is that `/v3/balance` keeps it in `USD.Lock` and equity subtracts it once
   (PositionValue already contains it). The bot never places limit orders, so any `USD.Lock`
   while shorts are open can only be collateral; `detect_collateral_in_lock` confirms or
   overrides the default from the first cycle that has a short, and the finding is persisted
   in `state/state.json` and logged. `scripts/endpoint_check.py --trade` makes the same
   observation explicitly on the TEST key and writes it to `docs/ENDPOINT_CHECK.md`.
8. **Two-pass execution.** Every close and reduction is sent before any open or increase, so
   the cash they free funds the new positions, and buys are capped by the free USD the API
   reported (tracked through the cycle). A flip therefore closes in pass 1 and opens in pass 2.
9. **The first cycle runs at start-up.** If the last closed 4h bar has not been processed
   (fresh deploy or a restart that missed a bar), it is processed immediately rather than
   waiting up to four hours. The bar is recorded in `state/state.json` so it is never
   processed twice.
10. **Heartbeats read the account.** Every 15 minutes the bot logs equity and exposure from
    a fresh ticker + balance + short_positions read (3 calls; the limiter allows 20/min).
    This gives a continuous equity record for the judges without touching orders.
11. **A consequence of the fixed sizing worth stating.** With a 25% vol target split over 8
    coins of 50-100% vol, a single coin's target weight is usually 2-6% of equity, so the
    3% no-trade band blocks many entries from flat and the book is often small or empty
    (mean gross 15% in the backtest). This is the design as specified and was left alone.
12. **Dry run without keys is a paper account.** `MODE=dry_run` with no key uses a flat
    $100k wallet so the full pipeline can be exercised against the public endpoints.
13. **2026-10-06, sizing bug fixed before deployment.** The per-coin formula
    `signal * (target_vol / n) / vol` ran the book at ~15% gross and ~10% realised vol against a
    declared 25% target. Sizing is now portfolio-level: `raw = signal / vol` scaled so that
    `sqrt(w' Sigma w) = 25%` with Sigma the 30-day covariance of 4h returns, caps applied after
    (no re-levering when a cap binds), identical code in backtest and live bot. This is a
    correction to the declared design, not tuning: the 25% target predates every backtest and
    nothing was chosen from results. Signals, EMA 100, universe, caps, band and the drawdown
    stop are untouched. Before/after numbers are in `docs/CHANGELOG.md`; the original report is
    kept as `backtest/RESULTS_2026-10-06_legacy_sizing.md`.
14. **Covariance estimate is listwise over the trailing 180 bars.** Rows where any coin has a
    missing return are dropped so every pair is estimated on the same bars; if an active coin
    still has no covariance the sizing falls back to the diagonal (uncorrelated) matrix, which
    is the conservative direction for a vol target. The backtest and the live bot call the same
    `cov_matrix` function on the same window.
15. **The half-size rule dominates realised vol, and was left alone.** After a stop the book
    runs at half size until a new all-time peak; in the backtest that is 95% of active bars, so
    realised vol is ~20% rather than 25% even though the full-size target is hit. The rule is
    part of the specified design and the brief said not to change it.
