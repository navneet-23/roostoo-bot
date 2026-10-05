"""Turn weight changes into Roostoo orders.

- Spot longs: MARKET orders; quantity rounded down to AmountPrecision; orders whose notional is
  below MiniOrder (USD) are skipped.
- Shorts: /v6/short_open sized by USD collateral (2 decimals, min $1); reduced or closed with
  /v6/short_close by quantity, or fully with no quantity.
- A long and a short on the same coin never coexist: a flip closes first, then opens.
- Reductions and closes are sent before increases and opens so freed cash funds the buys, and
  buys never exceed the free USD actually available.
- MODE=dry_run logs what would be sent and sends nothing.
"""
import json
import logging
import math
import time

from bot.execution.roostoo_client import RoostooError, RoostooUnavailable

log = logging.getLogger(__name__)


def floor_qty(qty: float, precision: int) -> str:
    f = 10 ** precision
    q = math.floor(qty * f + 1e-9) / f
    return f"{q:.{precision}f}"


def fmt_usd(x: float) -> str:
    return f"{math.floor(x * 100) / 100:.2f}"


class Executor:
    def __init__(self, client, pair_meta: dict, live: bool, order_log, fee: float = 0.001):
        self.client = client
        self.meta = pair_meta          # pair -> {"AmountPrecision", "MiniOrder", "CanTrade"}
        self.live = live
        self.order_log = order_log     # CsvLogger
        self.fee = fee

    # --- single legs ------------------------------------------------------------------------
    def _send(self, kind, pair, reason, **kw):
        """Send one leg (or log it in dry run). Returns the API response dict or None."""
        rec = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pair": pair,
               "side": kind, "type": "MARKET", "price": "", "quantity": kw.get("quantity", ""),
               "collateral": kw.get("collateral", ""), "order_id": "", "mode": "live" if self.live else "dry_run",
               "reason": reason, "response": ""}
        if not self.live:
            rec["response"] = "DRY_RUN"
            self.order_log.write(rec)
            log.info("dry_run %s %s %s", kind, pair, {k: v for k, v in kw.items()})
            return None
        try:
            if kind == "BUY" or kind == "SELL":
                resp = self.client.place_order(pair, kind, kw["quantity"])
                od = resp.get("OrderDetail", {})
                rec["order_id"] = od.get("OrderID", "")
                rec["price"] = od.get("FilledAverPrice", od.get("Price", ""))
                rec["quantity"] = od.get("FilledQuantity", kw["quantity"])
            elif kind == "SHORT_OPEN":
                resp = self.client.short_open(pair, kw["collateral"])
                rec["order_id"] = resp.get("ID", "")
                rec["price"] = resp.get("EntryPrice", "")
                rec["quantity"] = resp.get("ShortQty", "")
            elif kind == "SHORT_CLOSE":
                resp = self.client.short_close(pair, close_qty=kw.get("quantity"))
                rec["price"] = resp.get("ClosePrice", "")
                rec["quantity"] = resp.get("ClosedQty", "")
            else:
                raise ValueError(kind)
            rec["response"] = json.dumps(resp, separators=(",", ":"))
            log.info("sent %s %s %s -> %s", kind, pair, kw, rec["response"][:300])
            return resp
        except (RoostooError, RoostooUnavailable) as e:
            rec["response"] = f"ERROR {e}"
            log.error("order failed %s %s %s: %s", kind, pair, kw, e)
            return None
        finally:
            self.order_log.write(rec)

    # --- weight changes -------------------------------------------------------------------
    def execute(self, trades: list, snap, reason_by_pair: dict = None) -> list:
        """trades: [{"coin": pair, "from": w, "to": w}], weights as fractions of equity."""
        reason_by_pair = reason_by_pair or {}
        results = []
        usd_free = snap.usd_free
        # closes and reductions first, then opens and increases
        order = sorted(trades, key=lambda t: 0 if abs(t["to"]) < abs(t["from"]) or t["from"] * t["to"] < 0 else 1)
        for tr in order:
            pair, w_from, w_to = tr["coin"], tr["from"], tr["to"]
            meta = self.meta.get(pair)
            px = snap.prices.get(pair, 0.0)
            if not meta or not meta.get("CanTrade", True) or px <= 0:
                log.warning("skip %s: no metadata or price", pair)
                continue
            prec, mini = int(meta.get("AmountPrecision", 0)), float(meta.get("MiniOrder", 1) or 1)
            coin = pair.split("/")[0]
            reason = reason_by_pair.get(pair, "")
            equity = snap.equity
            held_long = snap.coins.get(coin, 0.0)
            held_short = snap.shorts.get(pair, {}).get("qty", 0.0)

            # 1. flips: close the old side completely
            if w_from > 0 and w_to <= 0 and held_long > 0:
                q = floor_qty(held_long, prec)
                if float(q) * px >= mini:
                    r = self._send("SELL", pair, reason + " close long", quantity=q)
                    results.append(r)
                    usd_free += float(q) * px * (1 - self.fee)
                w_from = 0.0
            elif w_from < 0 and w_to >= 0 and held_short > 0:
                r = self._send("SHORT_CLOSE", pair, reason + " close short")
                results.append(r)
                usd_free += snap.shorts[pair]["value"] * (1 - self.fee)
                w_from = 0.0

            delta = w_to - w_from
            notional = abs(delta) * equity
            if notional < mini:
                continue
            # 2. adjust within the same side
            if w_to > 0:
                if delta > 0:
                    spend = min(notional, max(usd_free - 1.0, 0.0) / (1 + self.fee))
                    q = floor_qty(spend / px, prec)
                    if float(q) > 0 and float(q) * px >= mini:
                        results.append(self._send("BUY", pair, reason, quantity=q))
                        usd_free -= float(q) * px * (1 + self.fee)
                else:
                    q_f = min(notional / px, held_long)
                    if (held_long - q_f) * px < mini:      # do not leave dust
                        q_f = held_long
                    q = floor_qty(q_f, prec)
                    if float(q) > 0 and float(q) * px >= mini:
                        results.append(self._send("SELL", pair, reason, quantity=q))
                        usd_free += float(q) * px * (1 - self.fee)
            elif w_to < 0:
                if delta < 0:
                    coll = min(notional, max(usd_free - 1.0, 0.0) / (1 + self.fee))
                    if coll >= max(mini, 1.0):
                        results.append(self._send("SHORT_OPEN", pair, reason, collateral=fmt_usd(coll)))
                        usd_free -= coll * (1 + self.fee)
                else:
                    q_f = min(notional / px, held_short)
                    if (held_short - q_f) * px < mini:
                        results.append(self._send("SHORT_CLOSE", pair, reason + " close short"))
                        usd_free += snap.shorts[pair]["value"] * (1 - self.fee)
                    else:
                        q = floor_qty(q_f, prec)
                        if float(q) > 0:
                            results.append(self._send("SHORT_CLOSE", pair, reason, quantity=q))
                            usd_free += float(q) * px * (1 - self.fee)
        return results
