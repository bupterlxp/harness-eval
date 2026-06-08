"""Judge I/O: read a run's answer + evidence + artifacts for grading; write a
judge verdict. No network. Stable schema for an automated grader.

NO third-party imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..core.serialization import write_json_file
from . import bmk_io

JUDGE_INPUT_NAME = "judge_input.json"
JUDGE_OUTPUT_NAME = "judge_output.json"


def build_judge_input(out_dir: Path, *, task: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Assemble everything a judge needs from a completed out-dir."""
    out_dir = Path(out_dir)
    artifacts = bmk_io.read_artifacts(out_dir) or {}
    metadata = bmk_io.read_metadata(out_dir) or {}
    evidence = bmk_io._read_json(out_dir / bmk_io.EVIDENCE_JSON)  # may be None
    return {
        "task": task,
        "status": metadata.get("status"),
        "answer": bmk_io.read_response(out_dir),
        "answer_path": str(out_dir / bmk_io.RESPONSE_MD),
        "artifacts": artifacts.get("artifacts", {}),
        "evidence": evidence,
        "metadata": metadata,
        "error": bmk_io.read_error(out_dir),
    }


def write_judge_input(out_dir: Path, judge_input: dict[str, Any]) -> Path:
    return write_json_file(Path(out_dir) / JUDGE_INPUT_NAME, judge_input)


def write_judge_output(
    out_dir: Path,
    *,
    score: float,
    passed: bool,
    rationale: str = "",
    rubric: Optional[dict[str, Any]] = None,
    details: Optional[dict[str, Any]] = None,
) -> Path:
    verdict = {
        "score": float(score),
        "passed": bool(passed),
        "rationale": rationale,
        "rubric": rubric or {},
        "details": details or {},
    }
    return write_json_file(Path(out_dir) / JUDGE_OUTPUT_NAME, verdict)


def read_judge_output(out_dir: Path) -> Optional[dict[str, Any]]:
    return bmk_io._read_json(Path(out_dir) / JUDGE_OUTPUT_NAME)
