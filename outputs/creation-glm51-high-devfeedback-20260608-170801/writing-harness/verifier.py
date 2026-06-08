"""Verifier: validate final artifacts before declaring success.

Checks that:
- final text file exists
- final text is prose, not JSON/logs/metadata
- final text meets minimum length
- result.json references the final text
- trajectory records the writing process
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


# Minimum word counts for each length target.
_MIN_WORDS = {
    "brief": 20,
    "short": 50,
    "medium": 100,
    "long": 200,
    "flash": 30,
    "drabble": 80,
}

# Patterns that indicate non-prose content.
_NON_PROSE_INDICATORS = [
    re.compile(r'^\s*\{.*"status"', re.DOTALL),
    re.compile(r'^\s*\{.*"error_code"', re.DOTALL),
    re.compile(r'task completed', re.IGNORECASE),
    re.compile(r'see logs|see trajectory|execution summary', re.IGNORECASE),
    re.compile(r'^\s*```json', re.MULTILINE),
]


def verify_artifacts(
    output_dir: Path,
    *,
    final_text_name: str = "response.md",
    length_target: str = "medium",
) -> dict[str, Any]:
    """Verify the final artifacts. Returns a dict with 'ok' and 'issues'."""
    issues: list[str] = []
    checks: dict[str, bool] = {}

    # 1. Final text file exists.
    text_path = output_dir / final_text_name
    checks["final_text_exists"] = text_path.exists()
    if not text_path.exists():
        issues.append(f"Final text file '{final_text_name}' does not exist.")
        return {"ok": False, "issues": issues, "checks": checks}

    # 2. Read the final text.
    try:
        text = text_path.read_text(encoding="utf-8")
    except Exception as e:
        issues.append(f"Cannot read final text: {e}")
        return {"ok": False, "issues": issues, "checks": checks}

    # 3. Final text is prose.
    is_prose = _is_prose(text)
    checks["is_prose"] = is_prose
    if not is_prose:
        issues.append("Final text is not prose (appears to be JSON, logs, or metadata).")

    # 4. Final text meets minimum length.
    word_count = len(text.split())
    min_words = _MIN_WORDS.get(length_target, 100)
    meets_length = word_count >= min_words
    checks["meets_length"] = meets_length
    if not meets_length:
        issues.append(
            f"Final text has {word_count} words, minimum is {min_words} for '{length_target}' target."
        )

    # 5. result.json exists and references the final text.
    result_path = output_dir / "result.json"
    checks["result_json_exists"] = result_path.exists()
    if result_path.exists():
        try:
            result_data = json.loads(result_path.read_text(encoding="utf-8"))
            artifacts = result_data.get("artifacts", {})
            checks["result_references_text"] = final_text_name in str(artifacts)
            if final_text_name not in str(artifacts):
                issues.append(f"result.json does not reference '{final_text_name}'.")
        except Exception:
            issues.append("result.json is not valid JSON.")
    else:
        issues.append("result.json does not exist.")

    # 6. trajectory.jsonl exists and is non-empty.
    traj_path = output_dir / "trajectory.jsonl"
    checks["trajectory_exists"] = traj_path.exists()
    if traj_path.exists():
        try:
            lines = [l for l in traj_path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
            checks["trajectory_has_events"] = len(lines) >= 2
            if len(lines) < 2:
                issues.append("trajectory.jsonl has fewer than 2 events.")
        except Exception:
            issues.append("trajectory.jsonl cannot be read.")
    else:
        issues.append("trajectory.jsonl does not exist.")

    ok = len(issues) == 0
    return {"ok": ok, "issues": issues, "checks": checks, "word_count": word_count}


def _is_prose(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    # Check for non-prose indicators.
    for pat in _NON_PROSE_INDICATORS:
        if pat.search(stripped[:800]):
            return False

    # Check if it's raw JSON.
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            json.loads(stripped)
            return False
        except Exception:
            pass

    # Check if it's a list of JSON objects.
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            json.loads(stripped)
            return False
        except Exception:
            pass

    return True
