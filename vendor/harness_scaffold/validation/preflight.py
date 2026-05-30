"""Preflight checks BEFORE running a harness. NEVER installs anything.

Verifies the workdir exists/readable, out_dir is creatable/writable, required
tools are present in the registry, and probes optional deps with a short timeout.

NO third-party imports.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..core.dependency import probe_optional
from ..core.schemas import HarnessTask, RuntimePolicy


def preflight(
    task: HarnessTask,
    policy: RuntimePolicy,
    *,
    required_tools: Optional[list[str]] = None,
    optional_deps: Optional[list[str]] = None,
    registry: Optional[Any] = None,
    out_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Return a structured preflight report; ``ok`` true if no blocking issues."""
    issues: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    # workdir
    wd = Path(task.workdir)
    wd_ok = wd.exists() and wd.is_dir()
    checks["workdir_exists"] = wd_ok
    if not wd_ok:
        issues.append({"check": "workdir_exists", "detail": str(wd)})
    else:
        checks["workdir_readable"] = os.access(wd, os.R_OK)
        if not checks["workdir_readable"]:
            issues.append({"check": "workdir_readable", "detail": str(wd)})

    # out_dir creatable / writable
    if out_dir is not None:
        od = Path(out_dir)
        creatable = _check_creatable(od)
        checks["out_dir_writable"] = creatable
        if not creatable:
            issues.append({"check": "out_dir_writable", "detail": str(od)})

    # input files
    missing_inputs = [str(p) for p in task.input_files if not Path(p).exists()]
    checks["input_files_present"] = len(missing_inputs) == 0
    if missing_inputs:
        issues.append({"check": "input_files_present", "detail": missing_inputs})

    # required tools
    if required_tools:
        reg = registry
        if reg is None:
            from ..tools.registry import default_registry

            reg = default_registry()
        missing_tools = [t for t in required_tools if not reg.has(t)]
        checks["required_tools_available"] = len(missing_tools) == 0
        if missing_tools:
            issues.append({"check": "required_tools_available", "detail": missing_tools})

    # optional deps (probed, never blocking)
    dep_report: dict[str, Any] = {}
    if optional_deps:
        dep_report = probe_optional(optional_deps, timeout_seconds=5.0)
    checks["optional_dependencies"] = dep_report

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "checks": checks,
        "policy": policy.to_dict(),
    }


def _check_creatable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(path), delete=True):
            pass
        return True
    except Exception:  # noqa: BLE001
        return False
