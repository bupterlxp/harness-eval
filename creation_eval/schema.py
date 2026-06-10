from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SUMMARY_FIELDS = [
    "generation_model",
    "eval_model",
    "eval_model_input",
    "eval_reasoning_effort",
    "creation_profile",
    "domain",
    "harness_task_id",
    "harness_path",
    "benchmark",
    "benchmark_id",
    "generation_status",
    "creation_attempts",
    "syntax_ok",
    "import_ok",
    "cli_probe_ok",
    "cli_status",
    "harness_invocation",
    "eval_status",
    "score",
    "end_to_end_score",
    "score_breakdown",
    "pass_rate",
    "win_rate",
    "reward",
    "harness_run_tokens",
    "harness_run_token_breakdown",
    "harness_run_interactions",
    "llm_used",
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
    cli_status: str = "not_checked"
    generation_tokens: int | None = None
    creation_attempts: int | None = None
    harness_run_tokens: int | None = None
    harness_run_interactions: int | None = None
    missing_dependencies: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stdout_path: str = ""
    stderr_path: str = ""
    raw_result_path: str = ""
    creation_profile: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def runnable(self) -> bool:
        return (
            self.syntax_ok
            and self.import_ok
            and self.cli_probe_ok
            and self.cli_status == "ready"
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
    token_breakdown: dict[str, Any] = field(default_factory=dict)
    interactions: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    raw_result_path: str = ""
    missing_dependencies: list[str] = field(default_factory=list)
    error: str = ""
