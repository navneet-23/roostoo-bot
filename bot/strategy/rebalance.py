"""Turn target and current weights into a list of weight changes, applying the no-trade band."""


def plan_trades(target: dict, current: dict, band: float) -> list:
    trades = []
    for coin in target:
        t = float(target[coin])
        cur = float(current.get(coin, 0.0))
        if abs(t - cur) <= band:
            continue
        trades.append({"coin": coin, "from": cur, "to": t})
    return trades
