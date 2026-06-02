from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SUMMARY_FIELDS = [
    "generation_model",
    "creation_profile",
    "domain",
    "harness_task_id",
    "harness_path",
    "benchmark",
    "benchmark_id",
    "generation_status",
    "creation_attempts",
    "repair_rounds",
    "gate_pass_before_repair",
    "gate_pass_after_repair",
    "repair_failure_reasons",
    "repair_tokens",
    "selected_attempt_path",
    "syntax_ok",
    "import_ok",
    "cli_probe_ok",
    "adapter_status",
    "pre_bmk_gate_mode",
    "gate_pass",
    "gate_failure_reason",
    "toy_task_score",
    "static_check_pass",
    "artifact_check_pass",
    "eval_status",
    "score",
    "end_to_end_score",
    "score_breakdown",
    "pass_rate",
    "win_rate",
    "reward",
    "harness_run_tokens",
    "harness_run_interactions",
    "generation_tokens",
    "missing_dependencies",
    "stdout_path",
    "stderr_path",
    "raw_result_path",
]


@dataclass
class HarnessArtifact:
    path: Path
    task_id: str
    domain: str
    generation_model: str


@dataclass
class ValidationResult:
    generation_status: str
    syntax_ok: bool = False
    import_ok: bool = False
    cli_probe_ok: bool = False
    adapter_status: str = "not_checked"
    generation_tokens: int | None = None
    creation_attempts: int | None = None
    repair_rounds: int | None = None
    gate_pass_before_repair: bool | None = None
    gate_pass_after_repair: bool | None = None
    repair_failure_reasons: list[str] = field(default_factory=list)
    repair_tokens: int | None = None
    selected_attempt_path: str = ""
    harness_run_tokens: int | None = None
    harness_run_interactions: int | None = None
    missing_dependencies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stdout_path: str = ""
    stderr_path: str = ""
    raw_result_path: str = ""
    creation_profile: str = ""
    pre_bmk_gate_mode: str = "off"
    pre_bmk_gate_pass: bool | None = None
    pre_bmk_gate_status: str = "not_run"
    pre_bmk_toy_task_score: float | None = None
    pre_bmk_static_pass: bool | None = None
    pre_bmk_artifact_pass: bool | None = None
    pre_bmk_failure_reason: str = ""
    pre_bmk_report_path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def runnable(self) -> bool:
        return (
            self.generation_status == "success"
            and self.syntax_ok
            and self.import_ok
            and self.cli_probe_ok
            and self.adapter_status == "ready"
        )


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    command: list[str]


@dataclass
class HarnessRunResult:
    status: str
    score: float | None = None
    score_breakdown: dict[str, Any] = field(default_factory=dict)
    pass_rate: float | None = None
    win_rate: float | None = None
    reward: float | None = None
    tokens: int | None = None
    harness_run_tokens: int | None = None
    interactions: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    raw_result_path: str = ""
    missing_dependencies: list[str] = field(default_factory=list)
    error: str = ""
