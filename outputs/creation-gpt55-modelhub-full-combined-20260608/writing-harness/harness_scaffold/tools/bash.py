"""BashTool — execute a shell command in a sandboxed subprocess.

Conforms to the frozen interface spec (AtomicTool). The tool runs a command via
the OS shell in a fresh session/process-group so the whole tree can be killed on
timeout, enforces the configured denylist / shell gating through
``ctx.permissions.check_shell``, caps stdout/stderr to ``max_output_bytes`` and
records the exit code. It never prints to stdout and never raises to the caller:
all failures are returned as ``ToolResult.fail(...)`` with a structured error code
(``shell_error`` / ``timeout`` / ``permission_denied``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    ShellError,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from .base import AtomicTool, SubprocessResult, _run_subprocess


class BashTool(AtomicTool):
    name = "bash"
    description = (
        "Execute a shell command inside the sandbox working directory. "
        "Runs the command through the system shell in a fresh process group, "
        "enforces a timeout (defaulting to the runtime per-tool limit and "
        "clamped to the remaining time budget), captures truncated stdout/stderr "
        "and returns the process exit code. The command is checked against the "
        "permission denylist (and package installs / network access are blocked "
        "unless explicitly allowed). Requires shell execution to be enabled."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": (
                    "Working directory for the command. Defaults to the task "
                    "workdir. Must resolve inside the sandbox."
                ),
            },
            "timeout": {
                "type": "number",
                "description": (
                    "Optional timeout in seconds. Clamped to the runtime maximum "
                    "per-tool timeout and the remaining time budget."
                ),
            },
            "env": {
                "type": "object",
                "description": "Optional environment variables to inject.",
            },
        },
        "required": ["command"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "timed_out": {"type": "boolean"},
        },
    }
    is_read_only = False
    is_destructive = True
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult.fail(
                "bash: 'command' is required and must be a non-empty string",
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
            )

        # Abort/budget check before doing any work.
        try:
            ctx.check_abort(stage=self.name)
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)

        # Permission / denylist / shell gating. Raises PermissionDenied
        # (a HarnessError) which the execute() wrapper converts; we also handle
        # it here so run() itself never raises.
        try:
            ctx.permissions.check_shell(command)
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)

        # Resolve working directory inside the sandbox.
        cwd_arg = args.get("cwd")
        if cwd_arg:
            try:
                cwd = ctx.check_path_write(Path(cwd_arg))
            except HarnessError:
                # A read check is enough to confine the cwd; fall back to it so a
                # read-only directory can still be used as cwd.
                try:
                    cwd = ctx.check_path_read(Path(cwd_arg))
                except HarnessError as exc:
                    return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)
        else:
            cwd = ctx.workdir

        # Resolve and clamp timeout.
        timeout = self._resolve_timeout(ctx, args.get("timeout"))

        env = args.get("env") if isinstance(args.get("env"), dict) else None

        try:
            res: SubprocessResult = _run_subprocess(
                command,
                ctx=ctx,
                cwd=cwd,
                timeout=timeout,
                env=env,
                shell=True,
                max_output_bytes=ctx.policy.max_output_bytes,
            )
        except TimeoutErrorH as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=ErrorCode.TIMEOUT,
                stage=self.name,
            )
        except ShellError as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
            )
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)

        data: dict[str, Any] = {
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "truncated": res.truncated,
            "timed_out": res.timed_out,
        }
        preview = res.stdout if res.stdout else res.stderr
        ok = res.returncode == 0
        if not ok:
            # Non-zero exit is reported as a structured shell_error but we still
            # surface stdout/stderr/exit_code in the error details for debugging.
            return ToolResult.fail(
                f"command exited with code {res.returncode}",
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
                details=data,
                recoverable=True,
                stdout_preview=(res.stdout or "")[:2000],
                stderr_preview=(res.stderr or "")[:2000],
                elapsed_seconds=res.elapsed_seconds,
                metadata={"exit_code": res.returncode},
            )
        return ToolResult.success(
            data=data,
            stdout_preview=(preview or "")[:2000],
            stderr_preview=(res.stderr or "")[:2000] or None,
            elapsed_seconds=res.elapsed_seconds,
            metadata={"exit_code": res.returncode, "truncated": res.truncated},
        )

    @staticmethod
    def _resolve_timeout(ctx: RuntimeContext, requested) -> float:
        """Clamp a requested timeout to the per-tool maximum."""
        max_t = float(ctx.policy.max_tool_seconds)
        if requested is None:
            return max_t
        try:
            req = float(requested)
        except (TypeError, ValueError):
            return max_t
        if req <= 0:
            return max_t
        return min(req, max_t)


def get_tools() -> list[AtomicTool]:
    return [BashTool()]
