import numpy as np
import pytest

from bot.strategy.signals import cov_matrix
from bot.strategy.sizing import ex_ante_vol, target_weights, target_weights_legacy

COINS = list("ABCDEFGH")


def _cov(vols, corr=0.0):
    v = np.array(vols)
    c = np.full((len(v), len(v)), corr)
    np.fill_diagonal(c, 1.0)
    return np.outer(v, v) * c


def test_target_vol_is_hit_when_no_cap_binds():
    vols = [0.6, 0.8, 0.7, 0.9, 0.5, 0.6, 0.7, 0.8]
    cov = _cov(vols, corr=0.5)
    sig = dict(zip(COINS, [1, -1, 1, 0, 1, -1, 1, 1]))
    w = target_weights(sig, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    assert w["D"] == 0.0
    assert all(abs(x) < 0.25 for x in w.values())
    assert sum(abs(x) for x in w.values()) < 0.95
    assert ex_ante_vol(w, cov) == pytest.approx(0.25, rel=1e-9)
    assert np.sign(w["B"]) == -1 and np.sign(w["A"]) == 1


def test_target_vol_scaling_outruns_legacy_sizing():
    vols = [0.7] * 8
    cov = _cov(vols, corr=0.5)
    sig = {c: 1 for c in COINS}
    v = dict(zip(COINS, vols))
    new = target_weights(sig, v, cov, 0.25, 0.25, 0.95)
    old = target_weights_legacy(sig, v, 0.25, 0.25, 0.95)
    assert sum(new.values()) > sum(old.values())
    assert ex_ante_vol(old, cov) < 0.25 < ex_ante_vol(old, cov) * 2   # the old book ran far below target


def test_caps_bind_and_no_releveraging():
    vols = [0.05] * 8                                   # calm coins -> huge raw weights
    cov = _cov(vols, corr=0.0)
    sig = {c: 1 for c in COINS}
    w = target_weights(sig, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    assert max(abs(x) for x in w.values()) <= 0.25 + 1e-12
    assert sum(abs(x) for x in w.values()) == pytest.approx(0.95)
    assert ex_ante_vol(w, cov) < 0.25                   # accepted lower vol, no re-levering
    # a single active coin can never exceed the per-coin cap
    sig1 = {c: (1 if c == "A" else 0) for c in COINS}
    w1 = target_weights(sig1, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    assert w1["A"] == pytest.approx(0.25) and sum(abs(x) for x in w1.values()) == pytest.approx(0.25)


def test_all_zero_signals_give_cash():
    vols = [0.6] * 8
    w = target_weights({c: 0 for c in COINS}, dict(zip(COINS, vols)), _cov(vols), 0.25, 0.25, 0.95)
    assert all(x == 0.0 for x in w.values())


def test_size_mult_halves_final_weights():
    vols = [0.6, 0.8, 0.7, 0.9, 0.5, 0.6, 0.7, 0.8]
    cov = _cov(vols, corr=0.3)
    sig = dict(zip(COINS, [1, -1, 1, 0, 1, -1, 1, 1]))
    full = target_weights(sig, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    half = target_weights(sig, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95, size_mult=0.5)
    assert all(half[c] == pytest.approx(full[c] * 0.5) for c in COINS)


def test_nan_covariance_falls_back_to_diagonal_and_inactive_nan_is_ignored():
    vols = [0.6, 0.8, 0.7, 0.9, 0.5, 0.6, 0.7, 0.8]
    cov = _cov(vols, corr=0.4)
    cov[3, :] = cov[:, 3] = np.nan                        # coin D has no covariance but signal 0
    sig = dict(zip(COINS, [1, -1, 1, 0, 1, 0, 0, 0]))     # few enough coins that no cap binds
    w = target_weights(sig, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    assert ex_ante_vol(w, cov) == pytest.approx(0.25)
    cov[0, 1] = cov[1, 0] = np.nan                        # now an active pair is missing
    sig4 = dict(zip(COINS, [1, -1, 1, 0, 1, 0, 0, 0]))    # few enough coins that no cap binds
    w2 = target_weights(sig4, dict(zip(COINS, vols)), cov, 0.25, 0.25, 0.95)
    diag = np.diag(np.array(vols) ** 2)                   # fallback: uncorrelated, so the target
    assert ex_ante_vol(w2, diag) == pytest.approx(0.25)   # is hit under the diagonal matrix


def test_cov_matrix_annualises_and_drops_nan_rows():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.01, (2000, 3))
    x[5, 1] = np.nan
    c = cov_matrix(x, 2190)
    assert c.shape == (3, 3)
    assert c[0, 0] == pytest.approx(0.01 ** 2 * 2190, rel=0.1)
    assert np.isnan(cov_matrix(x[:1], 2190)).all()
