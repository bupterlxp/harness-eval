"""LLM-specific retry: retry on provider_error / timeout / llm_error.

Wraps :func:`harness_scaffold.core.retry.retry` with a classifier and a default
RetryPolicy tuned for transient provider failures. Still bounded; never infinite.

NO third-party imports.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional, TypeVar

from ..core.errors import ErrorCode, HarnessError
from ..core.retry import retry as _retry
from ..core.schemas import RetryPolicy

T = TypeVar("T")

LLM_RETRY_CODES = (
    ErrorCode.PROVIDER_ERROR.value,
    ErrorCode.TIMEOUT.value,
    ErrorCode.LLM_ERROR.value,
)


def default_llm_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=3,
        base_delay=0.5,
        max_delay=8.0,
        jitter=0.2,
        retry_on=LLM_RETRY_CODES,
    )


def classify_llm(exc: BaseException) -> Optional[str]:
    if isinstance(exc, HarnessError):
        return exc.error_code.value
    return ErrorCode.LLM_ERROR.value


def retry_llm_sync(
    func: Callable[[], T],
    *,
    policy: Optional[RetryPolicy] = None,
    sleep: Callable[[float], None] | None = None,
) -> T:
    pol = policy or default_llm_retry_policy()
    if sleep is None:
        import time as _time

        sleep = _time.sleep
    return _retry(func, pol, classify=classify_llm, sleep=sleep)


async def retry_llm_async(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    policy: Optional[RetryPolicy] = None,
    sleep_async: Optional[Callable[[float], Awaitable[None]]] = None,
) -> T:
    """Async retry: ``coro_factory`` is called fresh each attempt.

    Bounded by ``policy.max_attempts``. Uses ``asyncio.sleep`` for backoff.
    """
    import asyncio

    from ..core.retry import compute_delay, _deterministic_jitter

    pol = policy or default_llm_retry_policy()
    sleeper = sleep_async or asyncio.sleep
    retry_codes = set(pol.retry_on)
    attempts = max(1, pol.max_attempts)
    last_exc: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            code = classify_llm(exc)
            if code not in retry_codes or attempt >= attempts:
                break
            delay = compute_delay(attempt, pol, _deterministic_jitter)
            if delay > 0:
                await sleeper(delay)

    assert last_exc is not None
    if isinstance(last_exc, HarnessError):
        last_exc.details.setdefault("retry", {})
        last_exc.details["retry"].update({"attempts": attempts, "gave_up": True})
        raise last_exc
    raise HarnessError(
        f"llm retry gave up after {attempts} attempts: {last_exc}",
        error_code=ErrorCode.LLM_ERROR,
        details={"attempts": attempts},
        recoverable=False,
    ) from last_exc
