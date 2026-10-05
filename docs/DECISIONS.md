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
