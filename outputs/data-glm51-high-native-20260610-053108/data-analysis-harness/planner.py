"""Planner: parse the task prompt, infer expected artifact type, and build
a step-by-step execution plan.

The planner examines the task prompt for keywords, checks for MLE-bench
artifacts (sample_submission.csv, train/test splits), and produces a
structured plan the harness loop can follow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class TaskType(Enum):
    MLE_SUBMISSION = "mle_submission"
    DATA_ANALYSIS_REPORT = "data_analysis_report"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class ExecutionPlan:
    task_type: TaskType = TaskType.UNKNOWN
    needs_model: bool = False
    needs_submission: bool = False
    needs_report: bool = True
    target_columns: list[str] = field(default_factory=list)
    id_column: str = ""
    prediction_type: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    data_files: dict[str, list[Path]] = field(default_factory=dict)
    sample_submission_path: Optional[Path] = None


_MLE_KEYWORDS = (
    "predict", "classification", "regression", "train", "test",
    "submission", "accuracy", "f1", "auc", "rmse", "mse", "mae",
    "model", "feature", "label", "target", "fit", "score",
)

_DACP_KEYWORDS = (
    "analyze", "analysis", "report", "insight", "summary",
    "credit", "risk", "allocation", "invoice", "churn",
    "tier", "pricing", "interest", "business",
)


def infer_task_type(prompt: str) -> TaskType:
    p = prompt.lower()
    mle_score = sum(1 for kw in _MLE_KEYWORDS if kw in p)
    dacp_score = sum(1 for kw in _DACP_KEYWORDS if kw in p)
    if mle_score >= 2 and dacp_score >= 2:
        return TaskType.MIXED
    if mle_score >= 2:
        return TaskType.MLE_SUBMISSION
    if dacp_score >= 2:
        return TaskType.DATA_ANALYSIS_REPORT
    return TaskType.UNKNOWN


def discover_data_files(workdir: Path) -> dict[str, list[Path]]:
    """Find data files and categorize them."""
    result: dict[str, list[Path]] = {
        "train": [], "test": [], "sample_submission": [],
        "data": [], "readme": [], "instructions": [], "other": [],
    }
    if not workdir.exists():
        return result
    data_exts = {".csv", ".tsv", ".json", ".parquet", ".xlsx", ".sqlite", ".db"}
    for f in workdir.rglob("*"):
        if not f.is_file():
            continue
        name_lower = f.name.lower()
        if name_lower.startswith(".") or name_lower.startswith("_"):
            continue
        if "readme" in name_lower or "instructions" in name_lower:
            result["readme"].append(f)
            continue
        if "sample_submission" in name_lower or "samplesubmission" in name_lower:
            result["sample_submission"].append(f)
            continue
        if "train" in name_lower and f.suffix.lower() in data_exts:
            result["train"].append(f)
            continue
        if "test" in name_lower and f.suffix.lower() in data_exts:
            result["test"].append(f)
            continue
        if f.suffix.lower() in data_exts:
            result["data"].append(f)
            continue
        if f.suffix.lower() in {".md", ".txt", ".pdf"}:
            result["instructions"].append(f)
    return result


def build_plan(
    prompt: str,
    workdir: Path,
    *,
    max_steps: int = 50,
) -> ExecutionPlan:
    """Build an execution plan from the task prompt and workdir contents."""
    plan = ExecutionPlan()
    plan.task_type = infer_task_type(prompt)
    plan.data_files = discover_data_files(workdir)

    sample_subs = plan.data_files.get("sample_submission", [])
    plan.sample_submission_path = sample_subs[0] if sample_subs else None

    if plan.sample_submission_path is not None or plan.task_type == TaskType.MLE_SUBMISSION:
        plan.needs_submission = True
        plan.needs_model = True
    if plan.task_type in (TaskType.DATA_ANALYSIS_REPORT, TaskType.MIXED):
        plan.needs_report = True
    if plan.task_type == TaskType.UNKNOWN:
        plan.needs_report = True

    steps: list[dict[str, Any]] = []
    steps.append({"phase": "discover", "desc": "Discover and summarize data files"})
    steps.append({"phase": "read_context", "desc": "Read README/instructions for task details"})
    steps.append({"phase": "summarize_data", "desc": "Summarize data schemas and statistics"})

    if plan.needs_submission:
        steps.append({"phase": "parse_sample", "desc": "Parse sample_submission.csv for schema"})
        steps.append({"phase": "build_model", "desc": "Build and evaluate predictive model"})
        steps.append({"phase": "generate_submission", "desc": "Generate submission.csv"})

    if plan.needs_report:
        steps.append({"phase": "analyze", "desc": "Run data analysis computations"})
        steps.append({"phase": "write_report", "desc": "Write REPORT.md with findings"})

    steps.append({"phase": "validate", "desc": "Validate artifacts against domain contract"})
    steps.append({"phase": "finalize", "desc": "Write result.json and finalize outputs"})

    plan.steps = steps[:max_steps]
    return plan
