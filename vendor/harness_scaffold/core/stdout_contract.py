"""STDOUT CONTRACT (CRITICAL).

The hardest-won guarantee of this scaffold: when a harness runs under the CLI,
the process's *real* stdout receives EXACTLY ONE compact JSON line and nothing
else. Everything a program or library prints (``print``, tracebacks, library
chatter) is redirected to ``out_dir/stdout.log`` / ``out_dir/stderr.log``.

Mechanism:
  * :func:`capture_stdout_stderr` is a context manager that saves the original
    stdout/stderr file objects, replaces ``sys.stdout``/``sys.stderr`` with file
    handles to the log files, and restores them on exit. It hands back a
    callable that writes the single result line to the ORIGINAL stdout.
  * :func:`emit_result_line` writes one compact JSON line + newline to a given
    stream and flushes. It validates single-line-ness.

NO third-party imports.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO

from .errors import ContractError
from .serialization import safe_json_dumps

STDOUT_LOG = "stdout.log"
STDERR_LOG = "stderr.log"


def validate_single_json_line(s: str) -> dict[str, Any]:
    """Assert ``s`` is exactly one valid JSON object line. Returns the parsed dict.

    Raises :class:`ContractError` if it is not single-line or not valid JSON.
    """
    import json

    stripped = s.rstrip("\n")
    if "\n" in stripped:
        raise ContractError(
            "stdout contract violated: more than one line",
            stage="contract",
            details={"preview": stripped[:200]},
        )
    try:
        obj = json.loads(stripped)
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            "stdout contract violated: not valid JSON",
            stage="contract",
            details={"preview": stripped[:200], "error": str(exc)},
        ) from exc
    if not isinstance(obj, dict):
        raise ContractError(
            "stdout contract violated: top-level JSON must be an object",
            stage="contract",
            details={"type": type(obj).__name__},
        )
    return obj


def emit_result_line(result: dict[str, Any], *, stream: TextIO | None = None) -> str:
    """Write exactly one compact JSON line to ``stream`` (default real stdout).

    Returns the line written (without trailing newline). Never raises on
    serialization (uses safe_json_dumps); the resulting line is validated.
    """
    line = safe_json_dumps(result, compact=True)
    if "\n" in line:
        # Should be impossible with compact separators, but enforce.
        line = line.replace("\n", " ")
    target = stream if stream is not None else sys.__stdout__
    if target is None:  # pragma: no cover - exotic environments
        target = sys.stdout
    target.write(line + "\n")
    try:
        target.flush()
    except Exception:  # pragma: no cover - defensive
        pass
    return line


@contextlib.contextmanager
def capture_stdout_stderr(out_dir: Path) -> Iterator[Callable[[dict[str, Any]], str]]:
    """Redirect stdout/stderr to log files; yield a result-emitter.

    Usage::

        with capture_stdout_stderr(out_dir) as emit:
            ... run everything (all prints go to log files) ...
            emit({"status": "success", ...})  # -> real stdout, one line

    The yielded ``emit`` writes to the ORIGINAL stdout captured at entry, so it
    bypasses the redirection. If ``emit`` is never called, the real stdout stays
    empty (the CLI is responsible for always emitting).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    real_stdout: TextIO = sys.stdout
    real_stderr: TextIO = sys.stderr
    saved_stdout = sys.stdout
    saved_stderr = sys.stderr

    stdout_log = (out_dir / STDOUT_LOG).open("w", encoding="utf-8", buffering=1)
    stderr_log = (out_dir / STDERR_LOG).open("w", encoding="utf-8", buffering=1)

    emitted: dict[str, bool] = {"done": False}

    def emit(result: dict[str, Any]) -> str:
        # Always write the single result line to the REAL stdout.
        line = emit_result_line(result, stream=real_stdout)
        emitted["done"] = True
        return line

    sys.stdout = stdout_log  # type: ignore[assignment]
    sys.stderr = stderr_log  # type: ignore[assignment]
    try:
        yield emit
    finally:
        # Restore first so any teardown printing is visible normally.
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
        with contextlib.suppress(Exception):
            stdout_log.flush()
            stdout_log.close()
        with contextlib.suppress(Exception):
            stderr_log.flush()
            stderr_log.close()


class _NullWriter(io.TextIOBase):
    """A stream that swallows everything (used as a last-resort guard)."""

    def write(self, s: str) -> int:  # noqa: D401
        return len(s)

    def flush(self) -> None:  # pragma: no cover - trivial
        pass
