import pytest

from bot.execution.orders import Executor, floor_qty, fmt_usd
from bot.execution.portfolio import build_snapshot, detect_collateral_in_lock
from bot.execution.state import BotState

UNIVERSE = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}
TICKER = {"BTC/USD": {"MaxBid": 50_000.0, "MinAsk": 50_001.0, "LastPrice": 50_000.5},
          "ETH/USD": {"MaxBid": 2_000.0, "MinAsk": 2_000.5, "LastPrice": 2_000.2}}
META = {"BTC/USD": {"AmountPrecision": 5, "MiniOrder": 1, "CanTrade": True},
        "ETH/USD": {"AmountPrecision": 4, "MiniOrder": 1, "CanTrade": True}}


class MemLog:
    def __init__(self):
        self.rows = []

    def write(self, row):
        self.rows.append(dict(row))


class FakeClient:
    def __init__(self):
        self.calls = []

    def place_order(self, pair, side, quantity, order_type="MARKET", price=None):
        self.calls.append(("ORDER", pair, side, quantity))
        return {"Success": True, "OrderDetail": {"OrderID": len(self.calls), "FilledAverPrice": 1,
                                                 "FilledQuantity": quantity}}

    def short_open(self, pair, collateral):
        self.calls.append(("SHORT_OPEN", pair, collateral))
        return {"Success": True, "ID": len(self.calls), "EntryPrice": 1, "ShortQty": 1}

    def short_close(self, pair, close_qty=None, close_pct=None):
        self.calls.append(("SHORT_CLOSE", pair, close_qty))
        return {"Success": True, "ClosePrice": 1, "ClosedQty": close_qty or "all", "FullyClosed": close_qty is None}


def test_rounding_helpers():
    assert floor_qty(0.123456789, 5) == "0.12345"
    assert floor_qty(1234.5678, 0) == "1234"
    assert floor_qty(1e-7, 5) == "0.00000"
    assert fmt_usd(1234.5678) == "1234.56"


def test_equity_flat_account():
    s = build_snapshot({"USD": {"Free": 100_000}}, [], TICKER, UNIVERSE, None)
    assert s.equity == 100_000
    assert s.weights == {"BTC/USD": 0.0, "ETH/USD": 0.0}


def test_equity_with_long_and_short_collateral_in_lock():
    wallet = {"USD": {"Free": 70_000, "Lock": 10_000}, "BTC": {"Free": 0.4}}
    positions = [{"Pair": "ETH/USD", "ShortQty": 5, "EntryPrice": 2_000, "Collateral": 10_000,
                  "CurrentPrice": 2_000, "PositionValue": 10_000, "PositionStatus": "OPEN"}]
    s = build_snapshot(wallet, positions, TICKER, UNIVERSE, None)
    assert s.collateral_in_lock is True
    assert s.equity == pytest.approx(70_000 + 0 + 0.4 * 50_000 + 10_000)   # 100k, no double count
    assert s.weights["BTC/USD"] == pytest.approx(0.2)
    assert s.weights["ETH/USD"] == pytest.approx(-0.1)
    assert s.gross == pytest.approx(0.3)


def test_equity_when_collateral_leaves_wallet():
    wallet = {"USD": {"Free": 90_000}}                 # Lock omitted (zero fields are dropped)
    positions = [{"Pair": "ETH/USD", "ShortQty": 5, "EntryPrice": 2_000, "Collateral": 10_000,
                  "PositionValue": 10_400}]
    s = build_snapshot(wallet, positions, TICKER, UNIVERSE, True)
    assert s.collateral_in_lock is False               # detected from the data, assumption overridden
    assert s.equity == pytest.approx(100_400)


def test_detect_collateral_keeps_prior_when_ambiguous():
    assert detect_collateral_in_lock(5_000, 10_000, True) is True
    assert detect_collateral_in_lock(5_000, 10_000, False) is False
    assert detect_collateral_in_lock(0, 0, None) is None


def _snap(usd_free=100_000, coins=None, shorts=None):
    wallet = {"USD": {"Free": usd_free}}
    for c, q in (coins or {}).items():
        wallet[c] = {"Free": q}
    positions = []
    for pair, (qty, coll) in (shorts or {}).items():
        positions.append({"Pair": pair, "ShortQty": qty, "EntryPrice": TICKER[pair]["MaxBid"],
                          "Collateral": coll, "PositionValue": coll})
    return build_snapshot(wallet, positions, TICKER, UNIVERSE, True)


def test_executor_dry_run_sends_nothing_but_logs():
    c, logm = FakeClient(), MemLog()
    ex = Executor(c, META, live=False, order_log=logm)
    ex.execute([{"coin": "BTC/USD", "from": 0.0, "to": 0.10}], _snap())
    assert c.calls == []
    assert len(logm.rows) == 1 and logm.rows[0]["response"] == "DRY_RUN"
    assert logm.rows[0]["quantity"] == "0.20000"      # 10% of 100k at 50k, 5 decimals


def test_executor_flip_closes_before_opening_and_orders_reductions_first():
    c, logm = FakeClient(), MemLog()
    ex = Executor(c, META, live=True, order_log=logm)
    snap = _snap(usd_free=60_000, coins={"BTC": 0.4}, shorts={"ETH/USD": (10, 20_000)})
    # BTC: long 0.2 -> short -0.1 (flip); ETH: short -0.2 -> long +0.05 (flip)
    trades = [{"coin": "ETH/USD", "from": -0.2, "to": 0.05}, {"coin": "BTC/USD", "from": 0.2, "to": -0.1}]
    ex.execute(trades, snap)
    # pass 1 closes both old sides, pass 2 opens the new ones; each flip closes before it opens
    assert c.calls == [("SHORT_CLOSE", "ETH/USD", None),
                       ("ORDER", "BTC/USD", "SELL", "0.40000"),
                       ("ORDER", "ETH/USD", "BUY", "2.5000"),        # 5% of 100k equity at 2000
                       ("SHORT_OPEN", "BTC/USD", "10000.00")]        # 10% of 100k as collateral
    assert all(r["mode"] == "live" and r["response"].startswith("{") for r in logm.rows)


def test_executor_skips_below_mini_order_and_respects_cash():
    c, logm = FakeClient(), MemLog()
    ex = Executor(c, META, live=True, order_log=logm)
    snap = _snap(usd_free=100.0, coins={"ETH": 25})                      # equity 50,100, cash 100
    ex.execute([{"coin": "BTC/USD", "from": 0.0, "to": 0.5}], snap)   # wants $25,050, has $100
    assert c.calls == [("ORDER", "BTC/USD", "BUY", "0.00197")]           # (100-1)/1.001 / 50k, floored
    c.calls.clear()
    ex.execute([{"coin": "ETH/USD", "from": 0.0, "to": 0.000005}], _snap())  # $0.50 < MiniOrder
    assert c.calls == []


def test_executor_reduce_short_partially_and_close_when_dust():
    c, logm = FakeClient(), MemLog()
    ex = Executor(c, META, live=True, order_log=logm)
    snap = _snap(usd_free=80_000, shorts={"ETH/USD": (10, 20_000)})   # short 10 ETH = -0.2
    ex.execute([{"coin": "ETH/USD", "from": -0.2, "to": -0.1}], snap)
    assert c.calls == [("SHORT_CLOSE", "ETH/USD", "5.0000")]
    c.calls.clear()
    ex.execute([{"coin": "ETH/USD", "from": -0.2, "to": -0.000004}], snap)  # remainder $0.40 < $1 -> close all
    assert c.calls == [("SHORT_CLOSE", "ETH/USD", None)]


def test_state_roundtrip(tmp_path):
    p = str(tmp_path / "state.json")
    s = BotState(p)
    s.risk.peak = 123.0
    s.last_bar_ts = 42
    s.collateral_in_lock = False
    s.save()
    t = BotState(p)
    assert t.risk.peak == 123.0 and t.last_bar_ts == 42 and t.collateral_in_lock is False
