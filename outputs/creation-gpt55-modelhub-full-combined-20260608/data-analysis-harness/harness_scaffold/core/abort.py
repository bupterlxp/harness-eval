"""Cooperative abort signal with optional deadline auto-abort.

An :class:`AbortSignal` is checked at loop boundaries by harness programs and by
the runtime. It can also auto-trip once a wall-clock deadline passes. This is
the cooperative-cancellation analogue of Claude Code's AbortController.

NO third-party imports.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from .errors import HarnessError, ErrorCode


class Aborted(HarnessError):
    error_code = ErrorCode.FAILED


class AbortSignal:
    def __init__(
        self,
        *,
        deadline_seconds: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
        reason: Optional[str] = None,
    ) -> None:
        self._event = threading.Event()
        self._clock = clock
        self._reason = reason
        self._start = clock()
        self._deadline_seconds = (
            float(deadline_seconds) if deadline_seconds and deadline_seconds > 0 else None
        )

    def set(self, reason: Optional[str] = None) -> None:
        if reason:
            self._reason = reason
        self._event.set()

    @property
    def reason(self) -> Optional[str]:
        if self._event.is_set():
            return self._reason or "aborted"
        if self._deadline_expired():
            return self._reason or "deadline_exceeded"
        return None

    def _deadline_expired(self) -> bool:
        if self._deadline_seconds is None:
            return False
        return (self._clock() - self._start) >= self._deadline_seconds

    def is_set(self) -> bool:
        if self._event.is_set():
            return True
        if self._deadline_expired():
            self._event.set()
            if self._reason is None:
                self._reason = "deadline_exceeded"
            return True
        return False

    def raise_if_aborted(self, *, stage: Optional[str] = None) -> None:
        if self.is_set():
            details: dict[str, Any] = {"reason": self.reason}
            raise Aborted(
                f"run aborted: {self.reason}",
                stage=stage,
                details=details,
                recoverable=False,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aborted": self.is_set(),
            "reason": self.reason,
            "deadline_seconds": self._deadline_seconds,
        }
