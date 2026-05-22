from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .schema import CommandResult, SUMMARY_FIELDS


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding already-set env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for row in rows:
            normalized = {field: row.get(field, "") for field in SUMMARY_FIELDS}
            for key, value in list(normalized.items()):
                if isinstance(value, (dict, list)):
                    normalized[key] = json.dumps(value, ensure_ascii=False)
                elif value is None:
                    normalized[key] = ""
            writer.writerow(normalized)


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> CommandResult:
    started = time.time()
    def _as_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            elapsed_sec=time.time() - started,
            command=command,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=_as_text(exc.stdout),
            stderr=_as_text(exc.stderr) + f"\nTimed out after {timeout}s",
            elapsed_sec=time.time() - started,
            command=command,
        )


def best_python_bin(explicit: str | None = None) -> str:
    candidates = [
        explicit,
        os.environ.get("HARNESS_EVAL_PYTHON"),
        sys.executable,
        "/opt/homebrew/bin/python3.12",
        shutil.which("python3.12"),
        shutil.which("python3.11"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = shutil.which(candidate)
        if candidate_path:
            resolved_candidate = (
                candidate_path
                if Path(candidate_path).is_absolute()
                else str(Path(candidate_path).absolute())
            )
        else:
            resolved_candidate = str(Path(candidate).expanduser().absolute())
        result = run_command(
            [resolved_candidate, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"],
            timeout=10,
        )
        if result.returncode == 0:
            return resolved_candidate
    return explicit or sys.executable


def which_missing(executables: list[str]) -> list[str]:
    return [name for name in executables if shutil.which(name) is None]


def relpath(path: str | Path, base: Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(base.resolve()))
    except Exception:
        return str(p)


def copytree_filtered(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
    )
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
