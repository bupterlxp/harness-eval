"""Timeout primitives. NO infinite waits anywhere.

``run_with_timeout`` executes a blocking callable in a daemon worker thread and
raises :class:`TimeoutErrorH` if it does not finish in time. The worker thread
is left to die on its own (Python can't force-kill threads), but the caller is
never blocked past the deadline. For *killable* timeouts (subprocesses) see
``tools.base._run_subprocess`` which uses process groups.

``async_timeout`` wraps an awaitable with ``asyncio.wait_for`` and converts the
asyncio TimeoutError into our structured one.

NO third-party imports.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

from .errors import TimeoutErrorH

T = TypeVar("T")


def run_with_timeout(
    func: Callable[..., T],
    seconds: float,
    *args: Any,
    stage: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> T:
    """Run a blocking ``func`` with a hard wall-clock timeout.

    Raises :class:`TimeoutErrorH` on expiry; re-raises the callable's own
    exception if it fails first. ``seconds<=0`` runs inline with no timeout
    guard (interpreted as "no limit" only when explicitly non-positive).
    """
    if seconds is None or seconds <= 0:
        return func(*args, **kwargs)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            result["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - propagate to caller
            error["exc"] = exc

    thread = threading.Thread(target=_target, daemon=True, name="harness-timeout-worker")
    thread.start()
    thread.join(timeout=seconds)

    if thread.is_alive():
        raise TimeoutErrorH(
            f"operation timed out after {seconds:.3f}s",
            stage=stage,
            details={**(details or {}), "timeout_seconds": seconds},
            recoverable=True,
        )
    if "exc" in error:
        raise error["exc"]
    return result.get("value")  # type: ignore[return-value]


async def async_timeout(
    awaitable: Awaitable[T],
    seconds: float,
    *,
    stage: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> T:
    """Await ``awaitable`` with a timeout, raising :class:`TimeoutErrorH`."""
    if seconds is None or seconds <= 0:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutErrorH(
            f"async operation timed out after {seconds:.3f}s",
            stage=stage,
            details={**(details or {}), "timeout_seconds": seconds},
            recoverable=True,
        ) from exc


class Deadline:
    """Monotonic deadline helper. ``seconds<=0`` means 'no deadline'."""

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._start = clock()
        self._seconds = float(seconds)

    @property
    def start(self) -> float:
        return self._start

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining(self) -> float:
        """Seconds left; ``float('inf')`` if no deadline; never negative."""
        if self._seconds <= 0:
            return float("inf")
        return max(0.0, self._seconds - self.elapsed())

    def expired(self) -> bool:
        if self._seconds <= 0:
            return False
        return self.elapsed() >= self._seconds

    def raise_if_expired(self, *, stage: Optional[str] = None) -> None:
        if self.expired():
            raise TimeoutErrorH(
                f"deadline of {self._seconds:.3f}s exceeded",
                stage=stage,
                details={"timeout_seconds": self._seconds, "elapsed_seconds": self.elapsed()},
                recoverable=True,
            )

    def clamp(self, seconds: float) -> float:
        """Return the smaller of ``seconds`` and the remaining time (>0)."""
        rem = self.remaining()
        if rem == float("inf"):
            return seconds
        return max(0.0, min(seconds, rem))
