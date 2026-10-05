"""Tests for the final pre-deployment change set: the turnover rule and the timed re-entry."""
from bot.strategy.rebalance import plan_trades
from bot.strategy.risk import DrawdownController, DrawdownControllerLegacy, RiskState

H = 3600


# --- turnover rule ---------------------------------------------------------------------------
def test_no_trade_on_vol_noise_without_signal_change():
    sig = {"A": 1, "B": -1}
    prev = {"A": 1, "B": -1}
    target = {"A": 0.12, "B": -0.10}
    current = {"A": 0.10, "B": -0.085}          # moved 2% / 1.5% of equity, < 30% of target
    assert plan_trades(target, current, 0.03, sig, prev, 0.30) == []


def test_trade_when_move_exceeds_relative_or_absolute_band():
    sig = prev = {"A": 1, "B": 1, "C": 1}
    target = {"A": 0.20, "B": 0.05, "C": 0.05}
    current = {"A": 0.13, "B": 0.03, "C": 0.08}   # A: 7% > max(3%, 6%); B: 2% <= 3%; C: 3% <= 3%
    out = plan_trades(target, current, 0.03, sig, prev, 0.30)
    assert [t["coin"] for t in out] == ["A"]


def test_trade_on_every_kind_of_signal_change():
    prev = {"A": 0, "B": 1, "C": 1, "D": -1}
    sig = {"A": 1, "B": -1, "C": 0, "D": 0}
    target = {"A": 0.02, "B": -0.02, "C": 0.0, "D": 0.0}   # tiny targets, inside every band
    current = {"A": 0.0, "B": 0.02, "C": 0.01, "D": -0.01}
    out = plan_trades(target, current, 0.03, sig, prev, 0.30)
    assert [t["coin"] for t in out] == ["A", "B", "C", "D"]
    assert out[1] == {"coin": "B", "from": 0.02, "to": -0.02}       # flip: executor closes first


def test_first_cycle_without_previous_signals_trades_to_target():
    out = plan_trades({"A": 0.01, "B": 0.0}, {"A": 0.0, "B": 0.0}, 0.03, {"A": 1, "B": 0}, None, 0.30)
    assert [t["coin"] for t in out] == ["A"]                       # B: nothing to do, diff is 0


def test_legacy_band_rule_unchanged():
    assert plan_trades({"A": 0.10}, {"A": 0.08}, 0.03) == []
    assert plan_trades({"A": 0.10}, {"A": 0.06}, 0.03) == [{"coin": "A", "from": 0.06, "to": 0.10}]


# --- timed re-entry --------------------------------------------------------------------------
def test_timed_reentry_cycle():
    rc = DrawdownController(RiskState(), 0.08, 24 * H, 0.5, half_size_sec=72 * H)
    assert rc.update(100_000, 0)["reason"] == "normal"
    assert rc.update(110_000, 1 * H)["reason"] == "normal"               # peak 110k
    r = rc.update(101_000, 2 * H)                                         # -8.2%
    assert r == {"flat": True, "size_mult": 0.0, "reason": "stop"} and rc.s.stops == 1
    assert rc.update(90_000, 10 * H)["reason"] == "cooldown"             # flat during the 24h
    r = rc.update(95_000, 2 * H + 24 * H)                                 # re-entry
    assert r["reason"] == "resume" and r["size_mult"] == 0.5
    assert rc.s.peak == 95_000                                            # running peak reset
    assert rc.update(96_000, 2 * H + 50 * H)["size_mult"] == 0.5          # still inside the 72h
    r = rc.update(96_000, 2 * H + 24 * H + 72 * H)                        # 72h over: full size
    assert r["size_mult"] == 1.0 and r["reason"] == "normal"
    assert rc.s.peak == 96_000 and rc.s.half_until == 0
    # no new all-time peak was needed: equity never exceeded the original 110k


def test_stop_stays_armed_at_half_size_against_reset_peak():
    rc = DrawdownController(RiskState(), 0.08, 24 * H, 0.5, half_size_sec=72 * H)
    rc.update(100_000, 0)
    rc.update(90_000, 1 * H)                                              # stop
    rc.update(90_000, 1 * H + 24 * H)                                     # resume, peak = 90k
    rc.update(92_000, 1 * H + 30 * H)                                     # running peak 92k
    r = rc.update(84_000, 1 * H + 31 * H)                                 # -8.7% from 92k
    assert r["reason"] == "stop" and rc.s.stops == 2


def test_state_persists_timed_fields_and_legacy_still_works():
    s = RiskState(peak=1, cooldown_until=5, half_until=9, size_mult=0.5, stops=2)
    assert RiskState.from_dict(s.to_dict()) == s
    rc = DrawdownControllerLegacy(RiskState(), 0.08, 24 * H, 0.5)
    rc.update(100_000, 0)
    rc.update(91_000, 1)
    assert rc.update(91_000, 1 + 24 * H)["size_mult"] == 0.5
    assert rc.update(95_000, 2 + 24 * H + 72 * H)["size_mult"] == 0.5    # legacy: no timed return
    assert rc.update(101_000, 3 + 24 * H + 72 * H)["size_mult"] == 1.0   # only a new peak restores
