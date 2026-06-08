"""Validate that an out-dir conforms to the BMK contract.

Checks required files exist, error.json (if present) matches the schema, and a
provided stdout string is a single valid JSON line.

NO third-party imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..adapters import bmk_io
from ..core.errors import ErrorCode
from ..core.stdout_contract import validate_single_json_line

_ERROR_REQUIRED_KEYS = {
    "error_code",
    "message",
    "stage",
    "details",
    "recoverable",
    "elapsed_seconds",
}


def check_out_dir(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    issues: list[str] = []
    present: dict[str, bool] = {}
    for name in bmk_io.REQUIRED_OUTPUT_FILES:
        ok = (out_dir / name).exists()
        present[name] = ok
        if not ok:
            issues.append(f"missing required file: {name}")

    # error.json schema (only if present)
    err = bmk_io.read_error(out_dir)
    error_ok = True
    if err is not None:
        missing = _ERROR_REQUIRED_KEYS - set(err.keys())
        if missing:
            error_ok = False
            issues.append(f"error.json missing keys: {sorted(missing)}")
        code = err.get("error_code")
        if code not in {c.value for c in ErrorCode}:
            error_ok = False
            issues.append(f"error.json has unknown error_code: {code!r}")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "files_present": present,
        "error_json_valid": error_ok,
    }


def check_stdout_line(stdout: str) -> dict[str, Any]:
    """Validate a captured CLI stdout is exactly one JSON line with status."""
    try:
        obj = validate_single_json_line(stdout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "issues": [str(exc)], "parsed": None}
    issues: list[str] = []
    if "status" not in obj:
        issues.append("stdout JSON has no 'status' field")
    elif obj["status"] not in {c.value for c in ErrorCode}:
        issues.append(f"stdout status is not a known ErrorCode: {obj['status']!r}")
    return {"ok": len(issues) == 0, "issues": issues, "parsed": obj}


def check_full(out_dir: Path, stdout: Optional[str] = None) -> dict[str, Any]:
    report = {"out_dir": check_out_dir(out_dir)}
    if stdout is not None:
        report["stdout"] = check_stdout_line(stdout)
    report["ok"] = report["out_dir"]["ok"] and (
        stdout is None or report["stdout"]["ok"]
    )
    return report
