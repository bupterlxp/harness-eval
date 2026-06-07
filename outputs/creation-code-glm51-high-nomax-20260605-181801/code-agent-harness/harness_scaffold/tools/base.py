"""AtomicTool ABC + shared subprocess helper.

Every tool subclasses :class:`AtomicTool`, sets its metadata attributes, and
implements ``async run(ctx, args) -> ToolResult``. Tools MUST NOT raise to the
runtime: the :meth:`AtomicTool.execute` wrapper converts any exception into a
``ToolResult.fail`` with the right ErrorCode, applies the per-tool timeout, caps
output, runs permission checks, and logs tool_call / tool_result events.

``_run_subprocess`` is the shared, hardened subprocess runner used by shell/git
tools: own process group, hard timeout, kill-the-group on expiry, output caps.

NO third-party imports at module top level.
"""

from __future__ import annotations

import abc
import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    PermissionDenied,
    ShellError,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from ..core.serialization import truncate


class AtomicTool(abc.ABC):
    """Base class for all atomic tools.

    Subclasses set the class-level metadata attributes and implement ``run``.
    Use :meth:`execute` (not ``run``) to invoke a tool from a program/runtime so
    the safety wrapper applies.
    """

    name: str = "atomic_tool"
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object", "properties": {}}
    is_read_only: bool = True
    is_destructive: bool = False
    requires_network: bool = False
    requires_optional_dependency: bool = False
    # If set, the wrapper probes this module and fails fast with dependency_error.
    optional_dependency_module: Optional[str] = None
    optional_dependency_extra: Optional[str] = None

    @abc.abstractmethod
    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        """Implement the tool's behavior. Return a ToolResult.

        May raise; the :meth:`execute` wrapper converts exceptions. Inside
        ``run`` you may assume permission pre-checks for network/shell have NOT
        been done automatically beyond the wrapper-level gating; do explicit
        path checks via ``ctx.check_path_read/write``.
        """
        raise NotImplementedError

    # --- safe invocation wrapper ---------------------------------------- #

    async def execute(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        """Run the tool with timeout, output caps, gating, and trajectory logs.

        Never raises: always returns a ToolResult.
        """
        start = time.monotonic()
        step = ctx.budget.steps_used
        ctx.trajectory.log_tool_call(self.name, args, step=step)

        # Fail-fast gates BEFORE doing any work.
        gate_err = self._gate(ctx)
        if gate_err is not None:
            elapsed = time.monotonic() - start
            gate_err["elapsed_seconds"] = elapsed
            ctx.trajectory.log_tool_result(
                self.name, ok=False, elapsed_seconds=elapsed, error=gate_err, step=step
            )
            return ToolResult.fail(gate_err, elapsed_seconds=elapsed)

        timeout_s = ctx.policy.max_tool_seconds
        # Clamp to remaining overall budget so a tool can't overrun the run.
        budget_left = ctx.budget.seconds_left()
        if budget_left != float("inf"):
            timeout_s = max(0.0, min(timeout_s, budget_left))

        try:
            ctx.abort_signal.raise_if_aborted(stage=f"tool:{self.name}")
            if timeout_s and timeout_s > 0:
                result = await asyncio.wait_for(self.run(ctx, args), timeout=timeout_s)
            else:
                result = await self.run(ctx, args)
            if not isinstance(result, ToolResult):  # defensive
                result = ToolResult.ok_result(data=result)
            result = self._cap_output(ctx, result)
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            err = TimeoutErrorH(
                f"tool '{self.name}' timed out after {timeout_s:.3f}s",
                stage=f"tool:{self.name}",
                details={"timeout_seconds": timeout_s, "tool": self.name},
            ).to_dict(elapsed_seconds=elapsed)
            ctx.trajectory.log_tool_result(
                self.name, ok=False, elapsed_seconds=elapsed, error=err, step=step
            )
            return ToolResult.fail(err, elapsed_seconds=elapsed)
        except HarnessError as exc:
            elapsed = time.monotonic() - start
            err = exc.to_dict(elapsed_seconds=elapsed)
            ctx.trajectory.log_tool_result(
                self.name, ok=False, elapsed_seconds=elapsed, error=err, step=step
            )
            return ToolResult.fail(err, elapsed_seconds=elapsed)
        except Exception as exc:  # noqa: BLE001 - tools never raise to runtime
            elapsed = time.monotonic() - start
            err = HarnessError(
                f"tool '{self.name}' failed: {type(exc).__name__}: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
                details={"exception_type": type(exc).__name__, "tool": self.name},
            ).to_dict(elapsed_seconds=elapsed)
            ctx.trajectory.log_tool_result(
                self.name, ok=False, elapsed_seconds=elapsed, error=err, step=step
            )
            return ToolResult.fail(err, elapsed_seconds=elapsed)

        elapsed = time.monotonic() - start
        if result.elapsed_seconds == 0.0:
            result.elapsed_seconds = elapsed
        ctx.trajectory.log_tool_result(
            self.name,
            ok=result.ok,
            elapsed_seconds=result.elapsed_seconds,
            error=result.error,
            data_preview=_short(result.data),
            artifacts={k: str(v) for k, v in result.artifacts.items()} or None,
            step=step,
        )
        return result

    # --- gating helpers -------------------------------------------------- #

    def _gate(self, ctx: RuntimeContext) -> Optional[dict[str, Any]]:
        """Return an error dict if this tool is not permitted, else None."""
        if self.requires_network and not ctx.permissions.allow_network:
            return PermissionDenied(
                f"tool '{self.name}' requires network, which is disabled",
                stage=f"tool:{self.name}",
                details={"tool": self.name, "requires_network": True},
            ).to_dict()
        if self.optional_dependency_module:
            from ..core.dependency import probe_optional

            probe = probe_optional([self.optional_dependency_module], timeout_seconds=5.0)
            entry = probe[self.optional_dependency_module]
            if not entry["available"]:
                from ..core.errors import DependencyError

                return DependencyError(
                    f"tool '{self.name}' requires optional dependency "
                    f"'{self.optional_dependency_module}'",
                    stage=f"tool:{self.name}",
                    details={
                        "module": self.optional_dependency_module,
                        "pip_extra": self.optional_dependency_extra or entry.get("extra"),
                        "error": entry.get("error"),
                    },
                ).to_dict()
        return None

    def _cap_output(self, ctx: RuntimeContext, result: ToolResult) -> ToolResult:
        max_bytes = ctx.policy.max_output_bytes
        if result.stdout_preview is not None:
            result.stdout_preview = truncate(result.stdout_preview, max_bytes // 2 or 1)
        if result.stderr_preview is not None:
            result.stderr_preview = truncate(result.stderr_preview, max_bytes // 4 or 1)
        # Account produced output against the global budget.
        produced = 0
        for s in (result.stdout_preview, result.stderr_preview):
            if s:
                produced += len(s.encode("utf-8", errors="ignore"))
        if produced:
            ctx.budget.consume_output(produced)
        return result

    # --- spec ------------------------------------------------------------ #

    def spec(self) -> dict[str, Any]:
        """JSON-schema-ish spec for advertising to an LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "is_read_only": self.is_read_only,
            "is_destructive": self.is_destructive,
            "requires_network": self.requires_network,
            "requires_optional_dependency": self.requires_optional_dependency,
        }


def _short(data: Any, limit: int = 2000) -> Any:
    if isinstance(data, str):
        return truncate(data, limit)
    if isinstance(data, (list, dict)):
        s = str(data)
        if len(s) > limit:
            return s[:limit] + "...[truncated]"
    return data


# --------------------------------------------------------------------------- #
# Shared hardened subprocess runner (used by bash/python_exec/git tools).
# --------------------------------------------------------------------------- #


class SubprocessResult:
    __slots__ = ("returncode", "stdout", "stderr", "timed_out", "elapsed_seconds", "truncated")

    def __init__(
        self,
        returncode: Optional[int],
        stdout: str,
        stderr: str,
        timed_out: bool,
        elapsed_seconds: float,
        truncated: bool,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.elapsed_seconds = elapsed_seconds
        self.truncated = truncated

    def to_dict(self) -> dict[str, Any]:
        return {
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "elapsed_seconds": self.elapsed_seconds,
            "truncated": self.truncated,
        }


def _run_subprocess(
    cmd: "list[str] | str",
    *,
    ctx: RuntimeContext,
    cwd: Optional[Path] = None,
    timeout: Optional[float] = None,
    env: Optional[dict[str, str]] = None,
    shell: bool = False,
    max_output_bytes: Optional[int] = None,
    input_text: Optional[str] = None,
) -> SubprocessResult:
    """Run a subprocess with a hard timeout, process-group kill, and output caps.

    On POSIX it starts the child in its own session (``start_new_session``) so a
    timeout kills the whole process group, preventing orphaned children from
    hanging the experiment. Output beyond ``max_output_bytes`` is truncated.
    Raises :class:`TimeoutErrorH` on timeout, :class:`ShellError` on spawn error.
    """
    cwd = Path(cwd or ctx.workdir)
    timeout = ctx.policy.max_tool_seconds if timeout is None else timeout
    # Clamp to remaining budget.
    budget_left = ctx.budget.seconds_left()
    if budget_left != float("inf"):
        timeout = max(0.1, min(timeout, budget_left))
    cap = ctx.policy.max_output_bytes if max_output_bytes is None else max_output_bytes

    run_env = dict(os.environ)
    if env:
        run_env.update(env)

    start = time.monotonic()
    popen_kwargs: dict[str, Any] = dict(
        cwd=str(cwd),
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        text=True,
        errors="replace",
    )
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, shell=shell, **popen_kwargs)  # noqa: S603
    except (OSError, ValueError) as exc:
        raise ShellError(
            f"failed to spawn subprocess: {exc}",
            stage="shell",
            details={"cmd": _cmd_preview(cmd), "error": str(exc)},
        ) from exc

    timed_out = False
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:  # pragma: no cover - defensive
            stdout, stderr = "", ""
    except Exception as exc:  # noqa: BLE001
        _kill_process_tree(proc)
        raise ShellError(
            f"subprocess communication failed: {exc}",
            stage="shell",
            details={"cmd": _cmd_preview(cmd)},
        ) from exc

    elapsed = time.monotonic() - start
    stdout = stdout or ""
    stderr = stderr or ""
    truncated = False
    half = max(1, cap // 2)
    if len(stdout.encode("utf-8", "ignore")) > half:
        stdout = truncate(stdout, half)
        truncated = True
    if len(stderr.encode("utf-8", "ignore")) > half:
        stderr = truncate(stderr, half)
        truncated = True

    if timed_out:
        raise TimeoutErrorH(
            f"subprocess timed out after {timeout:.3f}s",
            stage="shell",
            details={
                "cmd": _cmd_preview(cmd),
                "timeout_seconds": timeout,
                "stdout_preview": stdout[:2000],
                "stderr_preview": stderr[:2000],
            },
        )

    return SubprocessResult(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
        elapsed_seconds=elapsed,
        truncated=truncated,
    )


def _kill_process_tree(proc: "subprocess.Popen[Any]") -> None:
    """Kill the process and its group (POSIX) or the process (others)."""
    try:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        else:  # pragma: no cover - non-posix
            proc.kill()
    except Exception:  # pragma: no cover - defensive
        pass


def _cmd_preview(cmd: "list[str] | str") -> str:
    if isinstance(cmd, list):
        return " ".join(str(c) for c in cmd)[:300]
    return str(cmd)[:300]
