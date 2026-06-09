"""Core dataclasses: the public data contract.

These mirror the shapes in the task brief (Phase 2). They are intentionally
plain dataclasses with explicit ``to_dict`` helpers so they round-trip cleanly
to JSON for the BMK runner.

NO third-party imports.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from .errors import ErrorCode

# The literal set of terminal statuses. Kept in sync with ErrorCode.
HarnessStatus = Literal[
    "success",
    "failed",
    "invalid_harness",
    "adapter_failed",
    "dependency_error",
    "provider_error",
    "timeout",
    "permission_denied",
    "tool_error",
    "llm_error",
    "browser_error",
    "shell_error",
    "filesystem_error",
    "artifact_error",
    "contract_error",
    "unknown_error",
]


# --- Policies ------------------------------------------------------------- #


@dataclass
class RetryPolicy:
    """Exponential-backoff retry configuration.

    ``retry_on`` is a tuple of ErrorCode values (as strings) that are eligible
    for retry. ``jitter`` is a *deterministic* fraction (0..1) applied via an
    injected jitter source in :func:`harness_scaffold.core.retry.retry`.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.1
    retry_on: tuple[str, ...] = (
        ErrorCode.TIMEOUT.value,
        ErrorCode.PROVIDER_ERROR.value,
        ErrorCode.LLM_ERROR.value,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
            "jitter": self.jitter,
            "retry_on": list(self.retry_on),
        }


@dataclass
class RuntimePolicy:
    """All hard limits + capability gates for a single run.

    Defaults are conservative and fail-fast. Network and destructive FS are
    OFF by default; shell is ON (but still permission-checked).
    """

    max_steps: int = 50
    max_seconds: float = 900.0
    max_tool_seconds: float = 60.0
    max_llm_seconds: float = 120.0
    max_output_bytes: int = 200_000
    max_artifact_bytes: int = 10_000_000
    allow_network: bool = False
    allow_shell: bool = True
    allow_destructive_fs: bool = False
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_seconds": self.max_seconds,
            "max_tool_seconds": self.max_tool_seconds,
            "max_llm_seconds": self.max_llm_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "allow_network": self.allow_network,
            "allow_shell": self.allow_shell,
            "allow_destructive_fs": self.allow_destructive_fs,
            "retry_policy": self.retry_policy.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RuntimePolicy":
        """Build a policy from a (partial) config dict; unknown keys ignored."""
        d = dict(d or {})
        rp_raw = d.pop("retry_policy", None)
        kwargs: dict[str, Any] = {}
        valid = {f.name for f in dataclasses.fields(cls)} - {"retry_policy"}
        for k, v in d.items():
            if k in valid:
                kwargs[k] = v
        policy = cls(**kwargs)
        if isinstance(rp_raw, dict):
            rp_valid = {f.name for f in dataclasses.fields(RetryPolicy)}
            rp_kwargs = {k: v for k, v in rp_raw.items() if k in rp_valid}
            if "retry_on" in rp_kwargs and isinstance(rp_kwargs["retry_on"], list):
                rp_kwargs["retry_on"] = tuple(rp_kwargs["retry_on"])
            policy.retry_policy = RetryPolicy(**rp_kwargs)
        return policy


# --- Task / Result -------------------------------------------------------- #


@dataclass
class HarnessTask:
    """Input contract: what a harness is asked to do."""

    task_id: str
    prompt: str
    workdir: Path
    input_files: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    domain: Optional[str] = None
    benchmark_id: Optional[str] = None
    expected_artifacts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workdir = Path(self.workdir)
        self.input_files = [Path(p) for p in self.input_files]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "workdir": str(self.workdir),
            "input_files": [str(p) for p in self.input_files],
            "metadata": dict(self.metadata),
            "domain": self.domain,
            "benchmark_id": self.benchmark_id,
            "expected_artifacts": list(self.expected_artifacts),
        }


@dataclass
class HarnessResult:
    """Terminal output contract returned by the runtime."""

    status: HarnessStatus
    answer_path: Optional[Path]
    artifacts: dict[str, Path]
    trajectory_path: Path
    metadata_path: Path
    error_path: Optional[Path]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer_path": _opt_str(self.answer_path),
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "trajectory_path": _opt_str(self.trajectory_path),
            "metadata_path": _opt_str(self.metadata_path),
            "error_path": _opt_str(self.error_path),
            "metadata": dict(self.metadata),
        }

    def stdout_line(self, out_dir: Path) -> dict[str, Any]:
        """The minimal dict for the single stdout JSON line."""
        line: dict[str, Any] = {
            "status": self.status,
            "out_dir": str(out_dir),
            "metadata_path": _opt_str(self.metadata_path),
        }
        if self.error_path is not None:
            line["error_path"] = str(self.error_path)
        if self.answer_path is not None:
            line["answer_path"] = str(self.answer_path)
        return line


@dataclass
class ToolResult:
    """Uniform return value of every AtomicTool.

    Tools NEVER raise to the runtime; failures become ``ToolResult.fail``.
    """

    ok: bool
    data: Any = None
    error: Optional[dict[str, Any]] = None
    artifacts: dict[str, Path] = field(default_factory=dict)
    stdout_preview: Optional[str] = None
    stderr_preview: Optional[str] = None
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_result(
        cls,
        data: Any = None,
        *,
        artifacts: Optional[dict[str, Path]] = None,
        stdout_preview: Optional[str] = None,
        stderr_preview: Optional[str] = None,
        elapsed_seconds: float = 0.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ToolResult":
        return cls(
            ok=True,
            data=data,
            error=None,
            artifacts=dict(artifacts or {}),
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            elapsed_seconds=elapsed_seconds,
            metadata=dict(metadata or {}),
        )

    # Convenience alias matching the brief's ``ToolResult.ok(...)`` naming.
    # ``ok`` is also the boolean field, so the classmethod is named
    # ``ok_result`` and we expose ``success`` + ``fail`` as the documented API.
    success = ok_result

    @classmethod
    def fail(
        cls,
        error: "dict[str, Any] | str",
        *,
        error_code: Any = ErrorCode.TOOL_ERROR,
        stage: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        recoverable: Optional[bool] = None,
        artifacts: Optional[dict[str, Path]] = None,
        stdout_preview: Optional[str] = None,
        stderr_preview: Optional[str] = None,
        elapsed_seconds: float = 0.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ToolResult":
        # Lazy import to avoid a cycle (errors imports nothing from here).
        from .errors import build_error_json

        if isinstance(error, dict):
            err = error
        else:
            err = build_error_json(
                error_code=error_code,
                message=str(error),
                stage=stage,
                details=details,
                recoverable=recoverable,
                elapsed_seconds=elapsed_seconds,
            )
        return cls(
            ok=False,
            data=None,
            error=err,
            artifacts=dict(artifacts or {}),
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            elapsed_seconds=elapsed_seconds,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "artifacts": {k: str(v) for k, v in self.artifacts.items()},
            "stdout_preview": self.stdout_preview,
            "stderr_preview": self.stderr_preview,
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": dict(self.metadata),
        }


def now() -> float:
    return time.time()


def _opt_str(p: Any) -> Optional[str]:
    return None if p is None else str(p)
