"""One-off check of every Roostoo endpoint the bot uses, on the TEST key only.

    python -m scripts.endpoint_check            # read-only calls
    python -m scripts.endpoint_check --trade    # also: small BUY then SELL, small short open then close

Reads the key from .env like the bot. Never run this against the competition key: the
competition account is touched only by the bot on the EC2 instance. The --trade run opens
and closes a $10 short to observe how /v3/balance reports locked USD while a short is open;
the finding is written to docs/ENDPOINT_CHECK.md.
"""
import json
import sys
import time

from bot.config import settings as S
from bot.execution.orders import floor_qty
from bot.execution.rate_limiter import RateLimiter
from bot.execution.roostoo_client import RoostooClient

PAIR = "BTC/USD"
SHORT_COLLATERAL = "10.00"
BUY_USD = 15.0


def main():
    if not (S.API_KEY and S.SECRET_KEY):
        sys.exit("set ROOSTOO_API_KEY / ROOSTOO_SECRET_KEY (TEST key) in .env first")
    trade = "--trade" in sys.argv
    c = RoostooClient(S.API_KEY, S.SECRET_KEY, RateLimiter(S.RATE_LIMIT_CALLS, S.RATE_LIMIT_WINDOW_SEC))
    out = []

    def step(name, fn):
        try:
            r = fn()
            out.append((name, "ok", r))
            print(f"[ok]   {name}: {json.dumps(r, default=str)[:300]}")
            return r
        except Exception as e:  # noqa: BLE001
            out.append((name, "FAIL", str(e)))
            print(f"[FAIL] {name}: {e}")
            return None

    st = step("serverTime", c.server_time)
    if st:
        print(f"       clock offset vs server: {int(time.time() * 1000) - st} ms (must stay within 60000)")
    info = step("exchangeInfo", c.exchange_info)
    meta = info["TradePairs"][PAIR] if info else {"AmountPrecision": 5, "MiniOrder": 1}
    tick = step("ticker", lambda: c.ticker(PAIR))
    px = float(tick[PAIR]["MinAsk"]) if tick else 0.0
    bal0 = step("balance", c.balance)
    pos0 = step("short_positions", c.short_positions)
    step("query_order (all)", lambda: c.query_order(pair=PAIR))

    if trade and px > 0 and bal0 is not None:
        qty = floor_qty(BUY_USD / px, int(meta["AmountPrecision"]))
        buy = step("place_order BUY", lambda: c.place_order(PAIR, "BUY", qty))
        if buy:
            oid = buy["OrderDetail"]["OrderID"]
            step("query_order (by id)", lambda: c.query_order(order_id=oid))
            filled = buy["OrderDetail"].get("FilledQuantity", qty)
            step("place_order SELL", lambda: c.place_order(PAIR, "SELL", floor_qty(float(filled), int(meta["AmountPrecision"]))))
        usd_before = c.balance().get("USD", {})
        so = step("short_open ($10 collateral)", lambda: c.short_open(PAIR, SHORT_COLLATERAL))
        if so:
            usd_during = c.balance().get("USD", {})
            pos = step("short_positions (open)", c.short_positions)
            sc = step("short_close (full)", lambda: c.short_close(PAIR))
            usd_after = c.balance().get("USD", {})
            coll = float(so.get("Collateral", 0) or 0)
            lock_delta = float(usd_during.get("Lock", 0) or 0) - float(usd_before.get("Lock", 0) or 0)
            free_delta = float(usd_during.get("Free", 0) or 0) - float(usd_before.get("Free", 0) or 0)
            in_lock = abs(lock_delta - coll) <= 0.02 * coll + 0.05
            finding = [
                "# Endpoint check (TEST key)", "",
                f"Run at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} against {S.ROOSTOO_URL}.", "",
                "| Step | Result |", "|---|---|",
            ] + [f"| {n} | {s} |" for n, s, _ in out] + [
                "", "## Short collateral accounting", "",
                f"- USD before short open: {json.dumps(usd_before)}",
                f"- USD while short open:  {json.dumps(usd_during)}",
                f"- USD after short close: {json.dumps(usd_after)}",
                f"- short_open response: `{json.dumps(so)}`",
                f"- short_positions while open: `{json.dumps(pos)}`",
                f"- short_close response: `{json.dumps(sc)}`", "",
                f"USD.Lock changed by {lock_delta:.2f} and USD.Free by {free_delta:.2f} for collateral {coll:.2f}.",
                ("**Finding: collateral is held in USD.Lock.** Equity = Free + (Lock - collateral) + longs + "
                 "PositionValue. The bot's detector (`detect_collateral_in_lock`) returns True for this case."
                 if in_lock else
                 "**Finding: collateral leaves the USD wallet.** Equity = Free + Lock + longs + PositionValue. "
                 "The bot's detector (`detect_collateral_in_lock`) returns False for this case."),
            ]
            with open("docs/ENDPOINT_CHECK.md", "w", encoding="utf-8") as f:
                f.write("\n".join(finding) + "\n")
            print("\nwrote docs/ENDPOINT_CHECK.md")
    fails = [n for n, s, _ in out if s == "FAIL"]
    print("\nFAILED:" if fails else "\nall steps ok", fails or "")


if __name__ == "__main__":
    main()
