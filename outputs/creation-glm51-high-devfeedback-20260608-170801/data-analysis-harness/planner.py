"""Planner: task analysis and plan generation for data analysis tasks.

Parses the task prompt to infer artifact type, domain, and analysis strategy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AnalysisPlan:
    """Structured plan for a data analysis task."""
    artifact_type: str  # "submission", "report", "both", "data_analysis"
    domain: str  # "mle_bench", "dacomp", "general"
    target_column: str | None = None
    task_type: str | None = None  # "classification", "regression", "clustering", "analysis"
    has_sample_submission: bool = False
    sample_columns: list[str] = field(default_factory=list)
    sample_id_column: str | None = None
    sample_target_columns: list[str] = field(default_factory=list)
    sample_row_count: int = 0
    train_files: list[Path] = field(default_factory=list)
    test_files: list[Path] = field(default_factory=list)
    data_files: list[Path] = field(default_factory=list)
    info_text: str = ""
    needs_modeling: bool = False
    needs_report: bool = True
    steps: list[str] = field(default_factory=list)


def parse_task(
    prompt: str,
    workdir: Path,
    discovered: dict[str, Any],
) -> AnalysisPlan:
    """Parse task prompt and discovered files into an AnalysisPlan."""
    workdir = Path(workdir)
    plan = AnalysisPlan(artifact_type="report", domain="general")

    # Determine domain from files and prompt
    sample_sub = discovered.get("sample_submission")
    if sample_sub is not None:
        plan.has_sample_submission = True
        plan.artifact_type = "submission"
        plan.domain = "mle_bench"
        plan.needs_modeling = True
        _parse_sample_submission(sample_sub, plan)

    # Classify train/test/data files
    for fp in discovered.get("data_files", []):
        name_lower = fp.name.lower()
        if name_lower.startswith("train"):
            plan.train_files.append(fp)
        elif name_lower.startswith("test"):
            plan.test_files.append(fp)
        else:
            plan.data_files.append(fp)

    # Read info files
    info_parts: list[str] = []
    for fp in discovered.get("info_files", []):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")[:5000]
            info_parts.append(f"--- {fp.name} ---\n{text}")
        except Exception:
            pass
    plan.info_text = "\n\n".join(info_parts)

    # Infer task type from prompt
    prompt_lower = prompt.lower()
    classification_keywords = [
        "classify", "classification", "label", "category", "categories",
        "predict whether", "binary", "multiclass", "true or false",
        "sentiment", "spam", "fraud", "churn",
    ]
    regression_keywords = [
        "regression", "predict the value", "predict the price",
        "forecast", "predict the amount", "predict the score",
        "continuous", "rmse", "mae", "mse",
    ]

    if any(kw in prompt_lower for kw in classification_keywords):
        plan.task_type = "classification"
    elif any(kw in prompt_lower for kw in regression_keywords):
        plan.task_type = "regression"

    # Check for DAComp-style open-ended analysis
    dacomp_keywords = [
        "credit allocation", "risk", "invoice", "pricing",
        "business", "churn rate", "interest rate", "allocation plan",
        "risk tier", "credit score", "portfolio",
    ]
    if any(kw in prompt_lower for kw in dacomp_keywords):
        plan.domain = "dacomp"
        plan.artifact_type = "both"
        plan.needs_report = True

    # If we have train + test but no sample submission, still try modeling
    if plan.train_files and plan.test_files and not plan.has_sample_submission:
        plan.needs_modeling = True
        plan.artifact_type = "both"

    # Build default steps
    plan.steps = _build_default_steps(plan, prompt)

    return plan


def _parse_sample_submission(filepath: Path, plan: AnalysisPlan) -> None:
    """Parse sample_submission.csv to understand expected output schema."""
    import csv as csv_mod

    try:
        with filepath.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv_mod.DictReader(f)
            plan.sample_columns = list(reader.fieldnames or [])
            rows = []
            for i, row in enumerate(reader):
                if i >= 5:
                    break
                rows.append(row)
            plan.sample_row_count = sum(1 for _ in open(filepath, encoding="utf-8", errors="replace")) - 1
    except Exception:
        return

    if not plan.sample_columns:
        return

    plan.sample_id_column = plan.sample_columns[0]
    plan.sample_target_columns = plan.sample_columns[1:]

    # Check if target is boolean
    if plan.sample_target_columns:
        first_col = plan.sample_target_columns[0]
        try:
            with filepath.open(newline="", encoding="utf-8", errors="replace") as f:
                reader = csv_mod.DictReader(f)
                values = set()
                for i, row in enumerate(reader):
                    if i >= 100:
                        break
                    val = str(row.get(first_col, "")).strip()
                    if val:
                        values.add(val.lower())
            if values <= {"true", "false", "0", "1", "yes", "no"}:
                plan.task_type = "classification"
        except Exception:
            pass


def _build_default_steps(plan: AnalysisPlan, prompt: str) -> list[str]:
    """Build default analysis steps based on the plan."""
    steps = [
        "Load and inspect all data files",
        "Check data shapes, dtypes, missing values, and basic statistics",
    ]

    if plan.train_files:
        steps.append("Explore target variable distribution in training data")
        steps.append("Examine feature correlations with the target")

    steps.append("Clean data: handle missing values, encode categoricals")

    if plan.needs_modeling:
        if plan.task_type == "classification":
            steps.extend([
                "Build a baseline classification model (e.g., LogisticRegression or RandomForest)",
                "Evaluate with cross-validation",
                "Generate predictions on test set",
                "Create submission.csv matching sample schema",
            ])
        elif plan.task_type == "regression":
            steps.extend([
                "Build a baseline regression model (e.g., LinearRegression or RandomForest)",
                "Evaluate with cross-validation",
                "Generate predictions on test set",
                "Create submission.csv matching sample schema",
            ])
        else:
            steps.extend([
                "Determine if this is classification or regression from the data",
                "Build appropriate baseline model",
                "Generate predictions on test set",
                "Create submission.csv matching sample schema",
            ])

    if plan.needs_report:
        steps.append("Write REPORT.md with findings, methodology, and limitations")

    return steps


def plan_to_context_string(plan: AnalysisPlan) -> str:
    """Convert plan to a compact string for LLM context."""
    parts = [
        f"Artifact type: {plan.artifact_type}",
        f"Domain: {plan.domain}",
    ]
    if plan.task_type:
        parts.append(f"Task type: {plan.task_type}")
    if plan.has_sample_submission:
        parts.append(f"Sample submission: columns={plan.sample_columns}, rows={plan.sample_row_count}")
        parts.append(f"ID column: {plan.sample_id_column}")
        parts.append(f"Target columns: {plan.sample_target_columns}")
    if plan.train_files:
        parts.append(f"Train files: {[f.name for f in plan.train_files]}")
    if plan.test_files:
        parts.append(f"Test files: {[f.name for f in plan.test_files]}")
    parts.append("Planned steps:")
    for i, step in enumerate(plan.steps, 1):
        parts.append(f"  {i}. {step}")
    return "\n".join(parts)
