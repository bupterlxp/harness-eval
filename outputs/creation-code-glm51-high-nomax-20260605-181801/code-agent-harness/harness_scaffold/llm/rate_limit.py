"""Token-bucket rate limiter with an injectable clock. Bounded waits only.

NO third-party imports.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class TokenBucket:
    """Classic token bucket. ``acquire`` blocks at most ``max_wait`` seconds.

    With ``rate`` tokens/sec and ``capacity`` burst. The clock and sleeper are
    injectable for deterministic tests; sleeps are always bounded.
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = float(rate)
        self.capacity = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._tokens = float(capacity)
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        delta = now - self._last
        if delta > 0:
            self._tokens = min(self.capacity, self._tokens + delta * self.rate)
            self._last = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0, *, max_wait: float = 30.0) -> bool:
        """Block until ``tokens`` available or ``max_wait`` elapses.

        Returns True if acquired, False on timeout. NEVER waits forever.
        """
        deadline = self._clock() + max(0.0, max_wait)
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                needed = tokens - self._tokens
                wait = needed / self.rate
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            self._sleep(min(wait, remaining, 1.0))

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens
