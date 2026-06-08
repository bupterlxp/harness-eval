"""HarnessRuntime: the universal run loop wrapper.

Responsibilities (all guaranteed, regardless of what the program does):
  * create ``out_dir`` and all standard services;
  * run ``program.run(ctx, tools, llm)`` under the overall ``max_seconds``
    timeout and the stdout-capture context;
  * map ANY exception to an ErrorCode and write ``error.json``;
  * ALWAYS write ``metadata.json``, ensure ``response.md`` exists (stub if the
    program didn't write one), ``trajectory.jsonl`` and ``artifacts.json``;
  * return a :class:`HarnessResult`.

The program decides domain logic; the runtime enforces the contract.

NO third-party imports.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Any, Optional

from . import events as ev
from .abort import AbortSignal
from .artifacts import ArtifactStore
from .budgets import Budget
from .context import RuntimeContext
from .errors import (
    ErrorCode,
    HarnessError,
    build_error_json,
    error_from_exception,
)
from .permissions import PermissionPolicy
from .schemas import HarnessResult, HarnessTask, RuntimePolicy, ToolResult
from .serialization import write_json_file
from .stdout_contract import capture_stdout_stderr
from .timeouts import async_timeout
from .trajectory import TrajectoryLogger

# Standard out-dir filenames.
RESPONSE_NAME = "response.md"
METADATA_NAME = "metadata.json"
ERROR_NAME = "error.json"
TRAJECTORY_NAME = "trajectory.jsonl"
ARTIFACTS_NAME = "artifacts.json"


class HarnessRuntime:
    def __init__(
        self,
        tools: Any,  # ToolRegistry (avoid hard import cycle)
        llm: Optional[Any],
        policy: RuntimePolicy,
        *,
        clock: Any = time.time,
    ) -> None:
        self.tools = tools
        self.llm = llm
        self.policy = policy
        self.clock = clock

    async def run(
        self,
        task: HarnessTask,
        program: Any,  # HarnessProgram
        out_dir: Path,
    ) -> HarnessResult:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        run_start = time.monotonic()

        # Build all services up front so we can always write artifacts.
        store = ArtifactStore(out_dir, max_artifact_bytes=self.policy.max_artifact_bytes)
        trajectory = TrajectoryLogger(out_dir / TRAJECTORY_NAME, clock=self.clock)
        permissions = PermissionPolicy(
            task.workdir,
            out_dir,
            allow_network=self.policy.allow_network,
            allow_shell=self.policy.allow_shell,
            allow_destructive_fs=self.policy.allow_destructive_fs,
        )
        budget = Budget(
            max_steps=self.policy.max_steps,
            max_seconds=self.policy.max_seconds,
            max_output_bytes=self.policy.max_output_bytes,
        )
        abort = AbortSignal(deadline_seconds=self.policy.max_seconds)
        ctx = RuntimeContext(
            task=task,
            workdir=Path(task.workdir),
            out_dir=out_dir,
            artifact_store=store,
            trajectory=trajectory,
            permissions=permissions,
            budget=budget,
            abort_signal=abort,
            policy=self.policy,
            metadata={},
            llm=self.llm,
            clock=self.clock,
        )

        status: str = ErrorCode.UNKNOWN_ERROR.value
        error_path: Optional[Path] = None
        answer_path: Optional[Path] = None
        program_result: Optional[HarnessResult] = None
        error_obj: Optional[dict[str, Any]] = None

        trajectory.log_info(
            "run_start",
            task_id=task.task_id,
            program=getattr(program, "name", type(program).__name__),
        )

        # Everything runs inside the stdout-capture context: any stray print
        # from the program/libs lands in stdout.log, never on real stdout.
        with capture_stdout_stderr(out_dir):
            try:
                program_result = await async_timeout(
                    self._invoke_program(ctx, program),
                    self.policy.max_seconds,
                    stage="runtime",
                    details={"task_id": task.task_id},
                )
                if isinstance(program_result, HarnessResult):
                    status = program_result.status
                    answer_path = program_result.answer_path
                    if status != ErrorCode.SUCCESS.value:
                        error_obj = program_result.metadata.get("error") if program_result.metadata else None
                else:
                    # Program returned something unexpected.
                    status = ErrorCode.SUCCESS.value
            except HarnessError as exc:
                error_obj = exc.to_dict(elapsed_seconds=time.monotonic() - run_start)
                status = exc.error_code.value
                trajectory.log_error(error_obj, step=budget.steps_used)
                # Tracebacks go to the (captured) stderr, never to real stdout.
                traceback.print_exc()
            except Exception as exc:  # noqa: BLE001
                error_obj = error_from_exception(
                    exc,
                    default_code=ErrorCode.FAILED,
                    stage="runtime",
                    elapsed_seconds=time.monotonic() - run_start,
                )
                status = error_obj["error_code"]
                trajectory.log_error(error_obj, step=budget.steps_used)
                traceback.print_exc()

        # --- ALWAYS finalize the out-dir contract ----------------------- #

        # 1) error.json if we have an error.
        if error_obj is not None:
            error_path = write_json_file(out_dir / ERROR_NAME, error_obj)

        # 2) response.md must exist (stub if program didn't write one).
        answer_path = self._ensure_response(out_dir, answer_path, status, program_result)

        # 3) artifacts.json (manifest) — include any artifacts the program
        #    registered plus the standard files.
        self._register_standard_artifacts(store, out_dir, answer_path, error_path)
        artifacts_path = store.write_manifest()

        # 4) metadata.json.
        elapsed = time.monotonic() - run_start
        metadata = self._build_metadata(
            task=task,
            program=program,
            status=status,
            elapsed_seconds=elapsed,
            budget=budget,
            store=store,
            trajectory=trajectory,
            error_obj=error_obj,
        )
        metadata_path = write_json_file(out_dir / METADATA_NAME, metadata)

        trajectory.log_info("run_end", status=status, elapsed_seconds=elapsed)

        artifacts_map = dict(store.paths())
        artifacts_map.setdefault("artifacts_manifest", artifacts_path)

        return HarnessResult(
            status=status,  # type: ignore[arg-type]
            answer_path=answer_path,
            artifacts=artifacts_map,
            trajectory_path=out_dir / TRAJECTORY_NAME,
            metadata_path=metadata_path,
            error_path=error_path,
            metadata=metadata,
        )

    # --- internals ------------------------------------------------------- #

    async def _invoke_program(self, ctx: RuntimeContext, program: Any) -> HarnessResult:
        run = getattr(program, "run", None)
        if not callable(run):
            raise HarnessError(
                "program has no callable 'run(ctx, tools, llm)'",
                error_code=ErrorCode.INVALID_HARNESS,
                stage="runtime",
                details={"program": type(program).__name__},
            )
        result = run(ctx, self.tools, self.llm)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def _ensure_response(
        self,
        out_dir: Path,
        answer_path: Optional[Path],
        status: str,
        program_result: Optional[HarnessResult],
    ) -> Path:
        # Prefer the program-declared answer path if it exists on disk.
        if answer_path is not None and Path(answer_path).exists():
            return Path(answer_path)
        default = out_dir / RESPONSE_NAME
        if default.exists():
            return default
        # Write a stub so the contract always has a response.md.
        stub = (
            f"# Harness Response\n\n"
            f"status: {status}\n\n"
            f"(No response.md was produced by the program.)\n"
        )
        default.write_text(stub, encoding="utf-8")
        return default

    def _register_standard_artifacts(
        self,
        store: ArtifactStore,
        out_dir: Path,
        answer_path: Optional[Path],
        error_path: Optional[Path],
    ) -> None:
        standard = {
            "response": out_dir / RESPONSE_NAME,
            "trajectory": out_dir / TRAJECTORY_NAME,
            "stdout_log": out_dir / "stdout.log",
            "stderr_log": out_dir / "stderr.log",
        }
        if error_path is not None:
            standard["error"] = error_path
        for name, path in standard.items():
            if path.exists() and store.get(name) is None:
                try:
                    store.register(name, path, kind="standard")
                except Exception:  # pragma: no cover - defensive
                    pass

    def _build_metadata(
        self,
        *,
        task: HarnessTask,
        program: Any,
        status: str,
        elapsed_seconds: float,
        budget: Budget,
        store: ArtifactStore,
        trajectory: TrajectoryLogger,
        error_obj: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "benchmark_id": task.benchmark_id,
            "domain": task.domain,
            "program": getattr(program, "name", type(program).__name__),
            "status": status,
            "timing": {
                "elapsed_seconds": round(elapsed_seconds, 4),
                "max_seconds": self.policy.max_seconds,
            },
            "steps": budget.steps_used,
            "budget": budget.snapshot(),
            "usage": dict(getattr(self.llm, "usage", {}) or {}) if self.llm else {},
            "policy": self.policy.to_dict(),
            "trajectory_events": trajectory.count,
            "manifest": store.manifest(),
            "error": error_obj,
        }

    # --- sync wrapper ---------------------------------------------------- #

    def run_sync(
        self, task: HarnessTask, program: Any, out_dir: Path
    ) -> HarnessResult:
        """Synchronous convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(task, program, out_dir))


def build_failed_result(
    out_dir: Path,
    *,
    status: str,
    error_obj: dict[str, Any],
) -> HarnessResult:
    """Construct a minimal HarnessResult + out-dir for failures that happen
    BEFORE/around the runtime (bad args, import errors). Writes error.json,
    a stub response.md, an empty trajectory, and metadata.json.

    Used by the CLI/adapters so even adapter-level failures honor the contract.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    error_path = write_json_file(out_dir / ERROR_NAME, error_obj)

    response = out_dir / RESPONSE_NAME
    if not response.exists():
        response.write_text(
            f"# Harness Response\n\nstatus: {status}\n\n{error_obj.get('message', '')}\n",
            encoding="utf-8",
        )

    trajectory = out_dir / TRAJECTORY_NAME
    if not trajectory.exists():
        traj = TrajectoryLogger(trajectory)
        traj.log_error(error_obj)

    store = ArtifactStore(out_dir)
    for name, p in {"response": response, "error": error_path, "trajectory": trajectory}.items():
        if p.exists():
            store.register(name, p, kind="standard")
    store.write_manifest()

    metadata = {
        "status": status,
        "timing": {"elapsed_seconds": error_obj.get("elapsed_seconds", 0.0)},
        "steps": 0,
        "error": error_obj,
    }
    metadata_path = write_json_file(out_dir / METADATA_NAME, metadata)

    return HarnessResult(
        status=status,  # type: ignore[arg-type]
        answer_path=response,
        artifacts=dict(store.paths()),
        trajectory_path=trajectory,
        metadata_path=metadata_path,
        error_path=error_path,
        metadata=metadata,
    )
