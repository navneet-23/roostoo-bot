"""Turn weight changes into Roostoo orders.

- Spot longs: MARKET orders; quantity rounded down to AmountPrecision; orders whose notional is
  below MiniOrder (USD) are skipped.
- Shorts: /v6/short_open sized by USD collateral (2 decimals, min $1); reduced with
  /v6/short_close by quantity, or closed fully with no quantity.
- A long and a short on the same coin never coexist: a flip closes first, then opens.
- Two passes per cycle: every close and reduction first, then every open and increase, so the
  cash freed by the first pass funds the second. A buy or short open never exceeds the free
  USD actually available (tracked through the cycle from the API-reported balance).
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
        self.usd_free = 0.0

    # --- one leg ------------------------------------------------------------------------------
    def _send(self, kind, pair, reason, **kw):
        """Send one leg (or log it in dry run). Returns the API response dict or None."""
        rec = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pair": pair,
               "side": kind, "type": "MARKET", "price": "", "quantity": kw.get("quantity", ""),
               "collateral": kw.get("collateral", ""), "order_id": "",
               "mode": "live" if self.live else "dry_run", "reason": reason, "response": ""}
        if not self.live:
            rec["response"] = "DRY_RUN"
            self.order_log.write(rec)
            log.info("dry_run %s %s %s", kind, pair, kw)
            return None
        try:
            if kind in ("BUY", "SELL"):
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

    # --- legs by intent ---------------------------------------------------------------------
    def _sell_long(self, pair, qty, px, prec, mini, reason, results):
        q = floor_qty(qty, prec)
        if float(q) > 0 and float(q) * px >= mini:
            results.append(self._send("SELL", pair, reason, quantity=q))
            self.usd_free += float(q) * px * (1 - self.fee)

    def _close_short(self, pair, snap, qty, px, prec, mini, reason, results):
        held = snap.shorts.get(pair, {}).get("qty", 0.0)
        if held <= 0:
            return
        if qty is None or (held - qty) * px < mini:          # close everything, leave no dust
            results.append(self._send("SHORT_CLOSE", pair, reason + " close short"))
            self.usd_free += snap.shorts[pair]["value"] * (1 - self.fee)
            return
        q = floor_qty(qty, prec)
        if float(q) > 0:
            results.append(self._send("SHORT_CLOSE", pair, reason, quantity=q))
            self.usd_free += float(q) * px * (1 - self.fee)

    def _buy(self, pair, notional, px, prec, mini, reason, results):
        spend = min(notional, max(self.usd_free - 1.0, 0.0) / (1 + self.fee))
        q = floor_qty(spend / px, prec)
        if float(q) > 0 and float(q) * px >= mini:
            results.append(self._send("BUY", pair, reason, quantity=q))
            self.usd_free -= float(q) * px * (1 + self.fee)

    def _open_short(self, pair, collateral, mini, reason, results):
        coll = min(collateral, max(self.usd_free - 1.0, 0.0) / (1 + self.fee))
        if coll >= max(mini, 1.0):
            results.append(self._send("SHORT_OPEN", pair, reason, collateral=fmt_usd(coll)))
            self.usd_free -= coll * (1 + self.fee)

    # --- weight changes ---------------------------------------------------------------------
    def execute(self, trades: list, snap, reason_by_pair: dict = None) -> list:
        """trades: [{"coin": pair, "from": w, "to": w}], weights as fractions of equity."""
        reason_by_pair = reason_by_pair or {}
        results, opens = [], []
        self.usd_free = snap.usd_free
        equity = snap.equity
        # pass 1: closes and reductions
        for tr in trades:
            pair, w_from, w_to = tr["coin"], float(tr["from"]), float(tr["to"])
            meta = self.meta.get(pair)
            px = snap.prices.get(pair, 0.0)
            if not meta or not meta.get("CanTrade", True) or px <= 0:
                log.warning("skip %s: no metadata or price", pair)
                continue
            prec, mini = int(meta.get("AmountPrecision", 0)), float(meta.get("MiniOrder", 1) or 1)
            coin = pair.split("/")[0]
            reason = reason_by_pair.get(pair, "")
            held_long = snap.coins.get(coin, 0.0)
            if w_from > 0 and w_to <= 0:                      # leave the long side entirely
                self._sell_long(pair, held_long, px, prec, mini, reason + " close long", results)
                w_from = 0.0
            elif w_from < 0 and w_to >= 0:                    # leave the short side entirely
                self._close_short(pair, snap, None, px, prec, mini, reason, results)
                w_from = 0.0
            delta = w_to - w_from
            notional = abs(delta) * equity
            if notional < mini:
                continue
            if w_to > 0 and delta < 0:                        # reduce a long
                q = min(notional / px, held_long)
                if (held_long - q) * px < mini:
                    q = held_long
                self._sell_long(pair, q, px, prec, mini, reason, results)
            elif w_to < 0 and delta > 0:                      # reduce a short
                self._close_short(pair, snap, notional / px, px, prec, mini, reason, results)
            else:                                             # open or increase: pass 2
                opens.append((pair, w_to, delta, px, prec, mini, reason))
        # pass 2: opens and increases, funded by what pass 1 freed
        for pair, w_to, delta, px, prec, mini, reason in opens:
            notional = abs(delta) * equity
            if w_to > 0:
                self._buy(pair, notional, px, prec, mini, reason, results)
            else:
                self._open_short(pair, notional, mini, reason, results)
        return results
