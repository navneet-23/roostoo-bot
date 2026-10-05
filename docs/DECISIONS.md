# Decisions

Choices made where the brief left room, in the order they came up.

1. **Repo location.** The brief's backtest reads `../hk/cache`, so this bot lives in a sibling
   folder of the `hk` research project (`SURP/roostoo-bot`) rather than inside it. The research
   project itself (with its 1.4 GB cache) is not part of this public repo.
2. **`logs/` and `state/` are tracked as empty folders** (a `.gitkeep` each) so a fresh clone
   has the directories the bot writes to, while their contents stay ignored.
