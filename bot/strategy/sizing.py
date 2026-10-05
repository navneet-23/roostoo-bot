"""Target weights. Weights are fractions of equity; negative means short (collateral =
|weight| * equity).

target_weights (current): portfolio-level vol targeting.
    raw_i = signal_i / vol_i, then the raw vector is scaled by k so that the ex-ante portfolio
    vol sqrt(w' Sigma w) equals target_vol, with Sigma the annualised 30-day covariance of 4h
    returns. The caps are applied afterwards (25% per coin, 95% gross); if a cap binds the
    portfolio simply runs below target. Never any leverage. All signals 0 -> cash.

target_weights_legacy (until 2026-10-06, kept for the before/after comparison):
    weight_i = signal_i * (target_vol / n) / vol_i. This treats the coins as perfectly
    correlated and divides the target by n, so the book ran at ~15% gross and well below the
    declared 25% vol. See docs/CHANGELOG.md.
"""
import math

import numpy as np


def _cap(w: dict, max_weight: float, max_gross: float, size_mult: float) -> dict:
    w = {c: max(-max_weight, min(max_weight, x)) for c, x in w.items()}
    gross = sum(abs(x) for x in w.values())
    if gross > max_gross:
        w = {c: x * max_gross / gross for c, x in w.items()}
    return {c: x * size_mult for c, x in w.items()}


def target_weights(signals: dict, vols: dict, cov: np.ndarray, target_vol: float, max_weight: float,
                   max_gross: float, size_mult: float = 1.0) -> dict:
    """signals/vols keyed by coin; cov is the annualised covariance matrix in the same coin
    order as `signals` (NaN entries allowed for coins whose signal is 0)."""
    coins = list(signals)
    raw = np.zeros(len(coins))
    for i, c in enumerate(coins):
        s, v = signals[c], vols.get(c)
        if s != 0 and v is not None and math.isfinite(v) and v > 0:
            raw[i] = s / v
    active = np.nonzero(raw)[0]
    if len(active) == 0:
        return {c: 0.0 for c in coins}
    sub = np.asarray(cov, dtype=float)[np.ix_(active, active)]
    if not np.all(np.isfinite(sub)):
        # covariance unavailable for an active coin: fall back to the diagonal (no correlation)
        sub = np.diag([vols[coins[i]] ** 2 for i in active])
    var = float(raw[active] @ sub @ raw[active])
    if var <= 0:
        return {c: 0.0 for c in coins}
    k = target_vol / math.sqrt(var)
    w = {c: float(k * raw[i]) for i, c in enumerate(coins)}
    return _cap(w, max_weight, max_gross, size_mult)


def target_weights_legacy(signals: dict, vols: dict, target_vol: float, max_weight: float,
                          max_gross: float, size_mult: float = 1.0) -> dict:
    n = len(signals)
    w = {}
    for coin, s in signals.items():
        v = vols.get(coin)
        if s == 0 or v is None or not math.isfinite(v) or v <= 0:
            w[coin] = 0.0
            continue
        w[coin] = s * (target_vol / n) / v
    return _cap(w, max_weight, max_gross, size_mult)


def ex_ante_vol(weights: dict, cov: np.ndarray) -> float:
    """sqrt(w' Sigma w) for weights in the covariance's coin order; NaN if undefined."""
    w = np.array(list(weights.values()), dtype=float)
    idx = np.nonzero(w)[0]
    if len(idx) == 0:
        return 0.0
    sub = np.asarray(cov, dtype=float)[np.ix_(idx, idx)]
    if not np.all(np.isfinite(sub)):
        return float("nan")
    return float(math.sqrt(max(w[idx] @ sub @ w[idx], 0.0)))
