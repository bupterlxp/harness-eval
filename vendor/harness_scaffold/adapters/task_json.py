"""task.json adapter: load/validate a HarnessTask from disk.

Required fields: ``task_id``, ``prompt``, ``workdir``. Paths are resolved
(workdir relative to the task.json's directory if not absolute). Bad input
raises :class:`ContractError`.

NO third-party imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..core.errors import ContractError
from ..core.schemas import HarnessTask

_REQUIRED = ("task_id", "prompt", "workdir")


def load_task(path: Path) -> HarnessTask:
    path = Path(path)
    if not path.exists():
        raise ContractError(
            f"task-json not found: {path}",
            stage="adapter",
            details={"path": str(path)},
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            f"task-json is not valid JSON: {exc}",
            stage="adapter",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    return parse_task(raw, base_dir=path.parent)


def parse_task(raw: dict[str, Any], *, base_dir: Optional[Path] = None) -> HarnessTask:
    if not isinstance(raw, dict):
        raise ContractError(
            "task-json top-level must be an object",
            stage="adapter",
            details={"type": type(raw).__name__},
        )
    missing = [k for k in _REQUIRED if k not in raw or raw[k] in (None, "")]
    if missing:
        raise ContractError(
            f"task-json missing required fields: {missing}",
            stage="adapter",
            details={"missing": missing, "required": list(_REQUIRED)},
        )

    base = Path(base_dir) if base_dir else Path.cwd()
    workdir = _resolve_path(raw["workdir"], base)
    input_files = [_resolve_path(p, base) for p in (raw.get("input_files") or [])]

    return HarnessTask(
        task_id=str(raw["task_id"]),
        prompt=str(raw["prompt"]),
        workdir=workdir,
        input_files=input_files,
        metadata=dict(raw.get("metadata") or {}),
        domain=raw.get("domain"),
        benchmark_id=raw.get("benchmark_id"),
        expected_artifacts=list(raw.get("expected_artifacts") or []),
    )


def _resolve_path(p: Any, base: Path) -> Path:
    pp = Path(str(p)).expanduser()
    if not pp.is_absolute():
        pp = (base / pp)
    return pp


def example_task(workdir: Optional[Path] = None) -> HarnessTask:
    """A trivial valid task for smoke tests / docs."""
    wd = Path(workdir) if workdir else Path.cwd()
    return HarnessTask(
        task_id="example-task",
        prompt="Write a one-line summary to response.md.",
        workdir=wd,
        input_files=[],
        metadata={},
        domain="generic",
    )


def example_task_dict(workdir: Optional[Path] = None) -> dict[str, Any]:
    return example_task(workdir).to_dict()
