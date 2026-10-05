import numpy as np
import pandas as pd
import pytest

from bot.strategy.rebalance import plan_trades
from bot.strategy.risk import DrawdownControllerLegacy as DrawdownController, RiskState
from bot.strategy.signals import realized_vol, trend_signal
from bot.strategy.sizing import target_weights_legacy


def _close(series_by_coin):
    return pd.DataFrame(series_by_coin, dtype=float)


def test_trend_signal_long_short_flat():
    n = 300
    up = np.linspace(100, 200, n)                      # steady rise: long
    down = np.linspace(200, 100, n)                    # steady fall: short
    flat = np.full(n, 100.0)                           # no move: close == EMA, ret == 0 -> flat
    sig = trend_signal(_close({"UP": up, "DN": down, "FL": flat}), n=50, ret_lookback=84)
    assert sig["UP"].iloc[-1] == 1
    assert sig["DN"].iloc[-1] == -1
    assert sig["FL"].iloc[-1] == 0
    assert (sig.iloc[:84] == 0).all().all()            # warm-up rows are flat


def test_trend_signal_requires_both_conditions():
    # 170 bars at 100, 50 bars at 400, 80 bars at 300: the last close (300) is above EMA(100)
    # (~298) but the 84-bar return is 300/400 - 1 < 0, so the signal must be flat
    x = np.concatenate([np.full(170, 100.0), np.full(50, 400.0), np.full(80, 300.0)])
    sig = trend_signal(_close({"X": x}), n=100, ret_lookback=84)
    assert sig["X"].iloc[-1] == 0


def test_realized_vol_scale():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, 2000)
    px = 100 * np.exp(np.cumsum(r))
    v = realized_vol(_close({"X": px}), lookback=180, bars_per_year=2190)
    assert abs(v["X"].iloc[-1] - 0.01 * np.sqrt(2190)) < 0.1


def test_legacy_target_weights_caps():
    sig = {"A": 1, "B": -1, "C": 0, "D": 1}
    vol = {"A": 0.10, "B": 0.50, "C": 0.3, "D": 2.0}
    w = target_weights_legacy(sig, vol, target_vol=0.25, max_weight=0.25, max_gross=0.95)
    assert w["A"] == 0.25                     # 0.0625/0.10 = 0.625 -> capped
    assert w["B"] == pytest.approx(-0.125)    # 0.0625/0.5
    assert w["C"] == 0.0
    assert w["D"] == pytest.approx(0.03125)
    assert sum(abs(x) for x in w.values()) <= 0.95 + 1e-12


def test_legacy_target_weights_gross_cap_and_size_mult():
    sig = {c: 1 for c in "ABCDEFGH"}
    vol = {c: 0.05 for c in "ABCDEFGH"}      # each raw weight 0.625 -> capped 0.25 -> gross 2.0
    w = target_weights_legacy(sig, vol, 0.25, 0.25, 0.95, size_mult=0.5)
    assert sum(w.values()) == pytest.approx(0.95 * 0.5)
    assert all(x == pytest.approx(0.95 / 8 * 0.5) for x in w.values())


def test_plan_trades_band():
    t = {"A": 0.10, "B": -0.20, "C": 0.0}
    c = {"A": 0.08, "B": 0.0, "C": 0.05}
    out = plan_trades(t, c, band=0.03)
    assert [x["coin"] for x in out] == ["B", "C"]


def test_legacy_drawdown_controller_cycle():
    rc = DrawdownController(RiskState(), dd_stop=0.08, cooldown_sec=24 * 3600, reduced_size=0.5)
    assert rc.update(100_000, 0)["reason"] == "normal"
    assert rc.update(105_000, 1)["reason"] == "normal"         # new peak
    r = rc.update(96_000, 2)                                    # -8.6% from 105k
    assert r["flat"] and r["reason"] == "stop"
    assert rc.update(97_000, 3600)["reason"] == "cooldown"     # still flat
    r = rc.update(97_000, 2 + 24 * 3600)                        # cooldown over
    assert r["reason"] == "resume" and r["size_mult"] == 0.5
    assert rc.update(98_000, 2 + 25 * 3600)["size_mult"] == 0.5   # below old peak: half size
    r = rc.update(106_000, 2 + 26 * 3600)                       # new all-time peak
    assert r["size_mult"] == 1.0 and r["reason"] == "normal"
    # the stop reference was reset at resume: an 8% drop from the post-resume peak fires again
    r = rc.update(97_000, 2 + 27 * 3600)
    assert r["reason"] == "stop" and rc.s.stops == 2


def test_risk_state_roundtrip():
    s = RiskState(peak=1.0, ref_peak=0.9, cooldown_until=5, size_mult=0.5, stops=1)
    assert RiskState.from_dict(s.to_dict()) == s
    assert RiskState.from_dict({"peak": 2.0, "unknown": 1}).peak == 2.0
