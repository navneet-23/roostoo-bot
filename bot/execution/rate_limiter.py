"""Global sliding-window rate limiter: at most `calls` acquisitions per `window_sec`.

Every Roostoo request, including retries and queries, acquires a slot before it is sent.
"""
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, calls: int, window_sec: float, clock=time.monotonic, sleeper=time.sleep):
        self.calls = calls
        self.window = window_sec
        self.clock = clock
        self.sleeper = sleeper
        self.q = deque()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            while True:
                now = self.clock()
                while self.q and self.q[0] <= now - self.window:
                    self.q.popleft()
                if len(self.q) < self.calls:
                    self.q.append(now)
                    return
                self.sleeper(max(self.q[0] + self.window - now, 0.01))

    def used(self) -> int:
        now = self.clock()
        return sum(1 for t in self.q if t > now - self.window)
