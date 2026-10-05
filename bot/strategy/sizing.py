"""Volatility-scaled target weights with per-coin and gross caps.

Weights are fractions of equity; negative means short (collateral = |weight| * equity).
"""
import math


def target_weights(signals: dict, vols: dict, target_vol: float, max_weight: float,
                   max_gross: float, size_mult: float = 1.0) -> dict:
    n = len(signals)
    w = {}
    for coin, s in signals.items():
        v = vols.get(coin)
        if s == 0 or v is None or not math.isfinite(v) or v <= 0:
            w[coin] = 0.0
            continue
        raw = s * (target_vol / n) / v
        w[coin] = max(-max_weight, min(max_weight, raw))
    gross = sum(abs(x) for x in w.values())
    if gross > max_gross:
        w = {c: x * max_gross / gross for c, x in w.items()}
    return {c: x * size_mult for c, x in w.items()}
