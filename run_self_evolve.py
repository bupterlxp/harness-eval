#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from creation_eval.utils import load_env_file, read_json, write_json
from creation_eval.validator import discover_harness_artifacts
from creation_eval.token_usage import merge_token_usages, normalize_usage
from run import (
    build_docker_image,
    load_config,
    normalize_creation_profile,
    resolve_config_models,
    run_generation,
    validate_generation_config,
)


HIDDEN_TASK_KEYS = {
    "base_sha",
    "compare_url",
    "commit_count",
    "files",
    "fusion_reason",
    "merged_at_end",
    "merged_at_start",
    "pr_count",
    "pr_numbers",
    "pr_titles",
    "pr_urls",
    "source_type",
    "target_sha",
    "human_sha",
    "human_tree_url",
    "human_diff_url",
    "diff_url",
    "commit_urls",
    "patch",
    "diff",
}

SAFE_TASK_METADATA_KEYS = {
    "domain_key",
    "domain",
    "harness",
    "update_index_oldest_to_newest",
    "capabilities",
    "capability_primary",
    "validation_hint",
}

SKIP_COPY_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

JUDGE_TOKEN_KEYS = {
    "judge_tokens",
    "judge_total_tokens",
    "llm_judge_tokens",
    "evaluator_tokens",
    "grader_tokens",
}

NESTED_USAGE_KEYS = ("metrics", "usage", "token_usage", "llm_usage")
DIRECT_TOKEN_KEYS = {
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "agent_total_tokens",
    "agent_input_tokens",
    "agent_output_tokens",
    "agent_reasoning_tokens",
    "harness_run_tokens",
    "tokens",
}


def now_run_id() -> str:
    return datetime.now().strftime("self-evolve-%Y%m%d-%H%M%S")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return cleaned[:80] or "round"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def as_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def token_total(usage: dict[str, Any] | None) -> int | None:
    if not usage:
        return None
    value = as_number(usage.get("total_tokens"))
    if value is None:
        prompt = as_number(usage.get("prompt_tokens") or usage.get("input_tokens"))
        completion = as_number(usage.get("completion_tokens") or usage.get("output_tokens"))
        if prompt is not None or completion is not None:
            value = (prompt or 0) + (completion or 0)
    return int(value) if value is not None else None


def sum_numeric(values: list[Any]) -> int | None:
    total = 0
    found = False
    for value in values:
        number = as_number(value)
        if number is None:
            continue
        total += int(number)
        found = True
    return total if found else None


def sum_nested_token_keys(value: Any, keys: set[str]) -> int | None:
    value = maybe_json(value)
    total = 0
    found = False
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in keys:
                number = as_number(item)
                if number is not None:
                    total += int(number)
                    found = True
                    continue
            nested = sum_nested_token_keys(item, keys)
            if nested is not None:
                total += nested
                found = True
    elif isinstance(value, list):
        for item in value:
            nested = sum_nested_token_keys(item, keys)
            if nested is not None:
                total += nested
                found = True
    return total if found else None


def row_token_usage(row: dict[str, Any]) -> dict[str, Any]:
    breakdown = maybe_json(row.get("harness_run_token_breakdown"))
    usage = normalize_usage(breakdown) if isinstance(breakdown, dict) else {}
    explicit_total = as_number(row.get("harness_run_tokens"))
    if explicit_total is not None and usage.get("total_tokens") is None:
        usage = {**usage, "total_tokens": int(explicit_total)}
    return usage


def aggregate_eval_tokens(rows: list[dict[str, Any]]) -> dict[str, Any]:
    harness_usages = [row_token_usage(row) for row in rows]
    harness_breakdown = merge_token_usages(harness_usages)
    harness_tokens = token_total(harness_breakdown)
    if harness_tokens is None:
        harness_tokens = sum_numeric([row.get("harness_run_tokens") for row in rows])

    judge_tokens = 0
    judge_found = False
    for row in rows:
        nested = sum_nested_token_keys(row.get("score_breakdown"), JUDGE_TOKEN_KEYS)
        if nested is not None:
            judge_tokens += nested
            judge_found = True

    interactions = sum_numeric([row.get("harness_run_interactions") for row in rows])
    total = None
    if harness_tokens is not None or judge_found:
        total = int(harness_tokens or 0) + int(judge_tokens if judge_found else 0)

    return {
        "eval_harness_run_tokens": harness_tokens,
        "eval_harness_run_token_breakdown": harness_breakdown,
        "eval_judge_tokens": judge_tokens if judge_found else None,
        "eval_total_tokens": total,
        "eval_harness_run_interactions": interactions,
    }


def token_usage_from_mapping(data: dict[str, Any]) -> dict[str, Any]:
    for key in NESTED_USAGE_KEYS:
        usage = data.get(key)
        if isinstance(usage, dict):
            normalized = normalize_usage(usage)
            if token_total(normalized) is not None:
                return normalized
    if any(key in data for key in DIRECT_TOKEN_KEYS):
        normalized = normalize_usage(data)
        if token_total(normalized) is not None:
            return normalized
    return {}


def artifact_generation_usage(artifact_dir: Path) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    for path in (artifact_dir / "meta.json", artifact_dir / "metrics.json"):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        usage = token_usage_from_mapping(data)
        if usage:
            usages.append(usage)
    return merge_token_usages(usages)


def metrics_summary_from_file(metrics_path: Path) -> dict[str, Any]:
    if not metrics_path.exists():
        return {}
    metrics = read_json(metrics_path)
    if not isinstance(metrics, dict):
        return {}
    summary = {
        "total_requests": metrics.get("total_requests", 0),
        "total_input_tokens": metrics.get("total_input_tokens", 0),
        "total_output_tokens": metrics.get("total_output_tokens", 0),
        "total_cache_read_tokens": metrics.get("total_cache_read_tokens", 0),
        "total_cache_creation_tokens": metrics.get("total_cache_creation_tokens", 0),
        "effective_requests": metrics.get("effective_requests", 0),
        "effective_input_tokens": metrics.get("effective_input_tokens", 0),
        "effective_output_tokens": metrics.get("effective_output_tokens", 0),
        "retry_requests": metrics.get("retry_requests", 0),
        "usage_source": metrics.get("usage_source"),
    }
    summary["total_tokens"] = int(summary.get("total_input_tokens") or 0) + int(summary.get("total_output_tokens") or 0)
    return {key: value for key, value in summary.items() if value is not None}


def cost_adjusted_gain(score: Any, baseline_score: Any, tokens: Any) -> float | None:
    score_value = as_number(score)
    baseline_value = as_number(baseline_score)
    token_value = as_number(tokens)
    if score_value is None or baseline_value is None or token_value is None or token_value <= 0:
        return None
    return float(score_value - baseline_value) / float(token_value)


def copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in SKIP_COPY_NAMES:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*SKIP_COPY_NAMES))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def select_artifact(generation_output: Path, task_id: str | None) -> Any:
    artifacts = discover_harness_artifacts(generation_output)
    if task_id:
        artifacts = [artifact for artifact in artifacts if artifact.task_id == task_id]
    if len(artifacts) != 1:
        found = [f"{artifact.task_id}:{artifact.path}" for artifact in artifacts]
        raise SystemExit(
            "Expected exactly one base harness artifact. "
            f"Use --task-id to disambiguate. Found: {found}"
        )
    return artifacts[0]


def apply_cli_overrides(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    override_fields = {
        "base_url": args.base_url,
        "api_key": args.api_key,
        "model_name": args.model_name,
        "claude_model_name": args.claude_model_name,
        "reasoning_effort": args.reasoning_effort,
        "eval_base_url": args.eval_base_url,
        "eval_api_key": args.eval_api_key,
        "eval_model_name": args.eval_model_name,
        "eval_reasoning_effort": args.eval_reasoning_effort,
        "meta_harness": args.meta_harness,
        "codex_bin": args.codex_bin,
        "codex_sandbox": args.codex_sandbox,
        "codex_extra_args": args.codex_extra_args,
        "pre_bmk_gate": args.pre_bmk_gate,
    }
    for key, value in override_fields.items():
        if value is not None:
            config[key] = value
    if args.codex_enable_search:
        config["codex_enable_search"] = True
    config["creation_profile"] = normalize_creation_profile(str(args.creation_profile or config.get("creation_profile") or "interface_tool"))
    config["pre_bmk_gate"] = str(config.get("pre_bmk_gate") or "soft")
    config["run_id"] = args.run_id
    return config


def sanitize_task_unit(task_unit: dict[str, Any]) -> dict[str, Any]:
    sanitized = {}
    for key, value in task_unit.items():
        lowered = key.lower()
        if key not in SAFE_TASK_METADATA_KEYS:
            continue
        if key in HIDDEN_TASK_KEYS or "diff" in lowered or lowered.endswith("_sha") or "commit_url" in lowered:
            continue
        sanitized[key] = value
    return sanitized


def task_instruction(task_unit: dict[str, Any]) -> str:
    for key in ("agent_input_prompt", "task_instruction", "instruction", "prompt", "feature_description", "summary"):
        value = task_unit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(sanitize_task_unit(task_unit), ensure_ascii=False, indent=2)


def prompt_header(artifact_task_id: str, domain: str, args: argparse.Namespace, config: dict[str, Any]) -> str:
    return f"""# Harness Self-Evolve Round

You are editing an existing generated harness, not solving a single downstream benchmark instance.

Current harness task id: {artifact_task_id}
Domain: {domain}
Meta harness: {config.get("meta_harness")}
Generation model: {config.get("model_name")}
Creation profile: {config.get("creation_profile")}

## Non-negotiable contract

- Keep the generated harness runnable as a standard artifact under `harness/`.
- Preserve the CLI contract expected by downstream eval adapters:
  `python -m harness` or `python -m harness.cli`, with support for prompt/task input, workdir/workspace, output-dir, and max-steps/max-turns style arguments.
- Preserve or improve `result.json`, `trajectory.jsonl`, stdout/stderr logging, and domain artifacts.
- Do not hard-code benchmark answers, task ids, hidden test instances, or expected grader outputs.
- Make reusable harness improvements: context management, tool policy, verifier, retry/recovery, state tracking, artifact writing, or cost control.
- Before finishing, run a lightweight validation if feasible and record what you ran.

The downstream BMK eval will be run after this edit by the experiment runner.
"""


def build_commit_prompt(
    artifact_task_id: str,
    domain: str,
    task_unit: dict[str, Any],
    round_index: int,
    previous_eval_summary: dict[str, Any] | None,
    args: argparse.Namespace,
    config: dict[str, Any],
) -> str:
    sanitized = sanitize_task_unit(task_unit)
    instruction = task_instruction(task_unit)
    return (
        prompt_header(artifact_task_id, domain, args, config)
        + f"""
## Mode: human-commit comparable evolution

This round represents one human harness evolution task. The human reference diff is hidden.
Implement an equivalent functional improvement from the same base state, using only the instruction below.

Round: {round_index}
Task unit metadata visible to the agent:

```json
{json.dumps(sanitized, ensure_ascii=False, indent=2)}
```

Task instruction:

{instruction}

Previous downstream eval summary, if any:

```json
{json.dumps(previous_eval_summary or {}, ensure_ascii=False, indent=2)}
```

Expected final state: edited harness code in this workspace.
"""
    )


def build_goal_prompt(
    artifact_task_id: str,
    domain: str,
    round_index: int,
    previous_eval_summary: dict[str, Any] | None,
    args: argparse.Namespace,
    config: dict[str, Any],
) -> str:
    goal = args.goal or f"Improve downstream benchmark score for domain={domain}, bench={args.eval_bench}."
    return (
        prompt_header(artifact_task_id, domain, args, config)
        + f"""
## Mode: target-driven self-evolve

Goal:

{goal}

Round: {round_index} of {args.rounds}
Downstream eval domain: {args.eval_domain or domain}
Downstream eval bench: {args.eval_bench}
Eval model used by the generated harness: {config.get("eval_model_name") or config.get("model_name")}

Previous downstream eval summary:

```json
{json.dumps(previous_eval_summary or {}, ensure_ascii=False, indent=2)}
```

Your job in this round:

1. Inspect the current harness implementation and the previous eval signal.
2. Identify one or two reusable harness weaknesses.
3. Edit the harness to improve future benchmark performance under the same CLI/output contract.
4. Prefer concrete mechanism changes over prompt-only commentary.
5. Do not optimize by memorizing a specific benchmark instance.
"""
    )


def write_round_context(workspace: Path, prompt: str, previous_eval_summary: dict[str, Any] | None) -> None:
    (workspace / "CLAUDE.md").write_text(prompt, encoding="utf-8")
    context_dir = workspace / "evolution_context"
    context_dir.mkdir(exist_ok=True)
    write_json(context_dir / "previous_eval_summary.json", previous_eval_summary or {})


def snapshot_artifact(
    workspace: Path,
    artifact_dir: Path,
    *,
    base_task_id: str,
    domain: str,
    status: str,
    config: dict[str, Any],
    mode: str,
    round_index: int,
    round_name: str,
    stdout: str = "",
    stderr: str = "",
) -> Path:
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    copy_tree_contents(workspace, artifact_dir)
    meta = read_json(artifact_dir / "meta.json")
    meta.update(
        {
            "task_id": base_task_id,
            "status": status,
            "domain": domain,
            "mode": "self_evolve",
            "self_evolve_mode": mode,
            "self_evolve_round": round_index,
            "self_evolve_round_name": round_name,
            "meta_harness": config.get("meta_harness"),
            "generation_model_input": config.get("model_name_input"),
            "generation_model": config.get("model_name"),
            "eval_model_input": config.get("eval_model_name_input"),
            "eval_model": config.get("eval_model_name"),
            "reasoning_effort": config.get("reasoning_effort"),
            "eval_reasoning_effort": config.get("eval_reasoning_effort"),
            "creation_profile": config.get("creation_profile"),
            "pre_bmk_gate": config.get("pre_bmk_gate"),
            "stdout": stdout[-5000:] if stdout else "",
            "stderr": stderr[-5000:] if stderr else "",
        }
    )
    metrics_summary = metrics_summary_from_file(artifact_dir / "metrics.json")
    if metrics_summary:
        meta["metrics"] = metrics_summary
    elif round_index > 0:
        # Avoid carrying the base creation metrics into later self-evolve
        # snapshots when the meta harness did not emit per-round usage.
        meta.pop("metrics", None)
    write_json(artifact_dir / "meta.json", meta)
    return artifact_dir


def load_eval_rows(summary_jsonl: Path) -> list[dict[str, Any]]:
    if not summary_jsonl.is_file():
        return []
    rows = []
    with summary_jsonl.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize_eval(eval_dir: Path, returncode: int) -> dict[str, Any]:
    rows = load_eval_rows(eval_dir / "summary.jsonl")
    scores = [row.get("score") for row in rows if isinstance(row.get("score"), (int, float))]
    e2e_scores = [row.get("end_to_end_score") for row in rows if isinstance(row.get("end_to_end_score"), (int, float))]
    statuses: dict[str, int] = {}
    for row in rows:
        status = str(row.get("eval_status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    token_summary = aggregate_eval_tokens(rows)
    return {
        "returncode": returncode,
        "eval_dir": str(eval_dir),
        "summary_csv": str(eval_dir / "summary.csv"),
        "summary_jsonl": str(eval_dir / "summary.jsonl"),
        "rows": len(rows),
        "status_counts": statuses,
        "avg_score": sum(scores) / len(scores) if scores else None,
        "avg_end_to_end_score": sum(e2e_scores) / len(e2e_scores) if e2e_scores else None,
        **token_summary,
        "rows_preview": rows[:5],
    }


def run_downstream_eval(artifact_dir: Path, label: str, args: argparse.Namespace, config: dict[str, Any], run_root: Path) -> dict[str, Any]:
    if args.no_eval:
        return {"status": "skipped", "reason": "--no-eval"}

    eval_model_name = config.get("eval_model_name") or config.get("model_name")
    eval_base_url = config.get("eval_base_url") or config.get("base_url")
    eval_api_key = config.get("eval_api_key") or config.get("api_key")
    eval_reasoning_effort = config.get("eval_reasoning_effort") or config.get("reasoning_effort")
    eval_run_id = f"{args.run_id}-{safe_name(label)}-eval"
    eval_output_root = run_root / "eval_results"
    command = [
        sys.executable,
        "run_creation_eval.py",
        "--generation-output",
        str(artifact_dir),
        "--matrix",
        str(args.eval_matrix),
        "--bench",
        str(args.eval_bench),
        "--eval-output-root",
        str(eval_output_root),
        "--harness-evolve-root",
        str(args.harness_evolve_root),
        "--python-bin",
        sys.executable,
        "--timeout-seconds",
        str(args.eval_timeout_seconds),
        "--eval-model-name",
        str(eval_model_name),
        "--eval-base-url",
        str(eval_base_url),
        "--run-id",
        eval_run_id,
        "--pre-bmk-gate",
        str(config.get("pre_bmk_gate") or "soft"),
    ]
    if eval_reasoning_effort:
        command.extend(["--eval-reasoning-effort", str(eval_reasoning_effort)])
    if args.no_eval_provider_proxy:
        command.append("--no-eval-provider-proxy")
    command.extend(["--eval-provider-proxy-port", str(args.eval_provider_proxy_port)])
    if args.eval_domain:
        command.extend(["--domain", args.eval_domain])
    if args.eval_dry_run:
        command.append("--dry-run")

    env = os.environ.copy()
    env["EVAL_API_KEY"] = str(eval_api_key or "")
    logs_dir = run_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{safe_name(label)}.eval.stdout.log"
    stderr_path = logs_dir / f"{safe_name(label)}.eval.stderr.log"
    proc = subprocess.run(command, cwd=Path(__file__).resolve().parent, env=env, text=True, capture_output=True, check=False)
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    eval_dir = eval_output_root / eval_run_id
    summary = summarize_eval(eval_dir, proc.returncode)
    summary.update(
        {
            "status": "success" if proc.returncode == 0 else "failed",
            "label": label,
            "command": [part if part != str(eval_api_key) else "<redacted>" for part in command],
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    )
    return summary


def validate_eval_config(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if args.no_eval:
        return
    eval_base_url = config.get("eval_base_url") or config.get("base_url")
    eval_api_key = config.get("eval_api_key") or config.get("api_key")
    eval_model_name = config.get("eval_model_name") or config.get("model_name")
    missing = []
    if not eval_base_url:
        missing.append("eval_base_url/base_url")
    if not eval_api_key:
        missing.append("eval_api_key/api_key")
    if not eval_model_name:
        missing.append("eval_model_name/model_name")
    if missing:
        raise SystemExit("Missing eval LLM config for self-evolve downstream eval: " + ", ".join(missing))


def write_round_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = [
        "round",
        "round_name",
        "mode",
        "artifact_path",
        "evolve_status",
        "eval_status",
        "avg_score",
        "avg_end_to_end_score",
        "creation_or_evolve_tokens",
        "eval_harness_run_tokens",
        "eval_judge_tokens",
        "eval_total_tokens",
        "eval_harness_run_interactions",
        "cost_adjusted_gain",
        "status_counts",
        "summary_csv",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Iteratively evolve an existing generated harness and run downstream BMK eval after each round."
    )
    parser.add_argument("config", nargs="?", default="config.yaml")
    parser.add_argument("--mode", choices=["goal", "commit", "human-commit"], default=None)
    parser.add_argument("--run-id", default=now_run_id())
    parser.add_argument("--base-generation-output", type=Path, required=True)
    parser.add_argument("--task-id", default=None, help="Select one artifact from --base-generation-output.")
    parser.add_argument("--output-root", type=Path, default=Path("self_evolve_outputs"))
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--goal", default=None)
    parser.add_argument("--evolution-tasks-file", type=Path, default=None)
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--human-generation-output", type=Path, default=None, help="Optional human reference artifact to evaluate with the same BMK config.")

    parser.add_argument("--meta-harness", choices=["claude-code", "codex"], default=None)
    parser.add_argument("--codex-bin", default=None)
    parser.add_argument("--codex-sandbox", choices=["read-only", "workspace-write", "danger-full-access"], default=None)
    parser.add_argument("--codex-enable-search", action="store_true")
    parser.add_argument("--codex-extra-args", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--claude-model-name", default=None)
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None)
    parser.add_argument("--creation-profile", choices=["freeform", "interface", "interface_tool", "interface-tool", "full_loop", "full-loop"], default=None)

    parser.add_argument("--eval-bench", default="all")
    parser.add_argument("--eval-domain", default=None)
    parser.add_argument("--eval-matrix", default="eval_matrix.yaml")
    parser.add_argument("--eval-base-url", default=None)
    parser.add_argument("--eval-api-key", default=None)
    parser.add_argument("--eval-model-name", default=None)
    parser.add_argument("--eval-reasoning-effort", choices=["low", "medium", "high", "xhigh", "max"], default=None)
    parser.add_argument("--eval-timeout-seconds", default="3600")
    parser.add_argument("--eval-provider-proxy-port", type=int, default=3458)
    parser.add_argument("--no-eval-provider-proxy", action="store_true")
    parser.add_argument("--eval-dry-run", action="store_true")
    parser.add_argument("--no-eval", action="store_true")
    parser.add_argument("--pre-bmk-gate", choices=["off", "soft", "hard"], default=None)
    parser.add_argument("--harness-evolve-root", type=Path, default=Path("/Users/bytedance/Downloads/harness evolve project"))
    parser.add_argument("--timeout-minutes", type=int, default=None)
    parser.add_argument("--keep-workspace", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    harness_eval_root = Path(__file__).resolve().parent
    load_env_file(harness_eval_root / "secrets.local.env")
    load_env_file(args.harness_evolve_root / "secrets.local.env")

    config = load_config(args.config)
    self_cfg = config.get("self_evolve") if isinstance(config.get("self_evolve"), dict) else {}
    args.mode = args.mode or str(self_cfg.get("mode") or "goal")
    args.mode = "commit" if args.mode == "human-commit" else args.mode
    args.rounds = int(args.rounds if args.rounds is not None else self_cfg.get("rounds", 3))
    args.goal = args.goal if args.goal is not None else self_cfg.get("goal")
    if args.evolution_tasks_file is None and self_cfg.get("evolution_tasks_file"):
        args.evolution_tasks_file = Path(str(self_cfg["evolution_tasks_file"]))

    config = apply_cli_overrides(config, args)
    config = resolve_config_models(config)
    config["run_id"] = args.run_id
    if args.timeout_minutes is not None:
        config["timeout_minutes"] = args.timeout_minutes
    validate_generation_config(config)
    validate_eval_config(args, config)

    base_artifact = select_artifact(args.base_generation_output, args.task_id)
    run_root = (args.output_root / args.run_id).resolve()
    artifacts_root = run_root / "artifacts"
    logs_root = run_root / "logs"
    prompts_root = run_root / "prompts"
    run_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(exist_ok=True)
    prompts_root.mkdir(exist_ok=True)

    workspace_base = Path.home() / ".harness-eval" / "self_evolve_workspaces"
    workspace_base.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f"{safe_name(args.run_id)}_", dir=str(workspace_base)))
    copy_tree_contents(base_artifact.path, workspace)

    if str(config.get("meta_harness") or "claude-code") == "claude-code":
        build_docker_image()

    rounds: list[dict[str, Any]]
    if args.mode == "commit":
        if not args.evolution_tasks_file:
            raise SystemExit("--evolution-tasks-file is required for --mode commit")
        rounds = read_jsonl(args.evolution_tasks_file)
        if args.max_tasks:
            rounds = rounds[: args.max_tasks]
    else:
        rounds = [{} for _ in range(args.rounds)]

    run_config = {
        "run_id": args.run_id,
        "mode": args.mode,
        "base_generation_output": str(args.base_generation_output),
        "base_artifact": str(base_artifact.path),
        "task_id": base_artifact.task_id,
        "domain": base_artifact.domain,
        "meta_harness": config.get("meta_harness"),
        "model_name": config.get("model_name"),
        "model_name_input": config.get("model_name_input"),
        "eval_model_name": config.get("eval_model_name") or config.get("model_name"),
        "eval_model_name_input": config.get("eval_model_name_input"),
        "reasoning_effort": config.get("reasoning_effort"),
        "eval_reasoning_effort": config.get("eval_reasoning_effort") or config.get("reasoning_effort"),
        "creation_profile": config.get("creation_profile"),
        "pre_bmk_gate": config.get("pre_bmk_gate"),
        "eval_bench": args.eval_bench,
        "eval_domain": args.eval_domain or base_artifact.domain,
        "goal": args.goal,
        "round_count": len(rounds),
    }
    write_json(run_root / "run_config.json", run_config)

    round_rows: list[dict[str, Any]] = []
    previous_eval_summary: dict[str, Any] | None = None

    base_status = str(read_json(base_artifact.path / "meta.json").get("status") or "success")
    baseline_artifact = snapshot_artifact(
        workspace,
        artifacts_root / "round_000_base" / base_artifact.task_id,
        base_task_id=base_artifact.task_id,
        domain=base_artifact.domain,
        status=base_status,
        config=config,
        mode=args.mode,
        round_index=0,
        round_name="base",
    )
    baseline_generation_usage = artifact_generation_usage(baseline_artifact)
    baseline_generation_tokens = token_total(baseline_generation_usage)
    baseline_eval = run_downstream_eval(baseline_artifact, "round_000_base", args, config, run_root)
    previous_eval_summary = baseline_eval
    baseline_score = baseline_eval.get("avg_score")
    round_rows.append(
        {
            "round": 0,
            "round_name": "base",
            "mode": args.mode,
            "artifact_path": str(baseline_artifact),
            "evolve_status": "base",
            "eval_status": baseline_eval.get("status"),
            "avg_score": baseline_eval.get("avg_score"),
            "avg_end_to_end_score": baseline_eval.get("avg_end_to_end_score"),
            "creation_or_evolve_tokens": baseline_generation_tokens,
            "creation_or_evolve_token_breakdown": baseline_generation_usage,
            "eval_harness_run_tokens": baseline_eval.get("eval_harness_run_tokens"),
            "eval_harness_run_token_breakdown": baseline_eval.get("eval_harness_run_token_breakdown"),
            "eval_judge_tokens": baseline_eval.get("eval_judge_tokens"),
            "eval_total_tokens": baseline_eval.get("eval_total_tokens"),
            "eval_harness_run_interactions": baseline_eval.get("eval_harness_run_interactions"),
            "cost_adjusted_gain": None,
            "status_counts": json.dumps(baseline_eval.get("status_counts", {}), ensure_ascii=False),
            "summary_csv": baseline_eval.get("summary_csv"),
        }
    )

    for index, task_unit in enumerate(rounds, start=1):
        if args.mode == "commit":
            round_name = str(task_unit.get("id") or task_unit.get("name") or f"commit_task_{index}")
            prompt = build_commit_prompt(
                base_artifact.task_id,
                base_artifact.domain,
                task_unit,
                index,
                previous_eval_summary,
                args,
                config,
            )
        else:
            round_name = f"target_goal_{index}"
            prompt = build_goal_prompt(
                base_artifact.task_id,
                base_artifact.domain,
                index,
                previous_eval_summary,
                args,
                config,
            )
        prompt_path = prompts_root / f"round_{index:03d}_{safe_name(round_name)}.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        write_round_context(workspace, prompt, previous_eval_summary)

        stale_metrics = workspace / "metrics.json"
        if stale_metrics.exists():
            stale_metrics.unlink()
        started = time.time()
        status, stdout, stderr = run_generation(
            f"{base_artifact.task_id}-evolve-{index}",
            str(workspace),
            config,
            int(config.get("timeout_minutes", 30)) * 60,
        )
        elapsed = time.time() - started
        (logs_root / f"round_{index:03d}_{safe_name(round_name)}.stdout.log").write_text(stdout or "", encoding="utf-8")
        (logs_root / f"round_{index:03d}_{safe_name(round_name)}.stderr.log").write_text(stderr or "", encoding="utf-8")

        artifact_path = snapshot_artifact(
            workspace,
            artifacts_root / f"round_{index:03d}_{safe_name(round_name)}" / base_artifact.task_id,
            base_task_id=base_artifact.task_id,
            domain=base_artifact.domain,
            status=status,
            config=config,
            mode=args.mode,
            round_index=index,
            round_name=round_name,
            stdout=stdout,
            stderr=stderr,
        )
        evolve_usage = artifact_generation_usage(artifact_path)
        evolve_tokens = token_total(evolve_usage)
        eval_summary = run_downstream_eval(artifact_path, f"round_{index:03d}_{round_name}", args, config, run_root)
        previous_eval_summary = eval_summary
        total_round_tokens = sum_numeric([evolve_tokens, eval_summary.get("eval_total_tokens")])
        round_rows.append(
            {
                "round": index,
                "round_name": round_name,
                "mode": args.mode,
                "artifact_path": str(artifact_path),
                "evolve_status": status,
                "evolve_elapsed_sec": elapsed,
                "eval_status": eval_summary.get("status"),
                "avg_score": eval_summary.get("avg_score"),
                "avg_end_to_end_score": eval_summary.get("avg_end_to_end_score"),
                "creation_or_evolve_tokens": evolve_tokens,
                "creation_or_evolve_token_breakdown": evolve_usage,
                "eval_harness_run_tokens": eval_summary.get("eval_harness_run_tokens"),
                "eval_harness_run_token_breakdown": eval_summary.get("eval_harness_run_token_breakdown"),
                "eval_judge_tokens": eval_summary.get("eval_judge_tokens"),
                "eval_total_tokens": eval_summary.get("eval_total_tokens"),
                "eval_harness_run_interactions": eval_summary.get("eval_harness_run_interactions"),
                "cost_adjusted_gain": cost_adjusted_gain(eval_summary.get("avg_score"), baseline_score, total_round_tokens),
                "status_counts": json.dumps(eval_summary.get("status_counts", {}), ensure_ascii=False),
                "summary_csv": eval_summary.get("summary_csv"),
            }
        )

    human_eval = None
    if args.human_generation_output:
        human_artifact = select_artifact(args.human_generation_output, args.task_id)
        human_eval = run_downstream_eval(human_artifact.path, "human_reference", args, config, run_root)

    write_json(run_root / "rounds.json", round_rows)
    write_round_csv(run_root / "rounds.csv", round_rows)
    summary = {
        "run_id": args.run_id,
        "run_root": str(run_root),
        "workspace": str(workspace),
        "kept_workspace": args.keep_workspace,
        "rounds": round_rows,
        "final_artifact": round_rows[-1]["artifact_path"] if round_rows else str(baseline_artifact),
        "human_reference_eval": human_eval,
        "token_totals": {
            "creation_or_evolve_tokens": sum_numeric([row.get("creation_or_evolve_tokens") for row in round_rows]),
            "eval_harness_run_tokens": sum_numeric([row.get("eval_harness_run_tokens") for row in round_rows]),
            "eval_judge_tokens": sum_numeric([row.get("eval_judge_tokens") for row in round_rows]),
            "eval_total_tokens": sum_numeric([row.get("eval_total_tokens") for row in round_rows]),
        },
    }
    write_json(run_root / "summary.json", summary)
    if not args.keep_workspace:
        shutil.rmtree(workspace, ignore_errors=True)
        summary["workspace"] = ""
        write_json(run_root / "summary.json", summary)

    print(json.dumps({"run_id": args.run_id, "run_root": str(run_root), "rounds": len(round_rows), "final_artifact": summary["final_artifact"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
