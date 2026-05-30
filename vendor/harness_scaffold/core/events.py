"""Trajectory event factory + secret redaction.

Every event is a plain JSON dict ``{"ts": float, "type": str, ...}``. The
timestamp comes from an injected ``clock`` (defaults to ``time.time``) so tests
are deterministic. These are the ONLY event shapes written to
``trajectory.jsonl``.

Extraction note: Claude Code emits rich React/streaming progress events; we keep
only the machine-readable subset useful for replay/debug and judging.

NO third-party imports.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

Clock = Callable[[], float]

# Event type constants (stable strings).
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
LLM_CALL = "llm_call"
LLM_RESULT = "llm_result"
OBSERVATION = "observation"
ARTIFACT = "artifact"
ERROR = "error"
TIMING = "timing"
STEP = "step"
INFO = "info"


def _ts(clock: Optional[Clock]) -> float:
    return (clock or time.time)()


def _event(type_: str, clock: Optional[Clock], **fields: Any) -> dict[str, Any]:
    ev: dict[str, Any] = {"ts": _ts(clock), "type": type_}
    for k, v in fields.items():
        if v is not None:
            ev[k] = v
    return ev


def tool_call(
    name: str,
    args: dict[str, Any],
    *,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(TOOL_CALL, clock, name=name, args=redact(args), step=step, **extra)


def tool_result(
    name: str,
    *,
    ok: bool,
    elapsed_seconds: float = 0.0,
    error: Optional[dict[str, Any]] = None,
    data_preview: Any = None,
    artifacts: Optional[dict[str, Any]] = None,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(
        TOOL_RESULT,
        clock,
        name=name,
        ok=ok,
        elapsed_seconds=elapsed_seconds,
        error=error,
        data_preview=redact(data_preview),
        artifacts=artifacts,
        step=step,
        **extra,
    )


def llm_call(
    *,
    model: Optional[str] = None,
    num_messages: Optional[int] = None,
    tools: Optional[list[str]] = None,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(
        LLM_CALL, clock, model=model, num_messages=num_messages, tools=tools, step=step, **extra
    )


def llm_result(
    *,
    model: Optional[str] = None,
    usage: Optional[dict[str, Any]] = None,
    text_preview: Optional[str] = None,
    tool_calls: Optional[list[Any]] = None,
    elapsed_seconds: float = 0.0,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(
        LLM_RESULT,
        clock,
        model=model,
        usage=usage,
        text_preview=redact(text_preview),
        tool_calls=redact(tool_calls),
        elapsed_seconds=elapsed_seconds,
        step=step,
        **extra,
    )


def observation(
    content: Any,
    *,
    source: Optional[str] = None,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(OBSERVATION, clock, content=redact(content), source=source, step=step, **extra)


def artifact(
    name: str,
    path: Any,
    *,
    kind: Optional[str] = None,
    size_bytes: Optional[int] = None,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(
        ARTIFACT, clock, name=name, path=str(path), kind=kind, size_bytes=size_bytes, step=step, **extra
    )


def error(
    error_obj: dict[str, Any],
    *,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(ERROR, clock, error=error_obj, step=step, **extra)


def timing(
    label: str,
    elapsed_seconds: float,
    *,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(TIMING, clock, label=label, elapsed_seconds=elapsed_seconds, step=step, **extra)


def step(
    index: int,
    *,
    phase: Optional[str] = None,
    note: Optional[str] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(STEP, clock, index=index, phase=phase, note=note, **extra)


def info(
    message: str,
    *,
    step: Optional[int] = None,
    clock: Optional[Clock] = None,
    **extra: Any,
) -> dict[str, Any]:
    return _event(INFO, clock, message=message, step=step, **extra)


# --- Redaction ------------------------------------------------------------ #

# Keys whose values are masked entirely.
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|authorization|auth|"
    r"access[_-]?key|private[_-]?key|bearer|credential)"
)

# Inline patterns (e.g. tokens embedded in strings).
_INLINE_PATTERNS = [
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
]

_MASK = "***REDACTED***"
_MAX_REDACT_DEPTH = 8


def redact(obj: Any, _depth: int = 0) -> Any:
    """Recursively mask secret-looking keys and inline token patterns.

    Pure function; returns a new structure. Bounded recursion depth to avoid
    pathological inputs.
    """
    if _depth > _MAX_REDACT_DEPTH:
        return "***DEPTH_LIMIT***"
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = _MASK
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in obj]
    if isinstance(obj, str):
        return _redact_inline(obj)
    return obj


def _redact_inline(s: str) -> str:
    for pat in _INLINE_PATTERNS:
        s = pat.sub(_MASK, s)
    return s
