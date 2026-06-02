#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TASK_IDS = [
    "code-agent-harness",
    "data-analysis-harness",
    "writing-harness",
    "research-agent-harness",
    "browser-agent-harness",
]

ANTHROPIC_ENV_KEYS = [
    "CLAUDE_NATIVE_ANTHROPIC",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    "CLAUDE_CODE_THINKING",
    "CLAUDE_CODE_THINKING_EFFORT",
]


@dataclass
class ModelSpec:
    key: str
    label: str
    base_url: str
    api_key: str
    model: str
    effort: str
    native_anthropic: bool = False
    claude_model_name: str = "claude-sonnet-4-6"


def now_id() -> str:
    return datetime.now().strftime("full-exp-%Y%m%d-%H%M%S")


def env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_model_specs() -> dict[str, ModelSpec]:
    specs = {
        "opus47": ModelSpec(
            key="opus47",
            label="opus4.7_max",
            base_url=env_value("OPUS47_BASE_URL") or env_value("ANTHROPIC_BASE_URL"),
            api_key=env_value("OPUS47_API_KEY") or env_value("ANTHROPIC_AUTH_TOKEN") or env_value("ANTHROPIC_API_KEY"),
            model=env_value("OPUS47_MODEL") or env_value("ANTHROPIC_MODEL", "es1_orange_o47"),
            effort=env_value("OPUS47_EFFORT", "max"),
            native_anthropic=True,
            claude_model_name=env_value("OPUS47_CLAUDE_MODEL_NAME") or env_value("ANTHROPIC_MODEL", "es1_orange_o47"),
        ),
        "gpt55": ModelSpec(
            key="gpt55",
            label="gpt5.5",
            base_url=env_value("GPT55_BASE_URL"),
            api_key=env_value("GPT55_API_KEY", "not-needed"),
            model=env_value("GPT55_MODEL", "gpt-5.5-2026-04-24"),
            effort=env_value("GPT55_EFFORT", "max"),
            native_anthropic=False,
            claude_model_name=env_value("GPT55_CLAUDE_MODEL_NAME", "claude-sonnet-4-6"),
        ),
        "seed20pro": ModelSpec(
            key="seed20pro",
            label="seed2.0_pro",
            base_url=env_value("SEED20PRO_BASE_URL") or env_value("SEED2LITE_CHAT_COMPLETIONS_URL_HTTP") or env_value("SEED2LITE_BASE_URL"),
            api_key=env_value("SEED20PRO_API_KEY") or env_value("SEED2LITE_API_KEY"),
            model=env_value("SEED20PRO_MODEL", "ep-20260313114009-v6nvw"),
            effort=env_value("SEED20PRO_EFFORT", "high"),
            native_anthropic=False,
            claude_model_name=env_value("SEED20PRO_CLAUDE_MODEL_NAME", "claude-sonnet-4-6"),
        ),
    }
    return specs


def parse_keys(value: str, available: dict[str, ModelSpec]) -> list[str]:
    keys = [item.strip() for item in value.split(",") if item.strip()]
    if not keys or keys == ["all"]:
        keys = list(available)
    unknown = [key for key in keys if key not in available]
    if unknown:
        raise SystemExit(f"Unknown model keys: {unknown}. Available: {sorted(available)}")
    return keys


def ensure_specs(specs: dict[str, ModelSpec], keys: list[str]) -> None:
    missing: dict[str, list[str]] = {}
    for key in keys:
        spec = specs[key]
        fields = []
        if not spec.base_url:
            fields.append(f"{key.upper()}_BASE_URL")
        if not spec.api_key:
            fields.append(f"{key.upper()}_API_KEY")
        if not spec.model:
            fields.append(f"{key.upper()}_MODEL")
        if fields:
            missing[key] = fields
    if missing:
        raise SystemExit("Missing model config: " + json.dumps(missing, indent=2))


def redacted_spec(spec: ModelSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["base_url"] = redact_url(payload.get("base_url", ""))
    payload["api_key"] = "<redacted>"
    return payload


def redact_url(value: str) -> str:
    if not value:
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not query:
        return value
    redacted_query = []
    redacted_any = False
    for key, val in query:
        if key.lower() in {"ak", "api_key", "apikey", "key", "token", "access_token"}:
            redacted_query.append((key, "<redacted>"))
            redacted_any = True
        else:
            redacted_query.append((key, val))
    if not redacted_any:
        return value
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(redacted_query),
            parsed.fragment,
        )
    )


def redacted_command(command: list[str]) -> str:
    redacted: list[str] = []
    redact_next = False
    redact_url_next = False
    for part in command:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if redact_url_next:
            redacted.append(redact_url(part))
            redact_url_next = False
            continue
        if part in {"--api-key", "--eval-api-key"}:
            redacted.append(part)
            redact_next = True
            continue
        if part in {"--base-url", "--eval-base-url"}:
            redacted.append(part)
            redact_url_next = True
            continue
        redacted.append(part)
    return " ".join(shlex.quote(part) for part in redacted)


def run_logged(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    dry_run: bool,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    printable = redacted_command(command)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {datetime.now().isoformat()} ===\n")
        log.write(printable + "\n\n")
        log.flush()
        if dry_run:
            log.write("[dry-run] command not executed\n")
            return 0
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        return proc.wait()


def base_env_for_model(spec: ModelSpec) -> dict[str, str]:
    env = os.environ.copy()
    for key in ANTHROPIC_ENV_KEYS:
        env.pop(key, None)
    env.update(
        {
            "BASE_URL": spec.base_url,
            "API_KEY": spec.api_key,
            "MODEL_NAME": spec.model,
        }
    )
    if spec.native_anthropic:
        env.update(
            {
                "CLAUDE_NATIVE_ANTHROPIC": "1",
                "ANTHROPIC_BASE_URL": spec.base_url,
                "ANTHROPIC_AUTH_TOKEN": spec.api_key,
                "ANTHROPIC_API_KEY": spec.api_key,
                "ANTHROPIC_MODEL": spec.model,
                "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
                "CLAUDE_CODE_THINKING": "adaptive",
                "CLAUDE_CODE_THINKING_EFFORT": spec.effort,
            }
        )
    return env


def generation_command(args: argparse.Namespace, spec: ModelSpec, output_dir: Path) -> list[str]:
    return [
        args.python_bin,
        "run.py",
        "--output-dir",
        str(output_dir),
        "--meta-harness",
        "claude-code",
        "--base-url",
        spec.base_url,
        "--api-key",
        spec.api_key,
        "--model-name",
        spec.model,
        "--claude-model-name",
        spec.claude_model_name,
        "--reasoning-effort",
        spec.effort,
        "--creation-profile",
        args.creation_profile,
        "--pre-bmk-gate",
        args.pre_bmk_gate,
        "--task-id",
        ",".join(args.task_ids),
        "--max-concurrent",
        str(args.generation_concurrency),
        "--timeout-minutes",
        str(args.generation_timeout_minutes),
    ]


def eval_command(args: argparse.Namespace, spec: ModelSpec, generation_output: Path, run_id: str, port: int) -> list[str]:
    return [
        args.python_bin,
        "run_creation_eval.py",
        "--generation-output",
        str(generation_output),
        "--matrix",
        args.eval_matrix,
        "--bench",
        args.eval_bench,
        "--eval-output-root",
        str(args.eval_output_root),
        "--harness-evolve-root",
        args.harness_evolve_root,
        "--python-bin",
        args.python_bin,
        "--timeout-seconds",
        str(args.eval_timeout_seconds),
        "--eval-base-url",
        spec.base_url,
        "--eval-api-key",
        spec.api_key,
        "--eval-model-name",
        spec.model,
        "--eval-reasoning-effort",
        spec.effort,
        "--eval-provider-proxy-port",
        str(port),
        "--pre-bmk-gate",
        args.pre_bmk_gate,
        "--run-id",
        run_id,
    ]


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full creation x eval model matrix over all BMK registry entries.")
    parser.add_argument("--experiment-id", default=now_id())
    parser.add_argument("--models", default="opus47,gpt55,seed20pro", help="Generation model keys, comma-separated.")
    parser.add_argument("--eval-models", default="opus47,gpt55,seed20pro", help="Eval model keys, comma-separated.")
    parser.add_argument("--task-ids", default=",".join(DEFAULT_TASK_IDS))
    parser.add_argument("--eval-bench", default="all")
    parser.add_argument("--eval-matrix", default="eval_matrix.yaml")
    parser.add_argument("--creation-profile", default="interface_tool")
    parser.add_argument("--pre-bmk-gate", default="soft", choices=["off", "soft", "hard"])
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--harness-evolve-root", default="/Users/bytedance/Downloads/harness evolve project")
    parser.add_argument("--generation-concurrency", type=int, default=1)
    parser.add_argument("--generation-timeout-minutes", type=int, default=180)
    parser.add_argument("--eval-timeout-seconds", type=int, default=7200)
    parser.add_argument("--eval-provider-proxy-port-base", type=int, default=3658)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/full_experiment"))
    parser.add_argument("--eval-output-root", type=Path, default=Path("eval_results/full_experiment"))
    parser.add_argument("--run-root", type=Path, default=Path("eval_results/full_experiment_runs"))
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument(
        "--resume-completed-eval",
        action="store_true",
        help="Skip eval cells whose summary.csv already exists and is non-empty.",
    )
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.task_ids = [item.strip() for item in args.task_ids.split(",") if item.strip()]

    cwd = Path(__file__).resolve().parents[1]
    specs = load_model_specs()
    gen_keys = parse_keys(args.models, specs)
    eval_keys = parse_keys(args.eval_models, specs)
    ensure_specs(specs, sorted(set(gen_keys + eval_keys)))

    run_root = (args.run_root / args.experiment_id).resolve()
    log_dir = run_root / "logs"
    manifest_path = run_root / "manifest.json"
    status_path = run_root / "runs.jsonl"
    run_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "experiment_id": args.experiment_id,
        "created_at": datetime.now().isoformat(),
        "generation_models": [redacted_spec(specs[key]) for key in gen_keys],
        "eval_models": [redacted_spec(specs[key]) for key in eval_keys],
        "task_ids": args.task_ids,
        "eval_bench": args.eval_bench,
        "creation_profile": args.creation_profile,
        "pre_bmk_gate": args.pre_bmk_gate,
        "output_root": str(args.output_root),
        "eval_output_root": str(args.eval_output_root),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    generation_outputs: dict[str, Path] = {}
    for gen_key in gen_keys:
        spec = specs[gen_key]
        output_dir = args.output_root / args.experiment_id / f"generation_{gen_key}"
        generation_outputs[gen_key] = output_dir
        if args.skip_generation:
            continue
        print(f"\n=== Generation: {gen_key} -> {output_dir} ===")
        cmd = generation_command(args, spec, output_dir)
        env = base_env_for_model(spec)
        t0 = time.time()
        code = run_logged(cmd, cwd=cwd, env=env, log_path=log_dir / f"generation_{gen_key}.log", dry_run=args.dry_run)
        row = {"stage": "generation", "model": gen_key, "returncode": code, "elapsed_sec": round(time.time() - t0, 3), "output_dir": str(output_dir)}
        write_jsonl(status_path, row)
        if code != 0 and not args.continue_on_error:
            return code

    if args.skip_eval:
        return 0

    for gen_index, gen_key in enumerate(gen_keys):
        generation_output = generation_outputs[gen_key]
        for eval_index, eval_key in enumerate(eval_keys):
            spec = specs[eval_key]
            eval_run_id = f"{args.experiment_id}-gen_{gen_key}-eval_{eval_key}"
            summary_csv = args.eval_output_root / eval_run_id / "summary.csv"
            if args.resume_completed_eval and summary_csv.exists() and summary_csv.stat().st_size > 0:
                print(f"\n=== Eval: generated={gen_key}, eval_model={eval_key}, run_id={eval_run_id} ===")
                print(f"Skipping completed eval cell because summary exists: {summary_csv}")
                write_jsonl(
                    status_path,
                    {
                        "stage": "eval",
                        "generation_model": gen_key,
                        "eval_model": eval_key,
                        "returncode": 0,
                        "elapsed_sec": 0,
                        "run_id": eval_run_id,
                        "summary_csv": str(summary_csv),
                        "skipped": "completed",
                    },
                )
                continue
            port = args.eval_provider_proxy_port_base + gen_index * 20 + eval_index
            print(f"\n=== Eval: generated={gen_key}, eval_model={eval_key}, run_id={eval_run_id} ===")
            cmd = eval_command(args, spec, generation_output, eval_run_id, port)
            env = base_env_for_model(spec)
            t0 = time.time()
            code = run_logged(cmd, cwd=cwd, env=env, log_path=log_dir / f"eval_gen_{gen_key}_eval_{eval_key}.log", dry_run=args.dry_run)
            row = {
                "stage": "eval",
                "generation_model": gen_key,
                "eval_model": eval_key,
                "returncode": code,
                "elapsed_sec": round(time.time() - t0, 3),
                "run_id": eval_run_id,
                "summary_csv": str(summary_csv),
            }
            write_jsonl(status_path, row)
            if code != 0 and not args.continue_on_error:
                return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
