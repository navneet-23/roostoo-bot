"""Autonomous drawdown stop.

DrawdownController (current, "timed" re-entry, since 2026-10-06 final change set):
  If equity falls DD_STOP below its running peak: close everything and stay flat for
  COOLDOWN_SEC. At re-entry the running peak is reset to the equity at that moment, the book
  trades at REDUCED_SIZE for HALF_SIZE_SEC, then returns to full size. The stop stays armed
  throughout, measured against the running peak since re-entry.

DrawdownControllerLegacy (until the final change set, kept for the A/B comparison):
  Same stop and cooldown, then REDUCED_SIZE until equity makes a new all-time peak. With the
  all-time peak as the reference that state was permanent in practice (95% of active bars in
  the backtest), which is why it was replaced. See docs/CHANGELOG.md.

Both persist everything they need in RiskState (state/state.json), so restarts never reset
a stop, a cooldown or a size multiplier.
"""
from dataclasses import asdict, dataclass


@dataclass
class RiskState:
    peak: float = 0.0
    ref_peak: float = 0.0        # legacy controller only
    cooldown_until: int = 0      # epoch seconds; 0 = not in cooldown
    half_until: int = 0          # epoch seconds; 0 = not in the half-size period
    size_mult: float = 1.0
    stops: int = 0               # number of stops fired, for the log

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class DrawdownController:
    def __init__(self, state: RiskState, dd_stop: float, cooldown_sec: int, reduced_size: float,
                 half_size_sec: int = 72 * 3600):
        self.s = state
        self.dd_stop = dd_stop
        self.cooldown_sec = cooldown_sec
        self.reduced_size = reduced_size
        self.half_size_sec = half_size_sec

    def update(self, equity: float, now: int) -> dict:
        """Advance the state with the latest equity. Returns {"flat", "size_mult", "reason"}."""
        s = self.s
        if s.peak <= 0:
            s.peak = equity
        if s.cooldown_until and now < s.cooldown_until:
            return {"flat": True, "size_mult": 0.0, "reason": "cooldown"}
        if s.cooldown_until and now >= s.cooldown_until:
            # re-entry: reset the running peak, trade at reduced size for a fixed period
            s.cooldown_until = 0
            s.peak = equity
            s.half_until = now + self.half_size_sec
            s.size_mult = self.reduced_size
            return {"flat": False, "size_mult": s.size_mult, "reason": "resume"}
        if s.half_until and now >= s.half_until:
            s.half_until = 0
            s.size_mult = 1.0
        s.peak = max(s.peak, equity)
        if equity < s.peak * (1.0 - self.dd_stop):
            s.cooldown_until = now + self.cooldown_sec
            s.half_until = 0
            s.size_mult = 0.0
            s.stops += 1
            return {"flat": True, "size_mult": 0.0, "reason": "stop"}
        return {"flat": False, "size_mult": s.size_mult, "reason": "half" if s.half_until else "normal"}


class DrawdownControllerLegacy:
    def __init__(self, state: RiskState, dd_stop: float, cooldown_sec: int, reduced_size: float):
        self.s = state
        self.dd_stop = dd_stop
        self.cooldown_sec = cooldown_sec
        self.reduced_size = reduced_size

    def update(self, equity: float, now: int) -> dict:
        s = self.s
        if s.peak <= 0:
            s.peak = s.ref_peak = equity
        if equity > s.peak:
            s.peak = equity
            if now >= s.cooldown_until:
                s.size_mult = 1.0
        if s.cooldown_until and now < s.cooldown_until:
            return {"flat": True, "size_mult": 0.0, "reason": "cooldown"}
        if s.cooldown_until and now >= s.cooldown_until:
            s.cooldown_until = 0
            s.ref_peak = equity
            s.size_mult = self.reduced_size if equity < s.peak else 1.0
            return {"flat": False, "size_mult": s.size_mult, "reason": "resume"}
        s.ref_peak = max(s.ref_peak, equity)
        if equity < s.ref_peak * (1.0 - self.dd_stop):
            s.cooldown_until = now + self.cooldown_sec
            s.stops += 1
            s.size_mult = self.reduced_size
            return {"flat": True, "size_mult": 0.0, "reason": "stop"}
        return {"flat": False, "size_mult": s.size_mult, "reason": "normal"}
