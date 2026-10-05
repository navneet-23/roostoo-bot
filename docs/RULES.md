# Competition rules (Roostoo Quant Trading Hackathon, live round 4-17 Oct 2026)

Recorded from the organiser's brief so that every design choice in this repo can be
checked against them.

## Venue and account
- Roostoo mock exchange (`https://mock-api.roostoo.com`); prices are streamed from Binance.
- Starting portfolio: $100,000.
- Positions are auto-liquidated at the end of the competition.

## What is allowed
- Directional strategies only. No market-making, no arbitrage.
- Long and short, both at 1x. No leverage.
- Fees: 0.1% taker (market orders), 0.05% maker (limit orders).
  Shorts: 0.1% to open and 0.1% to close.
- Rate limit: 30 API calls per minute, including queries.

## Autonomy
- The bot must trade autonomously for at least 10 days.
- No manual intervention: no manual stops, overrides or hand-made API calls.
- Every change to behaviour goes through a commit to this repository.

## Judging
1. Screen 1: trade-log integrity and commit-history transparency.
2. Screen 2: top 20 per region by total return.
3. Screen 3: rank by `0.4 * Sortino + 0.3 * Sharpe + 0.3 * Calmar`.
4. Screen 4: code review (clear logic, clean repo, runs continuously).

## Deadlines
- Repo link due before 14 Oct 2026.
- Live round: 4-17 Oct 2026.
