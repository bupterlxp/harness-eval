"""Failure taxonomy and structured error types.

Every failure in the scaffold maps to a single :class:`ErrorCode`. This is the
stable contract a benchmark (BMK) runner relies on: the ``status`` of a
:class:`~harness_scaffold.core.schemas.HarnessResult` and the ``error_code`` in
``error.json`` are always drawn from this enum.

Design notes / extraction:
  Claude Code uses ad-hoc error shapes per tool plus a few discriminated unions
  in ``types/permissions.ts`` and tool result types. We collapse that into one
  flat, JSON-serializable taxonomy so generated harnesses cannot invent their
  own incompatible error vocabularies.

NO third-party imports. Stdlib only.
"""

from __future__ import annotations

import enum
from typing import Any, Optional


class ErrorCode(str, enum.Enum):
    """Full, flat failure taxonomy. ``str`` subclass => JSON-serializable as-is."""

    SUCCESS = "success"
    FAILED = "failed"
    INVALID_HARNESS = "invalid_harness"
    ADAPTER_FAILED = "adapter_failed"
    DEPENDENCY_ERROR = "dependency_error"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    BROWSER_ERROR = "browser_error"
    SHELL_ERROR = "shell_error"
    FILESYSTEM_ERROR = "filesystem_error"
    ARTIFACT_ERROR = "artifact_error"
    CONTRACT_ERROR = "contract_error"
    UNKNOWN_ERROR = "unknown_error"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Codes that are, in general, worth retrying by a higher-level orchestrator.
RECOVERABLE_CODES = frozenset(
    {
        ErrorCode.TIMEOUT,
        ErrorCode.PROVIDER_ERROR,
        ErrorCode.LLM_ERROR,
        ErrorCode.DEPENDENCY_ERROR,
    }
)

# The subset of codes that are valid as a terminal HarnessResult.status.
# (All codes are technically allowed, but these are the documented ones.)
RESULT_STATUS_CODES = frozenset(c.value for c in ErrorCode)


def is_recoverable(code: "ErrorCode | str") -> bool:
    try:
        code = ErrorCode(code)
    except ValueError:
        return False
    return code in RECOVERABLE_CODES


class HarnessError(Exception):
    """Base structured exception.

    Carries everything needed to render an ``error.json`` entry. Tools should
    generally *not* raise these to the runtime (they convert to
    ``ToolResult.fail``), but the runtime and adapters use them freely.
    """

    error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR

    def __init__(
        self,
        message: str,
        *,
        error_code: "ErrorCode | str | None" = None,
        stage: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        recoverable: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = ErrorCode(error_code)
        self.stage = stage
        self.details: dict[str, Any] = dict(details or {})
        self.recoverable = (
            recoverable if recoverable is not None else is_recoverable(self.error_code)
        )

    def to_dict(self, *, elapsed_seconds: float = 0.0) -> dict[str, Any]:
        return build_error_json(
            error_code=self.error_code,
            message=self.message,
            stage=self.stage,
            details=self.details,
            recoverable=self.recoverable,
            elapsed_seconds=elapsed_seconds,
        )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}(code={self.error_code.value!r}, message={self.message!r})"


# --- Concrete subclasses -------------------------------------------------- #


class DependencyError(HarnessError):
    error_code = ErrorCode.DEPENDENCY_ERROR


class PermissionDenied(HarnessError):
    error_code = ErrorCode.PERMISSION_DENIED


class TimeoutErrorH(HarnessError):
    """Named ``TimeoutErrorH`` to avoid shadowing builtins/asyncio names."""

    error_code = ErrorCode.TIMEOUT


class ToolError(HarnessError):
    error_code = ErrorCode.TOOL_ERROR


class ProviderError(HarnessError):
    error_code = ErrorCode.PROVIDER_ERROR


class ContractError(HarnessError):
    error_code = ErrorCode.CONTRACT_ERROR


class AdapterError(HarnessError):
    error_code = ErrorCode.ADAPTER_FAILED


class BrowserError(HarnessError):
    error_code = ErrorCode.BROWSER_ERROR


class ShellError(HarnessError):
    error_code = ErrorCode.SHELL_ERROR


class FilesystemError(HarnessError):
    error_code = ErrorCode.FILESYSTEM_ERROR


class ArtifactError(HarnessError):
    error_code = ErrorCode.ARTIFACT_ERROR


class LLMError(HarnessError):
    error_code = ErrorCode.LLM_ERROR


class InvalidHarnessError(HarnessError):
    error_code = ErrorCode.INVALID_HARNESS


def build_error_json(
    *,
    error_code: "ErrorCode | str",
    message: str,
    stage: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    recoverable: Optional[bool] = None,
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """Build the canonical ``error.json`` dict.

    Schema (stable contract)::

        {
          "error_code": str,    # one of ErrorCode
          "message": str,
          "stage": str | None,
          "details": dict,
          "recoverable": bool,
          "elapsed_seconds": float
        }
    """
    code = ErrorCode(error_code)
    return {
        "error_code": code.value,
        "message": str(message),
        "stage": stage,
        "details": dict(details or {}),
        "recoverable": bool(recoverable if recoverable is not None else is_recoverable(code)),
        "elapsed_seconds": float(elapsed_seconds),
    }


def error_from_exception(
    exc: BaseException,
    *,
    default_code: "ErrorCode | str" = ErrorCode.UNKNOWN_ERROR,
    stage: Optional[str] = None,
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """Best-effort conversion of an arbitrary exception to an error.json dict.

    Never raises. Tracebacks are NOT included here (they go to stderr.log); the
    ``details`` carry only the exception type for debuggability.
    """
    if isinstance(exc, HarnessError):
        d = exc.to_dict(elapsed_seconds=elapsed_seconds)
        if stage and not d.get("stage"):
            d["stage"] = stage
        return d
    return build_error_json(
        error_code=default_code,
        message=f"{type(exc).__name__}: {exc}",
        stage=stage,
        details={"exception_type": type(exc).__name__},
        recoverable=False,
        elapsed_seconds=elapsed_seconds,
    )
