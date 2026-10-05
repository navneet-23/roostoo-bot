"""Read the account as it actually is (balances, short positions, prices) and derive equity
and current weights. Nothing here is remembered between cycles: every call re-reads the API.

Equity = USD free + USD locked (less short collateral if the exchange keeps it in Lock)
       + sum(long qty * MaxBid) + sum(short PositionValue)

PositionValue = Collateral + UnrealizedPNL, so collateral must not also be counted inside the
USD wallet. Whether /v3/balance reports locked collateral in USD.Lock is detected from the
data (see detect_collateral_in_lock) and persisted; until a short exists it makes no difference.
"""
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Snapshot:
    usd_free: float = 0.0
    usd_lock: float = 0.0
    coins: dict = field(default_factory=dict)      # coin -> qty (free + lock)
    shorts: dict = field(default_factory=dict)     # pair -> {qty, entry, collateral, value}
    prices: dict = field(default_factory=dict)     # pair -> MaxBid
    equity: float = 0.0
    weights: dict = field(default_factory=dict)    # pair -> signed exposure / equity
    collateral_in_lock: bool = True
    raw: dict = field(default_factory=dict)

    @property
    def gross(self):
        return sum(abs(w) for w in self.weights.values())


def detect_collateral_in_lock(usd_lock: float, total_collateral: float, current):
    """True if USD.Lock matches the open shorts' collateral, False if Lock is ~0 while
    collateral is held, otherwise the previous finding (or True, the documented default)."""
    if total_collateral <= 0:
        return current
    if abs(usd_lock - total_collateral) <= 0.01 * total_collateral + 1.0:
        return True
    if usd_lock < 0.01 * total_collateral:
        return False
    return current


def build_snapshot(wallet: dict, positions: list, ticker: dict, universe: dict,
                   collateral_in_lock) -> Snapshot:
    s = Snapshot(raw={"wallet": wallet, "positions": positions})
    usd = wallet.get("USD", {})
    s.usd_free = float(usd.get("Free", 0) or 0)
    s.usd_lock = float(usd.get("Lock", 0) or 0)
    for coin, v in wallet.items():
        if coin == "USD":
            continue
        q = float(v.get("Free", 0) or 0) + float(v.get("Lock", 0) or 0)
        if q > 0:
            s.coins[coin] = q
    for p in positions:
        if p.get("PositionStatus", "OPEN") != "OPEN":
            continue
        pair = p["Pair"]
        s.shorts[pair] = {"qty": float(p.get("ShortQty", 0) or 0), "entry": float(p.get("EntryPrice", 0) or 0),
                          "collateral": float(p.get("Collateral", 0) or 0),
                          "value": float(p.get("PositionValue", 0) or 0)}
    for pair, t in ticker.items():
        s.prices[pair] = float(t.get("MaxBid", 0) or t.get("LastPrice", 0) or 0)
    total_coll = sum(x["collateral"] for x in s.shorts.values())
    s.collateral_in_lock = detect_collateral_in_lock(s.usd_lock, total_coll,
                                                     True if collateral_in_lock is None else collateral_in_lock)
    usd_lock_adj = s.usd_lock - total_coll if s.collateral_in_lock else s.usd_lock
    equity = s.usd_free + usd_lock_adj
    for coin, q in s.coins.items():
        pair = f"{coin}/USD"
        px = s.prices.get(pair)
        if px:
            equity += q * px
    for pair, sh in s.shorts.items():
        equity += sh["value"]
    s.equity = equity
    if equity > 0:
        for pair in universe:
            coin = pair.split("/")[0]
            w = 0.0
            px = s.prices.get(pair, 0.0)
            if coin in s.coins:
                w += s.coins[coin] * px / equity
            if pair in s.shorts:
                w -= s.shorts[pair]["qty"] * px / equity
            s.weights[pair] = w
    return s


def fetch_snapshot(client, universe: dict, collateral_in_lock) -> Snapshot:
    ticker = client.ticker()
    wallet = client.balance()
    positions = client.short_positions()
    return build_snapshot(wallet, positions, ticker, universe, collateral_in_lock)


def paper_snapshot(ticker: dict, universe: dict, cash: float = 100_000.0) -> Snapshot:
    """A flat $100k account, for dry runs without API keys."""
    return build_snapshot({"USD": {"Free": cash, "Lock": 0}}, [], ticker, universe, True)
