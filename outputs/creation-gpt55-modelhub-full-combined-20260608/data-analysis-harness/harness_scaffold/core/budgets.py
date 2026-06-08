"""Step / time / output budgets. Bounded, structured exhaustion reporting.

A :class:`Budget` is the single source of truth for "how much is left" during a
run. The runtime increments it; tools consult ``seconds_left`` to clamp their
own timeouts. Exhaustion is *reported* (via ``exceeded()``) rather than raised,
so the harness program can stop gracefully and still write artifacts.

NO third-party imports.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional


class Budget:
    """Tracks step count, elapsed wall-clock seconds, and output bytes used."""

    def __init__(
        self,
        *,
        max_steps: int = 50,
        max_seconds: float = 900.0,
        max_output_bytes: int = 200_000,
        start_time: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_steps = int(max_steps)
        self.max_seconds = float(max_seconds)
        self.max_output_bytes = int(max_output_bytes)
        self._clock = clock
        self.start_time = start_time if start_time is not None else clock()
        self.steps_used = 0
        self.output_bytes_used = 0

    # --- mutation -------------------------------------------------------- #

    def step(self, n: int = 1) -> int:
        """Consume ``n`` steps; returns new step count."""
        self.steps_used += n
        return self.steps_used

    def consume_output(self, n_bytes: int) -> int:
        """Account ``n_bytes`` of produced output; returns new total."""
        self.output_bytes_used += max(0, int(n_bytes))
        return self.output_bytes_used

    # --- queries --------------------------------------------------------- #

    def elapsed(self) -> float:
        return self._clock() - self.start_time

    def seconds_left(self) -> float:
        if self.max_seconds <= 0:
            return float("inf")
        return max(0.0, self.max_seconds - self.elapsed())

    def steps_left(self) -> int:
        if self.max_steps <= 0:
            return 2**31  # effectively unbounded
        return max(0, self.max_steps - self.steps_used)

    def output_bytes_left(self) -> int:
        if self.max_output_bytes <= 0:
            return 2**31
        return max(0, self.max_output_bytes - self.output_bytes_used)

    def exceeded(self) -> Optional[dict[str, Any]]:
        """Return a structured reason dict if any budget is exhausted, else None."""
        if self.max_steps > 0 and self.steps_used >= self.max_steps:
            return self._reason("max_steps", self.steps_used, self.max_steps)
        if self.max_seconds > 0 and self.elapsed() >= self.max_seconds:
            return self._reason("max_seconds", round(self.elapsed(), 3), self.max_seconds)
        if self.max_output_bytes > 0 and self.output_bytes_used >= self.max_output_bytes:
            return self._reason("max_output_bytes", self.output_bytes_used, self.max_output_bytes)
        return None

    def _reason(self, which: str, used: Any, limit: Any) -> dict[str, Any]:
        return {
            "budget": which,
            "used": used,
            "limit": limit,
            "steps_used": self.steps_used,
            "elapsed_seconds": round(self.elapsed(), 3),
            "output_bytes_used": self.output_bytes_used,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "steps_used": self.steps_used,
            "max_steps": self.max_steps,
            "elapsed_seconds": round(self.elapsed(), 3),
            "max_seconds": self.max_seconds,
            "output_bytes_used": self.output_bytes_used,
            "max_output_bytes": self.max_output_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot()
