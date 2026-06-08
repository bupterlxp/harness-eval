"""Append-only JSONL trajectory logger. NEVER writes to stdout.

One JSON object per line, flushed after each append, so a crashed run still
leaves a partial-but-valid trajectory for debugging. All events pass through
:func:`harness_scaffold.core.events.redact` by default.

NO third-party imports.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import events as ev
from .errors import ErrorCode
from .serialization import safe_json_dumps

TRAJECTORY_NAME = "trajectory.jsonl"


class TrajectoryLogger:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        redact: bool = True,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._redact = redact
        self._count = 0
        # Truncate/create the file at start so each run is clean.
        self.path.write_text("", encoding="utf-8")

    @property
    def count(self) -> int:
        return self._count

    # --- core append ----------------------------------------------------- #

    def append(self, event: dict[str, Any]) -> None:
        """Write exactly one JSON line and flush. Never raises to caller."""
        try:
            payload = ev.redact(event) if self._redact else event
            line = safe_json_dumps(payload, compact=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")
                fh.flush()
            self._count += 1
        except Exception:  # pragma: no cover - logging must never crash a run
            pass

    # --- typed helpers (timestamps injected via clock) ------------------- #

    def log_tool_call(self, name: str, args: dict[str, Any], *, step: Optional[int] = None) -> None:
        self.append(ev.tool_call(name, args, step=step, clock=self._clock))

    def log_tool_result(
        self,
        name: str,
        *,
        ok: bool,
        elapsed_seconds: float = 0.0,
        error: Optional[dict[str, Any]] = None,
        data_preview: Any = None,
        artifacts: Optional[dict[str, Any]] = None,
        step: Optional[int] = None,
    ) -> None:
        self.append(
            ev.tool_result(
                name,
                ok=ok,
                elapsed_seconds=elapsed_seconds,
                error=error,
                data_preview=data_preview,
                artifacts=artifacts,
                step=step,
                clock=self._clock,
            )
        )

    def log_llm_call(
        self,
        *,
        model: Optional[str] = None,
        num_messages: Optional[int] = None,
        tools: Optional[list[str]] = None,
        step: Optional[int] = None,
    ) -> None:
        self.append(
            ev.llm_call(model=model, num_messages=num_messages, tools=tools, step=step, clock=self._clock)
        )

    def log_llm_result(
        self,
        *,
        model: Optional[str] = None,
        usage: Optional[dict[str, Any]] = None,
        text_preview: Optional[str] = None,
        tool_calls: Optional[list[Any]] = None,
        elapsed_seconds: float = 0.0,
        step: Optional[int] = None,
    ) -> None:
        self.append(
            ev.llm_result(
                model=model,
                usage=usage,
                text_preview=text_preview,
                tool_calls=tool_calls,
                elapsed_seconds=elapsed_seconds,
                step=step,
                clock=self._clock,
            )
        )

    # Convenience alias.
    def log_llm(self, **kwargs: Any) -> None:
        self.log_llm_result(**kwargs)

    def log_observation(
        self, content: Any, *, source: Optional[str] = None, step: Optional[int] = None
    ) -> None:
        self.append(ev.observation(content, source=source, step=step, clock=self._clock))

    def log_artifact(
        self,
        name: str,
        path: Any,
        *,
        kind: Optional[str] = None,
        size_bytes: Optional[int] = None,
        step: Optional[int] = None,
    ) -> None:
        self.append(
            ev.artifact(name, path, kind=kind, size_bytes=size_bytes, step=step, clock=self._clock)
        )

    def log_error(self, error_obj: dict[str, Any], *, step: Optional[int] = None) -> None:
        self.append(ev.error(error_obj, step=step, clock=self._clock))

    def log_timing(self, label: str, elapsed_seconds: float, *, step: Optional[int] = None) -> None:
        self.append(ev.timing(label, elapsed_seconds, step=step, clock=self._clock))

    def log_step(
        self, index: int, *, phase: Optional[str] = None, note: Optional[str] = None
    ) -> None:
        self.append(ev.step(index, phase=phase, note=note, clock=self._clock))

    def log_info(self, message: str, *, step: Optional[int] = None, **extra: Any) -> None:
        self.append(ev.info(message, step=step, clock=self._clock, **extra))
