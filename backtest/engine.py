"""Bar-by-bar simulation of the live bot's logic on a 4h open/close panel.

Conventions (match the live bot):
- Decisions at the close of bar t use closes up to t; fills happen at open[t+1].
- Fee FEE per leg on traded notional, plus SLIPPAGE against the trader on every fill.
- Longs: market buy/sell of quantity.
- Shorts (Roostoo mechanics, 1x): opening with collateral C at price p gives qty = C/p and
  charges a fee of 0.1% of C; position value = C + qty * (entry - price); closing qty q at
  price p returns q * entry... i.e. collateral share plus PnL, minus 0.1% of q * p.
- Current weight of a position = signed exposure / equity (long: qty*price, short: -qty*price).
- A flip closes the old side first, then opens the new one.
- When the drawdown stop demands flat, every position is closed regardless of the band.
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from bot.strategy.rebalance import plan_trades
from bot.strategy.risk import DrawdownController, RiskState
from bot.strategy.signals import cov_matrix, log_returns, realized_vol, trend_signal
from bot.strategy.sizing import ex_ante_vol, target_weights, target_weights_legacy


@dataclass
class Short:
    qty: float
    entry: float
    collateral: float

    def value(self, price):
        return self.collateral + self.qty * (self.entry - price)


@dataclass
class Book:
    cash: float
    longs: dict = field(default_factory=dict)    # coin -> qty
    shorts: dict = field(default_factory=dict)   # coin -> Short
    fees: float = 0.0
    trades: int = 0

    def equity(self, price: dict):
        e = self.cash
        for c, q in self.longs.items():
            e += q * price[c]
        for c, s in self.shorts.items():
            e += s.value(price[c])
        return e

    def weights(self, price: dict, equity: float):
        w = {}
        for c, q in self.longs.items():
            w[c] = q * price[c] / equity
        for c, s in self.shorts.items():
            w[c] = -s.qty * price[c] / equity
        return w


class Simulator:
    def __init__(self, fee, slippage, ema_n, ret_lookback, vol_lookback, bars_per_year,
                 target_vol, max_weight, max_gross, band, dd_stop, cooldown_sec, reduced_size,
                 capital=100_000.0, sizing="cov"):
        """sizing: "cov" = portfolio vol targeting (current); "legacy" = per-coin formula used
        until 2026-10-06, kept for the before/after comparison in RESULTS.md."""
        self.sizing = sizing
        self.fee, self.slip = fee, slippage
        self.ema_n, self.ret_lb, self.vol_lb, self.bpy = ema_n, ret_lookback, vol_lookback, bars_per_year
        self.target_vol, self.max_w, self.max_gross, self.band = target_vol, max_weight, max_gross, band
        self.risk_params = (dd_stop, cooldown_sec, reduced_size)
        self.capital = capital

    # --- fills ----------------------------------------------------------------------------
    def _buy(self, book, coin, notional, px):
        p = px * (1 + self.slip)
        notional = min(notional, book.cash / (1 + self.fee))
        if notional <= 0:
            return
        qty = notional / p
        fee = notional * self.fee
        book.cash -= notional + fee
        book.fees += fee
        book.trades += 1
        book.longs[coin] = book.longs.get(coin, 0.0) + qty

    def _sell(self, book, coin, qty, px):
        p = px * (1 - self.slip)
        qty = min(qty, book.longs.get(coin, 0.0))
        if qty <= 0:
            return
        notional = qty * p
        fee = notional * self.fee
        book.cash += notional - fee
        book.fees += fee
        book.trades += 1
        rem = book.longs[coin] - qty
        if rem * p < 1e-6:
            del book.longs[coin]
        else:
            book.longs[coin] = rem

    def _short_open(self, book, coin, collateral, px):
        p = px * (1 - self.slip)                      # shorts fill at the bid
        collateral = min(collateral, book.cash / (1 + self.fee))
        if collateral <= 0:
            return
        qty = collateral / p
        fee = collateral * self.fee
        book.cash -= collateral + fee
        book.fees += fee
        book.trades += 1
        s = book.shorts.get(coin)
        if s is None:
            book.shorts[coin] = Short(qty, p, collateral)
        else:                                          # merge at weighted-average entry
            tq = s.qty + qty
            s.entry = (s.entry * s.qty + p * qty) / tq
            s.qty, s.collateral = tq, s.collateral + collateral

    def _short_close(self, book, coin, qty, px):
        s = book.shorts.get(coin)
        if s is None:
            return
        p = px * (1 + self.slip)                      # closes fill at the ask
        qty = min(qty, s.qty)
        if qty <= 0:
            return
        if (s.qty - qty) * p < 1e-6:
            qty = s.qty
        share = qty / s.qty
        collateral_back = s.collateral * share
        pnl = qty * (s.entry - p)
        fee = qty * p * self.fee
        book.cash += collateral_back + pnl - fee
        book.fees += fee
        book.trades += 1
        if qty >= s.qty:
            del book.shorts[coin]
        else:
            s.qty -= qty
            s.collateral -= collateral_back

    def _apply(self, book, coin, w_from, w_to, equity, px):
        """Move coin from weight w_from to w_to, filling at open price px."""
        if w_from > 0 and w_to <= 0:
            self._sell(book, coin, book.longs.get(coin, 0.0), px)
            w_from = 0.0
        elif w_from < 0 and w_to >= 0:
            s = book.shorts.get(coin)
            if s:
                self._short_close(book, coin, s.qty, px)
            w_from = 0.0
        delta = w_to - w_from
        if abs(delta) * equity < 1.0:
            return
        if w_to > 0:
            if delta > 0:
                self._buy(book, coin, delta * equity, px)
            else:
                self._sell(book, coin, -delta * equity / px, px)
        elif w_to < 0:
            if delta < 0:
                self._short_open(book, coin, -delta * equity, px)
            else:
                self._short_close(book, coin, delta * equity / px, px)

    # --- main loop -------------------------------------------------------------------------
    def run(self, opn: pd.DataFrame, cls: pd.DataFrame, start: pd.Timestamp):
        coins = list(cls.columns)
        sig = trend_signal(cls, self.ema_n, self.ret_lb)
        vol = realized_vol(cls, self.vol_lb, self.bpy)
        LR = log_returns(cls).values
        idx = cls.index
        t0 = int(np.searchsorted(idx.values, np.datetime64(start.tz_convert("UTC").tz_localize(None))))
        book = Book(cash=self.capital)
        risk = DrawdownController(RiskState(), *self.risk_params)
        rows = []
        pending = None                                  # trades decided at t, filled at open t+1
        C, O, SG, V = cls.values, opn.values, sig.values, vol.values
        ts = idx.as_unit("ms").asi8                      # bar open time in ms, whatever the index resolution
        for t in range(t0, len(idx)):
            price_open = {c: O[t, i] for i, c in enumerate(coins)}
            # 1. fill what was decided at the previous close
            if pending:
                eq_open = book.equity(price_open)
                for tr in pending:
                    if math.isfinite(price_open[tr["coin"]]):
                        self._apply(book, tr["coin"], tr["from"], tr["to"], eq_open, price_open[tr["coin"]])
                pending = None
            # 2. mark at this close and decide
            price = {c: C[t, i] for i, c in enumerate(coins)}
            equity = book.equity(price)
            r = risk.update(equity, int(ts[t] // 1000) + 4 * 3600)
            cur_w = book.weights(price, equity)
            exante = 0.0
            if r["flat"]:
                target = {c: 0.0 for c in coins}
                trades = plan_trades(target, cur_w, band=0.0)
            else:
                signals = {c: int(SG[t, i]) if math.isfinite(C[t, i]) else 0 for i, c in enumerate(coins)}
                vols = {c: float(V[t, i]) for i, c in enumerate(coins)}
                if self.sizing == "legacy":
                    target = target_weights_legacy(signals, vols, self.target_vol, self.max_w,
                                                   self.max_gross, r["size_mult"])
                    cov = cov_matrix(LR[max(0, t - self.vol_lb + 1):t + 1], self.bpy)
                else:
                    cov = cov_matrix(LR[max(0, t - self.vol_lb + 1):t + 1], self.bpy)
                    target = target_weights(signals, vols, cov, self.target_vol, self.max_w,
                                            self.max_gross, r["size_mult"])
                exante = ex_ante_vol(target, cov)
                trades = plan_trades(target, cur_w, self.band)
            pending = trades or None
            gross = sum(abs(x) for x in cur_w.values())
            rows.append((ts[t], equity, gross, r["reason"], len(trades), book.fees, book.trades, exante, r["size_mult"]))
        out = pd.DataFrame(rows, columns=["ts", "equity", "gross", "risk", "n_trades_planned",
                                          "fees_cum", "trades_cum", "exante_vol", "size_mult"])
        out["time"] = pd.to_datetime(out["ts"], unit="ms", utc=True)
        out["close_time"] = out["time"] + pd.Timedelta(hours=4)
        return out.set_index("close_time")
