"""Entry point: one cycle about a minute after every 4h bar close (UTC), forever.

    MODE=dry_run python -m bot.main      # compute and log, send nothing
    MODE=live    python -m bot.main      # trade

Every cycle re-reads balances and short positions from the API, never from memory. All
exceptions are caught and logged; the process never exits on its own.
"""
import json
import logging
import sys
import time

import pandas as pd

from bot.config import settings as S
from bot.data.binance import fetch_close_panel
from bot.data.price_store import PriceStore
from bot.execution.orders import Executor
from bot.execution.portfolio import fetch_snapshot, paper_snapshot
from bot.execution.rate_limiter import RateLimiter
from bot.execution.roostoo_client import RoostooClient
from bot.execution.state import BotState
from bot.logging_setup import CYCLE_FIELDS, HEARTBEAT_FIELDS, ORDER_FIELDS, CsvLogger, setup_logging
from bot.strategy.rebalance import plan_trades
from bot.strategy.risk import DrawdownController, DrawdownControllerLegacy
from bot.strategy.signals import cov_matrix, log_returns, realized_vol, trend_signal
from bot.strategy.sizing import ex_ante_vol, target_weights

log = logging.getLogger("bot")


def utc_now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def last_closed_bar_open_ms(now_ms: int) -> int:
    """Open time of the most recent 4h bar that has closed."""
    return (now_ms // S.BAR_MS - 1) * S.BAR_MS


class Bot:
    def __init__(self):
        self.live = S.MODE == "live"
        self.paper = not self.live and not (S.API_KEY and S.SECRET_KEY)
        if self.live and not (S.API_KEY and S.SECRET_KEY):
            raise SystemExit("MODE=live needs ROOSTOO_API_KEY and ROOSTOO_SECRET_KEY in .env")
        self.limiter = RateLimiter(S.RATE_LIMIT_CALLS, S.RATE_LIMIT_WINDOW_SEC)
        self.client = RoostooClient(S.API_KEY, S.SECRET_KEY, self.limiter)
        self.state = BotState(S.STATE_FILE)
        self.store = PriceStore(S.PRICE_STORE)
        self.orders_csv = CsvLogger(f"{S.LOG_DIR}/orders.csv", ORDER_FIELDS)
        self.cycles_csv = CsvLogger(f"{S.LOG_DIR}/cycles.csv", CYCLE_FIELDS)
        self.heartbeat_csv = CsvLogger(f"{S.LOG_DIR}/heartbeat.csv", HEARTBEAT_FIELDS)
        self.pair_meta = {}
        self.meta_refreshed = 0

    # --- helpers --------------------------------------------------------------------------
    def refresh_meta(self):
        if time.time() - self.meta_refreshed < 24 * 3600 and self.pair_meta:
            return
        info = self.client.exchange_info()
        self.pair_meta = {p: v for p, v in info["TradePairs"].items() if p in S.UNIVERSE}
        missing = [p for p in S.UNIVERSE if p not in self.pair_meta]
        if missing:
            log.error("pairs missing from exchangeInfo (will be skipped): %s", missing)
        self.meta_refreshed = time.time()

    def snapshot(self, ticker=None):
        if self.paper:
            return paper_snapshot(ticker or self.client.ticker(), S.UNIVERSE)
        snap = fetch_snapshot(self.client, S.UNIVERSE, self.state.collateral_in_lock)
        if self.state.collateral_in_lock != snap.collateral_in_lock:
            log.info("collateral accounting observed: USD.Lock %s short collateral",
                     "contains" if snap.collateral_in_lock else "does not contain")
            self.state.collateral_in_lock = snap.collateral_in_lock
            self.state.save()
        return snap

    def prices(self):
        """(close panel, source). Binance first, the local Roostoo store as a fallback."""
        try:
            panel = fetch_close_panel(S.UNIVERSE, S.HISTORY_BARS)
            if len(panel) >= S.VOL_LOOKBACK + 2:
                return panel, "binance"
            log.error("binance panel too short: %d bars", len(panel))
        except Exception as e:  # noqa: BLE001
            log.error("binance klines failed: %s", e)
        panel = self.store.close_panel(list(S.UNIVERSE))
        if len(panel) >= S.VOL_LOOKBACK + 2:
            return panel, "roostoo_store"
        return None, "none"

    # --- one cycle ------------------------------------------------------------------------
    def cycle(self, bar_open_ms: int):
        now = int(time.time())
        bar_open = pd.Timestamp(bar_open_ms, unit="ms", tz="UTC")
        self.refresh_meta()
        ticker = self.client.ticker()
        self.store.record(bar_open_ms + S.BAR_MS, ticker)
        snap = self.snapshot(ticker)
        if S.REENTRY == "legacy":
            risk = DrawdownControllerLegacy(self.state.risk, S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE)
        else:
            risk = DrawdownController(self.state.risk, S.DD_STOP, S.COOLDOWN_SEC, S.REDUCED_SIZE, S.HALF_SIZE_SEC)
        r = risk.update(snap.equity, now)

        panel, source = self.prices()
        note = ""
        signals, vols, target, trades = {}, {}, {}, []
        if r["flat"]:
            target = {p: 0.0 for p in S.UNIVERSE}
            trades = plan_trades(target, snap.weights, band=0.0)
            note = f"risk {r['reason']}: closing everything"
        elif panel is None:
            note = "no price data: holding current positions"
        else:
            panel = panel[panel.index <= bar_open]            # closed bars only
            sig = trend_signal(panel, S.EMA_N, S.RET_LOOKBACK).iloc[-1]
            vol = realized_vol(panel, S.VOL_LOOKBACK, S.BARS_PER_YEAR).iloc[-1]
            signals = {p: int(sig[p]) for p in S.UNIVERSE}
            vols = {p: float(vol[p]) for p in S.UNIVERSE}
            cov = cov_matrix(log_returns(panel[list(S.UNIVERSE)]).values[-S.VOL_LOOKBACK:], S.BARS_PER_YEAR)
            target = target_weights(signals, vols, cov, S.TARGET_VOL, S.MAX_WEIGHT, S.MAX_GROSS, r["size_mult"])
            if S.TURNOVER_RULE == "legacy":
                trades = plan_trades(target, snap.weights, S.NO_TRADE_BAND)
            else:
                trades = plan_trades(target, snap.weights, S.NO_TRADE_BAND, signals,
                                     self.state.prev_signals, S.REL_BAND)
            self.state.prev_signals = dict(signals)
            note = f"ex-ante vol {ex_ante_vol(target, cov):.3f}"
            if panel.index[-1] != bar_open:
                note += f"; latest bar in panel is {panel.index[-1]} (expected {bar_open})"
        reasons = {p: f"sig={signals.get(p, 0)} vol={vols.get(p, float('nan')):.2f} w {snap.weights.get(p, 0):.3f}->{target.get(p, 0):.3f} {r['reason']}"
                   for p in S.UNIVERSE}
        executor = Executor(self.client, self.pair_meta, self.live, self.orders_csv, S.FEE_TAKER)
        sent = executor.execute(trades, snap, reasons) if trades else []
        self.state.last_bar_ts = bar_open_ms
        self.state.save()
        self.cycles_csv.write({
            "timestamp": utc_now_iso(), "bar_open_utc": str(bar_open), "mode": S.MODE if not self.paper else "paper",
            "equity": f"{snap.equity:.2f}", "usd_free": f"{snap.usd_free:.2f}", "usd_lock": f"{snap.usd_lock:.2f}",
            "gross": f"{snap.gross:.4f}", "risk_reason": r["reason"], "size_mult": r["size_mult"],
            "peak": f"{self.state.risk.peak:.2f}", "ref_peak": f"{self.state.risk.ref_peak:.2f}",
            "cooldown_until": self.state.risk.cooldown_until, "half_until": self.state.risk.half_until,
            "signals": json.dumps(signals),
            "target_weights": json.dumps({k: round(v, 4) for k, v in target.items()}),
            "current_weights": json.dumps({k: round(v, 4) for k, v in snap.weights.items()}),
            "trades_planned": len(trades), "orders_sent": sum(1 for x in sent if x is not None),
            "price_source": source, "collateral_in_lock": snap.collateral_in_lock,
            "rate_limit_used": self.limiter.used(), "note": note})
        log.info("cycle %s equity %.2f gross %.3f risk=%s trades=%d sent=%d %s", bar_open, snap.equity,
                 snap.gross, r["reason"], len(trades), sum(1 for x in sent if x is not None), note)

    def heartbeat(self, next_cycle_ms: int):
        snap = self.snapshot()
        self.heartbeat_csv.write({
            "timestamp": utc_now_iso(), "mode": S.MODE if not self.paper else "paper",
            "equity": f"{snap.equity:.2f}", "usd_free": f"{snap.usd_free:.2f}", "gross": f"{snap.gross:.4f}",
            "n_longs": sum(1 for w in snap.weights.values() if w > 0),
            "n_shorts": sum(1 for w in snap.weights.values() if w < 0),
            "next_cycle_utc": str(pd.Timestamp(next_cycle_ms, unit="ms", tz="UTC")), "note": ""})
        log.info("heartbeat equity %.2f gross %.3f", snap.equity, snap.gross)

    # --- main loop ------------------------------------------------------------------------
    def run(self):
        log.info("starting mode=%s paper=%s ema=%d universe=%s", S.MODE, self.paper, S.EMA_N, list(S.UNIVERSE))
        while True:
            try:
                now_ms = int(time.time() * 1000)
                bar = last_closed_bar_open_ms(now_ms)
                if bar > self.state.last_bar_ts:
                    self.cycle(bar)                         # catches up after a restart, too
                next_cycle_ms = bar + 2 * S.BAR_MS + S.WAKE_DELAY_SEC * 1000
                last_hb = time.time()
                while time.time() * 1000 < next_cycle_ms:
                    time.sleep(min(30, max(0.0, next_cycle_ms / 1000 - time.time())))
                    if time.time() - last_hb >= S.HEARTBEAT_SEC:
                        last_hb = time.time()
                        try:
                            self.heartbeat(next_cycle_ms)
                        except Exception as e:  # noqa: BLE001
                            log.exception("heartbeat failed: %s", e)
            except Exception as e:  # noqa: BLE001
                log.exception("cycle failed: %s", e)
                time.sleep(60)


def main():
    setup_logging(S.LOG_DIR)
    try:
        Bot().run()
    except KeyboardInterrupt:
        log.info("stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
