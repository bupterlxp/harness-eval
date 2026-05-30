from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..adapter import run_generated_harness
from ..schema import HarnessArtifact, ValidationResult
from ..scaffold_runtime import find_scaffold_program
from ..utils import write_json
from .toy_tasks import setup_toy_task


DOMAIN_TOOL_KEYWORDS = {
    "code": ["read_file", "write_file", "run_command"],
    "data_analysis": ["execute_python", "read_file", "write_report"],
    "writing": ["plan", "critique", "revise"],
    "research": ["search", "evidence", "citation"],
    "browser": ["navigate", "click", "extract"],
}


def _collect_python_text(harness_dir: Path) -> tuple[list[Path], str, int]:
    py_files = sorted(harness_dir.rglob("*.py")) if harness_dir.exists() else []
    chunks = []
    line_count = 0
    for path in py_files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            chunks.append(content)
            line_count += content.count("\n") + 1
        except OSError:
            continue
    return py_files, "\n".join(chunks), line_count


def static_checks(artifact: HarnessArtifact) -> dict[str, Any]:
    harness_dir = artifact.path / "harness"
    scaffold_program = find_scaffold_program(artifact.path)
    if scaffold_program is not None and not harness_dir.exists():
        return _scaffold_static_checks(artifact, scaffold_program)
    py_files, text, line_count = _collect_python_text(harness_dir)
    lowered = text.lower()
    expected = DOMAIN_TOOL_KEYWORDS.get(artifact.domain, [])
    found_tools = [name for name in expected if name.lower() in lowered]
    has_base_url = any(name in text for name in ("OPENAI_BASE_URL", "BASE_URL", "ANTHROPIC_BASE_URL"))
    has_api_key = any(name in text for name in ("OPENAI_API_KEY", "API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    has_model = any(name in text for name in ("MODEL_NAME", "MODEL_ID", "OPENAI_MODEL", "ANTHROPIC_MODEL"))
    checks = {
        "has_python_files": bool(py_files),
        "has_entry_point": (harness_dir / "__main__.py").exists() or any(path.name == "harness.py" for path in py_files),
        "has_result_output": "result.json" in lowered,
        "has_trajectory": "trajectory" in lowered,
        "has_llm_config": has_base_url and has_api_key and has_model,
        "has_domain_tools": len(found_tools) >= max(1, len(expected) // 2) if expected else True,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "scaffold_style": False,
        "found_domain_tools": found_tools,
        "total_python_files": len(py_files),
        "total_python_lines": line_count,
    }


def _scaffold_static_checks(artifact: HarnessArtifact, program_path: Path) -> dict[str, Any]:
    try:
        text = program_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    lowered = text.lower()
    stub_markers = ("todo", "fixme", "notimplementederror", "pass  #")
    expected = DOMAIN_TOOL_KEYWORDS.get(artifact.domain, [])
    found_tools = [name for name in expected if name.lower() in lowered]
    checks = {
        "has_python_files": program_path.is_file(),
        "has_entry_point": True,
        "has_result_output": True,
        "has_trajectory": True,
        "has_llm_config": True,
        "has_domain_tools": True,
        "no_todo_stub": not any(marker in lowered for marker in stub_markers),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "scaffold_style": True,
        "scaffold_program": str(program_path),
        "found_domain_tools": found_tools,
        "total_python_files": 1,
        "total_python_lines": text.count("\n") + 1 if text else 0,
    }


def _json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_nonempty_file(root: Path, names: set[str]) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and path.name in names and path.stat().st_size > 0:
            return True
    return False


def _check_code(work_dir: Path, output_dir: Path) -> dict[str, Any]:
    app_path = work_dir / "app.py"
    test_result = subprocess.run(
        ["python3", "test_app.py"],
        cwd=work_dir,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    content = app_path.read_text(encoding="utf-8", errors="replace") if app_path.exists() else ""
    passed = test_result.returncode == 0
    return {
        "passed": passed,
        "app_modified": "todo.id == todo_id" in content and "not todo.completed" in content,
        "test_returncode": test_result.returncode,
        "test_stdout_tail": test_result.stdout[-1000:],
        "test_stderr_tail": test_result.stderr[-1000:],
    }


def _check_data(work_dir: Path, output_dir: Path) -> dict[str, Any]:
    report_exists = _has_nonempty_file(output_dir, {"REPORT.md", "report.md"}) or _has_nonempty_file(work_dir, {"REPORT.md", "report.md"})
    chart_exists = any(path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"} for root in (output_dir, work_dir) for path in root.rglob("*"))
    return {"passed": report_exists and chart_exists, "report_exists": report_exists, "chart_exists": chart_exists}


def _check_writing(work_dir: Path, output_dir: Path) -> dict[str, Any]:
    candidates = list(work_dir.rglob("story.md")) + list(output_dir.rglob("story.md"))
    word_count = 0
    if candidates:
        word_count = len(candidates[0].read_text(encoding="utf-8", errors="replace").split())
    return {"passed": bool(candidates) and word_count >= 300, "story_exists": bool(candidates), "word_count": word_count}


def _check_research(work_dir: Path, output_dir: Path) -> dict[str, Any]:
    candidates = list(work_dir.rglob("report.md")) + list(output_dir.rglob("report.md")) + list(output_dir.rglob("REPORT.md"))
    text = candidates[0].read_text(encoding="utf-8", errors="replace").lower() if candidates else ""
    passed = bool(candidates) and all(term in text for term in ("aws", "azure")) and ("gcp" in text or "google cloud" in text)
    return {"passed": passed, "report_exists": bool(candidates), "has_aws": "aws" in text, "has_azure": "azure" in text, "has_gcp": "gcp" in text or "google cloud" in text}


def _check_browser(work_dir: Path, output_dir: Path) -> dict[str, Any]:
    candidates = list(work_dir.rglob("products.json")) + list(output_dir.rglob("products.json"))
    count = 0
    if candidates:
        try:
            payload = json.loads(candidates[0].read_text(encoding="utf-8"))
            count = len(payload) if isinstance(payload, list) else 0
        except Exception:
            count = 0
    return {"passed": count >= 2, "products_json_exists": bool(candidates), "product_count": count}


DOMAIN_CHECKS = {
    "code": _check_code,
    "data_analysis": _check_data,
    "writing": _check_writing,
    "research": _check_research,
    "browser": _check_browser,
}


def run_pre_bmk_validation(
    artifact: HarnessArtifact,
    validation: ValidationResult,
    output_dir: Path,
    *,
    python_bin: str,
    timeout: int = 300,
    run_toy: bool = True,
) -> ValidationResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    static = static_checks(artifact)
    report: dict[str, Any] = {
        "artifact": str(artifact.path),
        "task_id": artifact.task_id,
        "domain": artifact.domain,
        "static": static,
        "toy": {"status": "not_run"},
    }
    validation.pre_bmk_static_pass = bool(static.get("passed"))

    toy_pass = False
    toy_score: float | None = None
    failure_reasons: list[str] = []
    if not static.get("passed"):
        failed = [name for name, ok in static.get("checks", {}).items() if not ok]
        failure_reasons.append("static_checks_failed: " + ",".join(failed))

    if run_toy and validation.runnable:
        with tempfile.TemporaryDirectory(prefix="pre_bmk_toy_") as tmp:
            work_dir = Path(tmp) / "work"
            prompt = setup_toy_task(artifact.domain, work_dir)
            if prompt is None:
                report["toy"] = {"status": "skipped", "reason": f"no toy task for domain {artifact.domain}"}
            else:
                toy_output = output_dir / "toy_run"
                result = run_generated_harness(
                    artifact.path,
                    artifact.domain,
                    prompt,
                    toy_output,
                    task_work_dir=work_dir,
                    python_bin=python_bin,
                    timeout=timeout,
                )
                checker = DOMAIN_CHECKS.get(artifact.domain)
                domain_check = checker(work_dir, toy_output) if checker else {"passed": result.status == "success"}
                toy_pass = result.status == "success" and bool(domain_check.get("passed"))
                toy_score = 1.0 if toy_pass else 0.0
                report["toy"] = {
                    "status": result.status,
                    "score": toy_score,
                    "domain_check": domain_check,
                    "stdout_path": result.stdout_path,
                    "stderr_path": result.stderr_path,
                    "raw_result_path": result.raw_result_path,
                    "error": result.error,
                }
                if not toy_pass:
                    failure_reasons.append("toy_task_failed")
    elif run_toy and not validation.runnable:
        report["toy"] = {"status": "skipped", "reason": "base validation is not runnable"}
        failure_reasons.append("base_validation_not_runnable")
    else:
        report["toy"] = {"status": "skipped", "reason": "dry-run/static-only validation"}

    validation.pre_bmk_toy_task_score = toy_score
    validation.pre_bmk_artifact_pass = toy_pass if run_toy and validation.runnable else None
    validation.pre_bmk_gate_pass = bool(static.get("passed")) and (toy_pass if run_toy and validation.runnable else True)
    validation.pre_bmk_gate_status = "passed" if validation.pre_bmk_gate_pass else "failed"
    validation.pre_bmk_failure_reason = "; ".join(failure_reasons)
    report["gate"] = {
        "passed": validation.pre_bmk_gate_pass,
        "failure_reason": validation.pre_bmk_failure_reason,
    }
    report_path = output_dir / "pre_bmk_validation.json"
    write_json(report_path, report)
    validation.pre_bmk_report_path = str(report_path)
    return validation
