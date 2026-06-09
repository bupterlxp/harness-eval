"""PythonExecTool — run Python source via an out-of-process interpreter.

Conforms to the frozen interface spec (AtomicTool). The tool executes Python
code in a separate ``python`` subprocess (NOT in-process ``exec``) so that the
runtime is isolated from crashes, infinite loops and resource leaks. Like
BashTool it runs in a fresh session/process-group (killed as a group on
timeout), enforces the per-tool timeout clamped to the remaining budget, caps
stdout/stderr and records the exit code. It never prints to stdout and never
raises to the caller.
"""
from __future__ import annotations

import sys
import tempfile
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


class PythonExecTool(AtomicTool):
    name = "python_exec"
    description = (
        "Execute Python source code in an isolated subprocess (never in-process). "
        "The code runs with the same interpreter as the host, in a fresh process "
        "group within the sandbox working directory, under the runtime per-tool "
        "timeout (clamped to the remaining budget). Captured stdout/stderr are "
        "truncated to the output limit and the process exit code is returned. "
        "Optionally accepts a list of string arguments exposed as sys.argv and "
        "stdin text. No package installation or network access unless the policy "
        "explicitly allows it."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional arguments exposed to the script as sys.argv[1:].",
            },
            "stdin": {
                "type": "string",
                "description": "Optional text fed to the script's standard input.",
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
        "required": ["code"],
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
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult.fail(
                "python_exec: 'code' is required and must be a non-empty string",
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
            )

        try:
            ctx.check_abort(stage=self.name)
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)

        # Running Python is a form of shell execution; gate it the same way so
        # the allow_shell flag and any global denylist still apply.
        try:
            ctx.permissions.check_shell("python_exec")
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(), error_code=exc.error_code)

        argv = args.get("argv")
        if argv is not None and (
            not isinstance(argv, list) or not all(isinstance(a, str) for a in argv)
        ):
            return ToolResult.fail(
                "python_exec: 'argv' must be a list of strings",
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
            )

        stdin_text = args.get("stdin")
        if stdin_text is not None and not isinstance(stdin_text, str):
            return ToolResult.fail(
                "python_exec: 'stdin' must be a string",
                error_code=ErrorCode.SHELL_ERROR,
                stage=self.name,
            )

        timeout = self._resolve_timeout(ctx, args.get("timeout"))
        env = args.get("env") if isinstance(args.get("env"), dict) else None

        # Write the code to a temp file inside the sandbox so it shows up as a
        # real script (better tracebacks) and is cleaned up afterwards.
        tmp_path: Path | None = None
        try:
            workdir = Path(ctx.workdir)
            workdir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix="_python_exec_", suffix=".py", dir=str(workdir)
            )
            tmp_path = Path(tmp_name)
            with open(fd, "w", encoding="utf-8") as fh:
                fh.write(code)

            cmd = [sys.executable, "-I", str(tmp_path)]
            if argv:
                cmd.extend(argv)

            try:
                res: SubprocessResult = _run_subprocess(
                    cmd,
                    ctx=ctx,
                    cwd=workdir,
                    timeout=timeout,
                    env=env,
                    shell=False,
                    max_output_bytes=ctx.policy.max_output_bytes,
                    input_text=stdin_text,
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
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        data: dict[str, Any] = {
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "truncated": res.truncated,
            "timed_out": res.timed_out,
        }
        if res.returncode != 0:
            return ToolResult.fail(
                f"python exited with code {res.returncode}",
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
            stdout_preview=(res.stdout or "")[:2000],
            stderr_preview=(res.stderr or "")[:2000] or None,
            elapsed_seconds=res.elapsed_seconds,
            metadata={"exit_code": res.returncode, "truncated": res.truncated},
        )

    @staticmethod
    def _resolve_timeout(ctx: RuntimeContext, requested) -> float:
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
    return [PythonExecTool()]
