"""Autonomous drawdown stop.

If equity falls DD_STOP below its running peak: close everything and stay flat for
COOLDOWN_SEC. Then resume at REDUCED_SIZE until equity makes a new all-time peak, at which
point full size returns.

Two reference levels are kept (see docs/DECISIONS.md):
  peak      all-time equity peak; a new one restores full size
  ref_peak  running peak since the last resume; the stop is measured against this, otherwise
            the stop would re-fire on every cycle after resuming below the old peak
"""
from dataclasses import asdict, dataclass


@dataclass
class RiskState:
    peak: float = 0.0
    ref_peak: float = 0.0
    cooldown_until: int = 0      # epoch seconds; 0 = not in cooldown
    size_mult: float = 1.0
    stops: int = 0               # number of stops fired, for the log

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class DrawdownController:
    def __init__(self, state: RiskState, dd_stop: float, cooldown_sec: int, reduced_size: float):
        self.s = state
        self.dd_stop = dd_stop
        self.cooldown_sec = cooldown_sec
        self.reduced_size = reduced_size

    def update(self, equity: float, now: int) -> dict:
        """Advance the state with the latest equity. Returns {"flat", "size_mult", "reason"}."""
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
            # first cycle after the cooldown: resume at reduced size, reset the stop reference
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
