#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from creation_eval.benchmarks import base_row, filter_matrix, load_matrix, run_benchmark
from creation_eval.llm_runtime import LLMRuntime, configure_eval_llm
from creation_eval.model_aliases import resolve_model_alias
from creation_eval.schema import HarnessRunResult
from creation_eval.utils import best_python_bin, load_env_file, write_json, write_jsonl, write_summary_csv
from creation_eval.validator import discover_harness_artifacts, validate_artifact


def parse_csv_set(value: str | None) -> set[str] | None:
    if not value:
        return None
    items = {item.strip() for item in value.split(",") if item.strip()}
    return items or None


def apply_max_tasks_per_bmk(matrix: list[dict], limit: int) -> list[dict]:
    if limit <= 0:
        return [dict(entry) for entry in matrix]
    limited = []
    for entry in matrix:
        item = dict(entry)
        item["n_limit"] = limit
        runner = str(item.get("runner") or "")
        if runner == "dacomp_generated":
            item["task_ids"] = "all"
            item["n_limit"] = limit
        elif runner == "eqbench3":
            item["default_subset"] = str(limit)
        elif runner == "the_agent_company_generated":
            item["task_image_name"] = "all"
            item["n_limit"] = limit
        limited.append(item)
    return limited


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run generated harness artifacts through downstream benchmark adapters."
    )
    parser.add_argument("--generation-output", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, default=Path("eval_matrix.yaml"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--bench", default="all", help="Comma-separated benchmark ids/names, or all.")
    parser.add_argument("--domain", default=None, help="Comma-separated domains to include.")
    parser.add_argument("--eval-output-root", type=Path, default=Path("eval_results"))
    parser.add_argument("--harness-evolve-root", type=Path, default=Path("/Users/bytedance/Downloads/harness evolve project"))
    parser.add_argument("--generation-model", default=None)
    parser.add_argument("--python-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--eval-base-url", default=None, help="OpenAI-compatible base URL or chat completions URL for eval-time harness LLM.")
    parser.add_argument("--eval-api-key", default=None, help="API key for eval-time harness LLM.")
    parser.add_argument("--eval-model-name", default=None, help="Model or configured alias used by the generated harness during downstream eval.")
    parser.add_argument(
        "--eval-reasoning-effort",
        default=None,
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Reasoning/verbosity level injected by the local provider proxy.",
    )
    parser.add_argument(
        "--no-eval-provider-proxy",
        action="store_true",
        help="Do not start the local provider proxy; pass eval LLM config directly to generated harnesses.",
    )
    parser.add_argument("--eval-provider-proxy-port", type=int, default=3458)
    parser.add_argument("--dry-run", action="store_true", help="Validate and dependency-check only; do not launch BMK commands.")
    parser.add_argument("--max-tasks-per-bmk", type=int, default=0, help="Limit each BMK to this many public/dev tasks. Omit for full eval.")
    parser.add_argument("--pre-bmk-gate", default="off", choices=["off", "soft", "hard"], help=argparse.SUPPRESS)
    parser.add_argument("--pre-bmk-timeout-seconds", type=int, default=300, help=argparse.SUPPRESS)
    parser.add_argument("--refresh-pre-bmk-gate", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--proxy-smoke-for-unsupported",
        action="store_true",
        help="For unsupported BMK adapters, run a generated-harness smoke proxy and mark it as non-downstream-BMK.",
    )
    parser.add_argument("--max-harnesses", type=int, default=0)
    parser.add_argument(
        "--adapter-mode",
        default="strict",
        choices=["strict", "permissive"],
        help=(
            "Generated harness invocation mode. strict uses only the fixed scaffold/canonical "
            "contract; permissive keeps legacy CLI probing and runtime patches for debugging."
        ),
    )
    args = parser.parse_args()

    harness_eval_root = Path(__file__).resolve().parent
    force_dry_run_file = harness_eval_root / ".force_creation_eval_dry_run"
    if force_dry_run_file.exists():
        args.dry_run = True
    load_env_file(harness_eval_root / "secrets.local.env")
    load_env_file(args.harness_evolve_root / "secrets.local.env")
    os.environ["HARNESS_EVAL_ADAPTER_MODE"] = args.adapter_mode
    run_id = args.run_id or "creation-eval-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = (args.eval_output_root / run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    eval_model_input = args.eval_model_name or os.environ.get("MODEL_NAME") or ""
    eval_model_resolved = resolve_model_alias(eval_model_input)
    runtime = LLMRuntime()
    if not args.dry_run:
        runtime = configure_eval_llm(
            harness_eval_root=harness_eval_root,
            base_url=args.eval_base_url,
            api_key=args.eval_api_key,
            model_name=args.eval_model_name,
            reasoning_effort=args.eval_reasoning_effort,
            provider_proxy=not args.no_eval_provider_proxy,
            provider_proxy_port=args.eval_provider_proxy_port,
            log_path=output_dir / "eval_provider_proxy.log",
        )

    try:
        python_bin = best_python_bin(args.python_bin)
        matrix = load_matrix(args.matrix)
        domains = parse_csv_set(args.domain)
        benches = parse_csv_set(args.bench)
        selected_matrix = filter_matrix(matrix, domains=domains, benches=benches)
        selected_matrix = apply_max_tasks_per_bmk(selected_matrix, args.max_tasks_per_bmk)
        artifacts = discover_harness_artifacts(args.generation_output, args.generation_model)
        if args.max_harnesses:
            artifacts = artifacts[: args.max_harnesses]

        validations = {}
        rows = []
        for artifact in artifacts:
            validation = validate_artifact(artifact, python_bin=python_bin)
            validation.pre_bmk_gate_mode = "off"
            validation.creation_profile = str(validation.meta.get("creation_profile") or "")
            validation.meta["eval_model"] = eval_model_resolved or ""
            validation.meta["eval_model_input"] = eval_model_input
            validation.meta["eval_reasoning_effort"] = args.eval_reasoning_effort or os.environ.get("REASONING_EFFORT") or ""
            validations[str(artifact.path)] = {
                "task_id": artifact.task_id,
                "domain": artifact.domain,
                "generation_model": artifact.generation_model,
                "creation_profile": validation.creation_profile,
                "generation_status": validation.generation_status,
                "creation_attempts": validation.creation_attempts,
                "repair_rounds": validation.repair_rounds,
                "gate_pass_before_repair": validation.gate_pass_before_repair,
                "gate_pass_after_repair": validation.gate_pass_after_repair,
                "repair_failure_reasons": validation.repair_failure_reasons,
                "repair_tokens": validation.repair_tokens,
                "selected_attempt_path": validation.selected_attempt_path,
                "syntax_ok": validation.syntax_ok,
                "import_ok": validation.import_ok,
                "cli_probe_ok": validation.cli_probe_ok,
                "adapter_status": validation.adapter_status,
                "adapter_mode": args.adapter_mode,
                "pre_bmk_gate_mode": validation.pre_bmk_gate_mode,
                "gate_pass": validation.pre_bmk_gate_pass,
                "gate_failure_reason": validation.pre_bmk_failure_reason,
                "toy_task_score": validation.pre_bmk_toy_task_score,
                "static_check_pass": validation.pre_bmk_static_pass,
                "artifact_check_pass": validation.pre_bmk_artifact_pass,
                "pre_bmk_report_path": validation.pre_bmk_report_path,
                "missing_dependencies": validation.missing_dependencies,
                "errors": validation.errors,
            }
            for entry in selected_matrix:
                if entry.get("domain") != artifact.domain:
                    continue
                bench_output_dir = output_dir / artifact.task_id / str(entry.get("id"))
                bench_output_dir.mkdir(parents=True, exist_ok=True)
                try:
                    result = run_benchmark(
                        artifact,
                        validation,
                        entry,
                        bench_output_dir,
                        harness_eval_root=harness_eval_root,
                        harness_evolve_root=args.harness_evolve_root,
                        python_bin=python_bin,
                        timeout=args.timeout_seconds,
                        dry_run=args.dry_run,
                        proxy_smoke_for_unsupported=args.proxy_smoke_for_unsupported,
                    )
                except Exception as exc:  # noqa: BLE001
                    result = HarnessRunResult(
                        status="failed",
                        missing_dependencies=[f"runner_exception: {type(exc).__name__}: {exc}"],
                        error=str(exc),
                    )
                rows.append(base_row(artifact, validation, entry, result))

        write_json(output_dir / "validation.json", validations)
        write_jsonl(output_dir / "summary.jsonl", rows)
        write_summary_csv(output_dir / "summary.csv", rows)
        write_json(
            output_dir / "run_config.json",
            {
                "run_id": run_id,
                "generation_output": str(args.generation_output),
                "matrix": str(args.matrix),
                "bench": args.bench,
                "domain": args.domain,
                "dry_run": args.dry_run,
                "pre_bmk_gate": "off",
                "public_validation_gate": "disabled",
                "max_tasks_per_bmk": args.max_tasks_per_bmk,
                "proxy_smoke_for_unsupported": args.proxy_smoke_for_unsupported,
                "eval_model_name": eval_model_resolved,
                "eval_model_input": eval_model_input,
                "eval_reasoning_effort": args.eval_reasoning_effort or os.environ.get("REASONING_EFFORT") or "",
                "eval_provider_proxy": (not args.no_eval_provider_proxy and not args.dry_run),
                "eval_provider_proxy_log": str(runtime.log_path) if runtime.log_path else None,
                "adapter_mode": args.adapter_mode,
                "python_bin": python_bin,
                "harness_evolve_root": str(args.harness_evolve_root),
                "rows": len(rows),
                "artifacts": len(artifacts),
            },
        )

        status_counts = {}
        for row in rows:
            status_counts[row["eval_status"]] = status_counts.get(row["eval_status"], 0) + 1
        print(json.dumps({"run_id": run_id, "output_dir": str(output_dir), "rows": len(rows), "status_counts": status_counts}, ensure_ascii=False, indent=2))
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
