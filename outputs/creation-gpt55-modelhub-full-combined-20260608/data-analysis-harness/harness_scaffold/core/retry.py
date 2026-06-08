"""Bounded retry with exponential backoff + deterministic jitter.

NEVER retries forever: capped by ``RetryPolicy.max_attempts``. The jitter and
sleep functions are injectable so tests are fully deterministic and never
actually sleep.

NO third-party imports.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, TypeVar

from .errors import ErrorCode, HarnessError, build_error_json
from .schemas import RetryPolicy

T = TypeVar("T")

# A classifier maps a raised exception to an ErrorCode (or None to not retry).
Classifier = Callable[[BaseException], "ErrorCode | str | None"]


def default_classify(exc: BaseException) -> "ErrorCode | str | None":
    if isinstance(exc, HarnessError):
        return exc.error_code
    return ErrorCode.UNKNOWN_ERROR


def _deterministic_jitter(attempt: int, fraction: float) -> float:
    """Deterministic pseudo-jitter in [-fraction, +fraction] of base.

    Uses a fixed hash of the attempt index so two runs produce identical
    backoff schedules (important for replayable benchmarks).
    """
    if fraction <= 0:
        return 0.0
    # cheap deterministic value in [0,1)
    h = (attempt * 2654435761) % 1000 / 1000.0
    return (h * 2 - 1) * fraction


def compute_delay(attempt: int, policy: RetryPolicy, jitter_fn: Callable[[int, float], float]) -> float:
    """Backoff for a 1-based ``attempt`` index (attempt 1 => base_delay)."""
    base = policy.base_delay * (2 ** max(0, attempt - 1))
    base = min(base, policy.max_delay)
    delta = jitter_fn(attempt, policy.jitter) * policy.base_delay
    return max(0.0, base + delta)


def retry(
    func: Callable[[], T],
    policy: RetryPolicy,
    *,
    classify: Classifier = default_classify,
    sleep: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[int, float], float] = _deterministic_jitter,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> T:
    """Call ``func`` with bounded retries.

    Retries only when ``classify(exc)`` is in ``policy.retry_on``. Raises the
    last exception (a HarnessError carrying give-up details) once attempts are
    exhausted or the error is non-retryable.
    """
    attempts = max(1, policy.max_attempts)
    last_exc: Optional[BaseException] = None
    retry_codes = set(policy.retry_on)

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            code = classify(exc)
            code_val = code.value if hasattr(code, "value") else (str(code) if code else None)
            retryable = code_val in retry_codes
            if not retryable or attempt >= attempts:
                break
            delay = compute_delay(attempt, policy, jitter_fn)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            if delay > 0:
                sleep(delay)

    # Give up: wrap with structured give-up info but preserve original code.
    assert last_exc is not None
    if isinstance(last_exc, HarnessError):
        last_exc.details.setdefault("retry", {})
        last_exc.details["retry"].update(
            {"attempts": attempts, "gave_up": True}
        )
        raise last_exc
    raise HarnessError(
        f"retry gave up after {attempts} attempts: {last_exc}",
        error_code=ErrorCode.UNKNOWN_ERROR,
        details={"attempts": attempts, "exception_type": type(last_exc).__name__},
        recoverable=False,
    ) from last_exc


def retry_give_up_error(
    attempts: int,
    last_error: dict[str, Any],
    *,
    stage: Optional[str] = None,
) -> dict[str, Any]:
    """Helper to build a structured give-up error.json dict."""
    return build_error_json(
        error_code=last_error.get("error_code", ErrorCode.UNKNOWN_ERROR.value),
        message=f"gave up after {attempts} attempts",
        stage=stage,
        details={"attempts": attempts, "last_error": last_error},
        recoverable=False,
    )
