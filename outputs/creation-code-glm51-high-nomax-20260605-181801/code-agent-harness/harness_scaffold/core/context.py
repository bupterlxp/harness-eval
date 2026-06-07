"""RuntimeContext: the per-run object every tool and program receives.

It bundles task, paths, and all runtime services (artifact store, trajectory,
permissions, budget, abort signal, policy, optional llm, clock). Tools reach
everything they need through ``ctx``; they do not construct their own services.

NO third-party imports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .abort import AbortSignal
from .artifacts import ArtifactStore
from .budgets import Budget
from .permissions import PermissionPolicy
from .schemas import HarnessTask, RuntimePolicy
from .trajectory import TrajectoryLogger


@dataclass
class RuntimeContext:
    task: HarnessTask
    workdir: Path
    out_dir: Path
    artifact_store: ArtifactStore
    trajectory: TrajectoryLogger
    permissions: PermissionPolicy
    budget: Budget
    abort_signal: AbortSignal
    policy: RuntimePolicy
    metadata: dict[str, Any] = field(default_factory=dict)
    llm: Optional[Any] = None  # LLMClient | None (avoid import cycle)
    clock: Callable[[], float] = time.time

    # --- convenience helpers -------------------------------------------- #

    def log_event(self, event: dict[str, Any]) -> None:
        self.trajectory.append(event)

    def new_artifact_text(self, name: str, content: str, *, kind: str = "text") -> Path:
        path = self.artifact_store.put_text(name, content, kind=kind)
        self.trajectory.log_artifact(name, path, kind=kind, step=self.budget.steps_used)
        return path

    def new_artifact_json(self, name: str, obj: Any, *, kind: str = "json") -> Path:
        path = self.artifact_store.put_json(name, obj, kind=kind)
        self.trajectory.log_artifact(name, path, kind=kind, step=self.budget.steps_used)
        return path

    def new_artifact_bytes(self, name: str, content: bytes, *, kind: str = "binary") -> Path:
        path = self.artifact_store.put_bytes(name, content, kind=kind)
        self.trajectory.log_artifact(name, path, kind=kind, step=self.budget.steps_used)
        return path

    # Generic dispatcher used by tools that don't care about the type.
    def new_artifact(self, name: str, content: Any, *, kind: Optional[str] = None) -> Path:
        if isinstance(content, bytes):
            return self.new_artifact_bytes(name, content, kind=kind or "binary")
        if isinstance(content, str):
            return self.new_artifact_text(name, content, kind=kind or "text")
        return self.new_artifact_json(name, content, kind=kind or "json")

    def check_path_read(self, path: Path) -> Path:
        return self.permissions.check_path_read(path)

    def check_path_write(self, path: Path) -> Path:
        return self.permissions.check_path_write(path)

    def time_left(self) -> float:
        """Seconds left in the overall budget; min with abort deadline implied."""
        return self.budget.seconds_left()

    def step(self, n: int = 1) -> int:
        return self.budget.step(n)

    def check_abort(self, *, stage: Optional[str] = None) -> None:
        self.abort_signal.raise_if_aborted(stage=stage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "workdir": str(self.workdir),
            "out_dir": str(self.out_dir),
            "policy": self.policy.to_dict(),
            "permissions": self.permissions.to_dict(),
            "budget": self.budget.to_dict(),
            "abort": self.abort_signal.to_dict(),
            "metadata": dict(self.metadata),
            "has_llm": self.llm is not None,
        }


def build_context(
    task: HarnessTask,
    out_dir: Path,
    policy: RuntimePolicy,
    *,
    clock: Callable[[], float] = time.time,
    llm: Optional[Any] = None,
    artifact_store: Optional[ArtifactStore] = None,
    trajectory: Optional[TrajectoryLogger] = None,
    permissions: Optional[PermissionPolicy] = None,
    budget: Optional[Budget] = None,
    abort_signal: Optional[AbortSignal] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> RuntimeContext:
    """Factory that wires up all default services for a run.

    The runtime normally constructs the services and passes them in, but this
    factory lets examples/tests build a context in one call.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = Path(task.workdir)

    store = artifact_store or ArtifactStore(out_dir, max_artifact_bytes=policy.max_artifact_bytes)
    traj = trajectory or TrajectoryLogger(out_dir / "trajectory.jsonl", clock=clock)
    perms = permissions or PermissionPolicy(
        workdir,
        out_dir,
        allow_network=policy.allow_network,
        allow_shell=policy.allow_shell,
        allow_destructive_fs=policy.allow_destructive_fs,
    )
    bud = budget or Budget(
        max_steps=policy.max_steps,
        max_seconds=policy.max_seconds,
        max_output_bytes=policy.max_output_bytes,
    )
    abort = abort_signal or AbortSignal(deadline_seconds=policy.max_seconds)

    return RuntimeContext(
        task=task,
        workdir=workdir,
        out_dir=out_dir,
        artifact_store=store,
        trajectory=traj,
        permissions=perms,
        budget=bud,
        abort_signal=abort,
        policy=policy,
        metadata=dict(metadata or {}),
        llm=llm,
        clock=clock,
    )
