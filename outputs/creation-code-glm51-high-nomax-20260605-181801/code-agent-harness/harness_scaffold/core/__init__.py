"""Core runtime layer (stdlib-only).

Re-exports the consistency-critical primitives. Leaf tools and adapters import
from here. Nothing in this package imports a third-party module at top level.
"""

from __future__ import annotations

from .abort import AbortSignal, Aborted
from .artifacts import ArtifactStore
from .budgets import Budget
from .context import RuntimeContext, build_context
from .dependency import check_dependencies, probe_optional, require
from .errors import (
    AdapterError,
    ArtifactError,
    BrowserError,
    ContractError,
    DependencyError,
    ErrorCode,
    FilesystemError,
    HarnessError,
    InvalidHarnessError,
    LLMError,
    PermissionDenied,
    ProviderError,
    ShellError,
    TimeoutErrorH,
    ToolError,
    build_error_json,
    error_from_exception,
    is_recoverable,
)
from .permissions import PermissionPolicy
from .retry import retry
from .runtime import HarnessRuntime, build_failed_result
from .schemas import (
    HarnessResult,
    HarnessStatus,
    HarnessTask,
    RetryPolicy,
    RuntimePolicy,
    ToolResult,
)
from .serialization import safe_json_dumps, truncate, write_json_file
from .stdout_contract import (
    capture_stdout_stderr,
    emit_result_line,
    validate_single_json_line,
)
from .timeouts import Deadline, async_timeout, run_with_timeout
from .trajectory import TrajectoryLogger

from . import events

__all__ = [
    # schemas
    "HarnessTask",
    "HarnessResult",
    "HarnessStatus",
    "ToolResult",
    "RuntimePolicy",
    "RetryPolicy",
    # context / runtime
    "RuntimeContext",
    "build_context",
    "HarnessRuntime",
    "build_failed_result",
    # services
    "ArtifactStore",
    "TrajectoryLogger",
    "PermissionPolicy",
    "Budget",
    "AbortSignal",
    "Aborted",
    "Deadline",
    # helpers
    "events",
    "retry",
    "require",
    "probe_optional",
    "check_dependencies",
    "run_with_timeout",
    "async_timeout",
    "safe_json_dumps",
    "truncate",
    "write_json_file",
    "capture_stdout_stderr",
    "emit_result_line",
    "validate_single_json_line",
    # errors
    "ErrorCode",
    "HarnessError",
    "DependencyError",
    "PermissionDenied",
    "TimeoutErrorH",
    "ToolError",
    "ProviderError",
    "ContractError",
    "AdapterError",
    "BrowserError",
    "ShellError",
    "FilesystemError",
    "ArtifactError",
    "LLMError",
    "InvalidHarnessError",
    "build_error_json",
    "error_from_exception",
    "is_recoverable",
]
