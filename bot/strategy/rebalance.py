"""Turn target and current weights into a list of weight changes.

Current rule (since the 2026-10-06 final change set): a coin is traded only if
  (a) its signal changed since the last decision (0 -> +1, +1 -> -1, +1 -> 0, ...), or
  (b) |current - target| > max(band, rel_band * |target|)   (3% of equity, 30% of the target).
Otherwise the position is left alone even if the vol estimates moved. This stops the book
being resized every 4h on covariance noise.

Legacy rule (A, kept for the comparison): trade whenever |current - target| > band.
Pass signals=None (or rel_band=0 with no signals) to get it.
"""


def plan_trades(target: dict, current: dict, band: float, signals: dict = None,
                prev_signals: dict = None, rel_band: float = 0.0) -> list:
    trades = []
    for coin in target:
        t = float(target[coin])
        cur = float(current.get(coin, 0.0))
        diff = abs(t - cur)
        changed = False
        if signals is not None:
            prev = (prev_signals or {}).get(coin)
            changed = prev is None or int(signals.get(coin, 0)) != int(prev)
        threshold = max(band, rel_band * abs(t))
        if not changed and diff <= threshold:
            continue
        if changed and diff <= 1e-12:
            continue
        trades.append({"coin": coin, "from": cur, "to": t})
    return trades
