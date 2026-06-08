"""Benchmark out-dir layout constants + read/write helpers.

This module defines the STABLE on-disk contract every harness run produces, so a
BMK runner / judge can find things deterministically.

NO third-party imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..core.serialization import safe_json_dumps, write_json_file

# --- Standard out-dir filenames (the contract) ---------------------------- #
RESPONSE_MD = "response.md"
ARTIFACTS_JSON = "artifacts.json"
TRAJECTORY_JSONL = "trajectory.jsonl"
METADATA_JSON = "metadata.json"
ERROR_JSON = "error.json"
STDOUT_LOG = "stdout.log"
STDERR_LOG = "stderr.log"
PATCH_DIFF = "patch.diff"
SCREENSHOTS_DIR = "screenshots"
EVIDENCE_JSON = "evidence.json"

# The set of files a contract-complete out-dir should contain after a run.
REQUIRED_OUTPUT_FILES = (RESPONSE_MD, ARTIFACTS_JSON, TRAJECTORY_JSONL, METADATA_JSON)
OPTIONAL_OUTPUT_FILES = (ERROR_JSON, STDOUT_LOG, STDERR_LOG, PATCH_DIFF, EVIDENCE_JSON)


def out_path(out_dir: Path, name: str) -> Path:
    return Path(out_dir) / name


def screenshots_dir(out_dir: Path) -> Path:
    d = Path(out_dir) / SCREENSHOTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- writers -------------------------------------------------------------- #


def write_response(out_dir: Path, markdown: str) -> Path:
    p = out_path(out_dir, RESPONSE_MD)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown, encoding="utf-8")
    return p


def write_metadata(out_dir: Path, metadata: dict[str, Any]) -> Path:
    return write_json_file(out_path(out_dir, METADATA_JSON), metadata)


def write_error(out_dir: Path, error_obj: dict[str, Any]) -> Path:
    return write_json_file(out_path(out_dir, ERROR_JSON), error_obj)


def write_patch(out_dir: Path, diff_text: str) -> Path:
    p = out_path(out_dir, PATCH_DIFF)
    p.write_text(diff_text, encoding="utf-8")
    return p


def write_evidence(out_dir: Path, evidence: Any) -> Path:
    return write_json_file(out_path(out_dir, EVIDENCE_JSON), evidence)


def append_trajectory_line(out_dir: Path, event: dict[str, Any]) -> None:
    p = out_path(out_dir, TRAJECTORY_JSONL)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(safe_json_dumps(event, compact=True) + "\n")


# --- readers -------------------------------------------------------------- #


def read_response(out_dir: Path) -> Optional[str]:
    p = out_path(out_dir, RESPONSE_MD)
    return p.read_text(encoding="utf-8") if p.exists() else None


def read_metadata(out_dir: Path) -> Optional[dict[str, Any]]:
    return _read_json(out_path(out_dir, METADATA_JSON))


def read_error(out_dir: Path) -> Optional[dict[str, Any]]:
    return _read_json(out_path(out_dir, ERROR_JSON))


def read_artifacts(out_dir: Path) -> Optional[dict[str, Any]]:
    return _read_json(out_path(out_dir, ARTIFACTS_JSON))


def read_trajectory(out_dir: Path) -> list[dict[str, Any]]:
    p = out_path(out_dir, TRAJECTORY_JSONL)
    if not p.exists():
        return []
    import json

    events: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:  # pragma: no cover - tolerate partial lines
            continue
    return events


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover
        return None
