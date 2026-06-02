from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArtifactContractResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    repair_hints: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_domain_artifacts(domain: str, work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    work_dir = Path(work_dir)
    output_dir = Path(output_dir)
    if domain == "code":
        return validate_code_artifacts(work_dir, output_dir)
    if domain == "data_analysis":
        return validate_data_artifacts(work_dir, output_dir)
    if domain == "writing":
        return validate_writing_artifacts(work_dir, output_dir)
    if domain == "research":
        return validate_research_artifacts(work_dir, output_dir)
    if domain == "browser":
        return validate_browser_artifacts(work_dir, output_dir)
    return ArtifactContractResult(True, evidence={"reason": f"no contract for domain {domain}"})


def summarize_contract_failures(result: ArtifactContractResult) -> str:
    if result.passed:
        return "public artifact contract passed"
    lines = ["public artifact contract failed:"]
    for failure in result.failures:
        lines.append(f"- {failure}")
    if result.repair_hints:
        lines.append("repair hints:")
        for hint in result.repair_hints:
            lines.append(f"- {hint}")
    return "\n".join(lines)


def _paths(root_a: Path, root_b: Path) -> list[Path]:
    roots = [root_a, root_b]
    out: list[Path] = []
    for root in roots:
        if root.exists():
            out.extend(path for path in root.rglob("*") if path.is_file())
    return out


def _find_named(root_a: Path, root_b: Path, names: set[str]) -> list[Path]:
    lowered = {name.lower() for name in names}
    return [path for path in _paths(root_a, root_b) if path.name.lower() in lowered]


def _read_text(path: Path, limit: int = 200_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _nonempty(paths: list[Path]) -> bool:
    return any(path.exists() and path.stat().st_size > 0 for path in paths)


def _result_objects(work_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for path in _find_named(work_dir, output_dir, {"result.json", "metadata.json", "artifacts.json"}):
        payload = _load_json(path)
        if isinstance(payload, dict):
            objects.append(payload)
    return objects


def validate_code_artifacts(work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    failures: list[str] = []
    hints: list[str] = []
    checked: list[str] = []
    evidence: dict[str, Any] = {}

    diff_like = [
        path
        for path in _paths(work_dir, output_dir)
        if path.name.lower() in {"patch.diff", "diff.patch", "changes.diff", "git.diff"}
        or path.suffix.lower() in {".patch", ".diff"}
    ]
    result_objs = _result_objects(work_dir, output_dir)
    result_text = json.dumps(result_objs, ensure_ascii=False).lower()
    changed_files = bool(re.search(r"changed_files|patch|diff|commands_run|verifier", result_text))
    verifier_evidence = bool(re.search(r"pytest|unittest|test_|verifier|commands_run|test_status", result_text))
    command_logs = _find_named(work_dir, output_dir, {"commands.log", "test.log", "verifier.log"})
    checked.extend(str(p) for p in diff_like + command_logs)
    evidence.update(
        {
            "diff_like_count": len(diff_like),
            "result_mentions_changes": changed_files,
            "result_mentions_verifier": verifier_evidence,
            "command_log_count": len(command_logs),
        }
    )
    if not diff_like and not changed_files:
        failures.append("code harness produced no patch/diff/changed_files evidence")
        hints.append("Record changed_files and either write a patch/diff artifact or include final git diff in result.json.")
    if not command_logs and not verifier_evidence:
        failures.append("code harness produced no verifier/test command evidence")
        hints.append("Run a real verifier command when possible and record commands_run plus stdout/stderr or test_status.")
    return ArtifactContractResult(not failures, failures, hints, checked, evidence)


def validate_data_artifacts(work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    failures: list[str] = []
    hints: list[str] = []
    checked: list[str] = []
    evidence: dict[str, Any] = {}

    reports = _find_named(work_dir, output_dir, {"report.md", "REPORT.md", "analysis.md", "analysis_summary.json"})
    checked.extend(str(p) for p in reports)
    report_text = "\n".join(_read_text(path) for path in reports)
    numeric_mentions = len(re.findall(r"[-+]?\d+(?:\.\d+)?%?", report_text))
    charts = [p for p in _paths(work_dir, output_dir) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".html"}]
    evidence.update({"report_count": len(reports), "numeric_mentions": numeric_mentions, "chart_count": len(charts)})
    if not reports:
        failures.append("data harness produced no REPORT.md/report.md/analysis_summary.json")
        hints.append("Write a concrete analysis report or analysis_summary.json with computed numbers.")
    if reports and numeric_mentions < 2:
        failures.append("data report appears template-like and contains too few concrete numbers")
        hints.append("Use Python/SQL/pandas or equivalent computation and include actual computed values.")

    sample_paths = _find_named(work_dir, output_dir, {"sample_submission.csv"})
    if sample_paths:
        sample_path = sample_paths[0]
        submission_paths = _find_named(work_dir, output_dir, {"submission.csv"})
        checked.append(str(sample_path))
        checked.extend(str(p) for p in submission_paths)
        evidence["sample_submission"] = str(sample_path)
        evidence["submission_candidates"] = [str(p) for p in submission_paths]
        if not submission_paths:
            failures.append("MLE-style public sample_submission.csv exists but no submission.csv was produced")
            hints.append("Create submission.csv with exactly the same columns and row ids as sample_submission.csv.")
        else:
            failures.extend(_validate_submission_csv(sample_path, submission_paths[0], hints, evidence))

    decisions = _find_named(
        work_dir,
        output_dir,
        {"risk_scores.csv", "decisions.csv", "decision.json", "analysis_summary.json", "results.json"},
    )
    checked.extend(str(p) for p in decisions)
    if not decisions and "risk" in report_text.lower():
        evidence["structured_decision_missing_but_report_mentions_risk"] = True
    return ArtifactContractResult(not failures, failures, hints, checked, evidence)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def _validate_submission_csv(sample_path: Path, submission_path: Path, hints: list[str], evidence: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    try:
        sample_cols, sample_rows = _read_csv(sample_path)
        sub_cols, sub_rows = _read_csv(submission_path)
    except Exception as exc:
        hints.append("Ensure submission.csv is valid CSV readable by the benchmark grader.")
        return [f"submission.csv could not be parsed: {type(exc).__name__}: {exc}"]

    evidence["submission_rows"] = len(sub_rows)
    evidence["sample_rows"] = len(sample_rows)
    evidence["submission_columns"] = sub_cols
    evidence["sample_columns"] = sample_cols
    if sub_cols != sample_cols:
        failures.append(f"submission.csv columns {sub_cols} do not exactly match sample_submission.csv columns {sample_cols}")
        hints.append("Copy sample_submission.csv column names exactly, in the same order.")
    if len(sub_rows) != len(sample_rows):
        failures.append(f"submission.csv row count {len(sub_rows)} does not match sample_submission.csv row count {len(sample_rows)}")
        hints.append("Preserve every row from sample_submission.csv and only replace prediction values.")
    if sample_cols and sample_rows and sub_rows:
        id_col = sample_cols[0]
        sample_ids = [row.get(id_col, "") for row in sample_rows]
        sub_ids = [row.get(id_col, "") for row in sub_rows]
        if sample_ids != sub_ids:
            failures.append(f"submission.csv id column {id_col!r} does not match sample_submission.csv order/content")
            hints.append("Keep the identifier column unchanged and in the original order.")
        for col in sample_cols[1:]:
            failures.extend(_validate_prediction_column(col, sample_rows, sub_rows, hints, evidence))
    return failures


def _validate_prediction_column(
    col: str,
    sample_rows: list[dict[str, str]],
    sub_rows: list[dict[str, str]],
    hints: list[str],
    evidence: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    sample_values = [str(row.get(col, "")).strip() for row in sample_rows]
    sub_values = [str(row.get(col, "")).strip() for row in sub_rows]
    lowered_sample = {v.lower() for v in sample_values if v != ""}
    lowered_sub = [v.lower() for v in sub_values]
    bool_words = {"true", "false"}
    if lowered_sample and lowered_sample.issubset(bool_words):
        bad = [v for v in lowered_sub if v not in bool_words]
        evidence[f"{col}_expected_domain"] = "boolean_words"
        if bad:
            failures.append(f"submission.csv column {col!r} must use boolean True/False labels, found invalid values like {bad[:5]}")
            hints.append(f"For {col}, output literal True/False labels, not probabilities or free text.")
    elif lowered_sample and len(lowered_sample) <= 20 and not all(_is_number(v) for v in lowered_sample):
        bad = [v for v in sub_values if v not in set(sample_values)]
        evidence[f"{col}_expected_domain"] = sorted(sample_values)
        if bad:
            failures.append(f"submission.csv column {col!r} has values outside sample_submission domain; examples: {bad[:5]}")
            hints.append(f"For {col}, use labels from sample_submission.csv's public value domain.")
    return failures


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def validate_writing_artifacts(work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    candidates = [
        path
        for path in _paths(work_dir, output_dir)
        if path.name.lower() in {"story.md", "response.md", "final.md", "final_answer.md", "writing.md"}
    ]
    checked = [str(p) for p in candidates]
    text = "\n".join(_read_text(path) for path in candidates)
    words = re.findall(r"\b[\w'-]+\b", text)
    log_markers = len(re.findall(r"adapter_|metadata|trajectory|stdout|stderr|status|tool_call", text.lower()))
    has_process = any(term in text.lower() for term in ("outline", "draft", "critique", "revision", "revised"))
    failures: list[str] = []
    hints: list[str] = []
    if not candidates:
        failures.append("writing harness produced no final writing artifact")
        hints.append("Write the final user-facing text to story.md, final.md, response.md, or final_answer.md.")
    if candidates and len(words) < 150:
        failures.append(f"writing artifact is too short for a downstream writing task ({len(words)} words)")
        hints.append("Produce the requested long-form content, not a short status message.")
    if candidates and log_markers > max(5, len(words) // 20):
        failures.append("writing artifact appears to be logs/metadata rather than user-facing prose")
        hints.append("Separate logs from final writing output; final artifact should contain only the answer/prose.")
    return ArtifactContractResult(
        not failures,
        failures,
        hints,
        checked,
        {"candidate_count": len(candidates), "word_count": len(words), "has_process_terms": has_process},
    )


def validate_research_artifacts(work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    reports = _find_named(work_dir, output_dir, {"report.md", "REPORT.md", "response.md", "answer.md", "evidence.json", "citations.json"})
    checked = [str(p) for p in reports]
    text = "\n".join(_read_text(path) for path in reports)
    citations = len(re.findall(r"https?://|doi:|\[[0-9]+\]|\bsource\b", text.lower()))
    search_trace = "search" in text.lower() or _nonempty(_find_named(work_dir, output_dir, {"evidence.json", "citations.json"}))
    failures: list[str] = []
    hints: list[str] = []
    if not reports:
        failures.append("research harness produced no report/answer/evidence artifact")
        hints.append("Write an answer report and an evidence/citation artifact.")
    if reports and citations < 1:
        failures.append("research output contains no citation/source evidence")
        hints.append("Record source URLs, citation ids, or evidence snippets used for synthesis.")
    if reports and not search_trace:
        failures.append("research output has no search/evidence collection trace")
        hints.append("Log search/fetch/evidence_add actions or write evidence.json.")
    return ArtifactContractResult(not failures, failures, hints, checked, {"citation_markers": citations, "search_trace": search_trace})


def validate_browser_artifacts(work_dir: Path, output_dir: Path) -> ArtifactContractResult:
    products = _find_named(work_dir, output_dir, {"products.json", "result.json", "browser_trace.json", "actions.json", "trajectory.jsonl"})
    checked = [str(p) for p in products]
    text = "\n".join(_read_text(path) for path in products)
    action_markers = len(re.findall(r"navigate|click|type|fill|extract|screenshot|state", text.lower()))
    final_result = _nonempty(_find_named(work_dir, output_dir, {"products.json", "browser_result.json", "final_state.json"}))
    failures: list[str] = []
    hints: list[str] = []
    if not products:
        failures.append("browser harness produced no browser result/action artifact")
        hints.append("Write action trace plus final extracted result, such as products.json or browser_result.json.")
    if products and action_markers < 1:
        failures.append("browser artifact has no observable browser action/state trace")
        hints.append("Record navigate/click/type/extract actions and final page state.")
    if products and not final_result:
        failures.append("browser harness did not write a domain final result artifact")
        hints.append("Write the final extracted data to a machine-readable file.")
    return ArtifactContractResult(not failures, failures, hints, checked, {"action_markers": action_markers, "final_result": final_result})
