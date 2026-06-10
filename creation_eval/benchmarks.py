from __future__ import annotations

import csv
import base64
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .agent_cli import read_harness_response as read_agent_cli_response, run_agent_cli
from .schema import HarnessArtifact, HarnessRunResult, ValidationResult
from .token_usage import (
    extract_harness_token_usage,
    extract_harness_token_usage_from_result,
    merge_token_usages,
)
from .utils import read_json, run_command, which_missing, write_json, write_jsonl


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    if value in {"true", "false"}:
        return value == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _load_restricted_yaml(text: str) -> dict[str, Any]:
    """Parse the small eval_matrix.yaml subset without requiring PyYAML."""
    data: dict[str, Any] = {"benchmarks": []}
    current: dict[str, Any] | None = None
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped == "benchmarks:":
            continue
        if indent == 2 and stripped.startswith("- "):
            if current:
                data["benchmarks"].append(current)
            current = {}
            current_list_key = None
            item = stripped[2:]
            if ":" in item:
                key, value = item.split(":", 1)
                current[key.strip()] = _parse_scalar(value)
            continue
        if current is None:
            continue
        if indent >= 4 and stripped.startswith("- "):
            if current_list_key is None:
                continue
            current.setdefault(current_list_key, []).append(_parse_scalar(stripped[2:]))
            continue
        if indent >= 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            if value.strip():
                current[key] = _parse_scalar(value)
                current_list_key = None
            else:
                current[key] = []
                current_list_key = key
    if current:
        data["benchmarks"].append(current)
    return data


def load_matrix(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(text)
    except ModuleNotFoundError:
        payload = _load_restricted_yaml(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("benchmarks"), list):
        raise ValueError(f"Invalid eval matrix: {path}")
    return payload["benchmarks"]


def filter_matrix(
    matrix: list[dict[str, Any]],
    *,
    domains: set[str] | None = None,
    benches: set[str] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for entry in matrix:
        bench_id = str(entry.get("id", ""))
        bench_name = str(entry.get("name", ""))
        domain = str(entry.get("domain", ""))
        if domains and domain not in domains:
            continue
        if benches and "all" not in benches and bench_id not in benches and bench_name not in benches:
            continue
        filtered.append(entry)
    return filtered


def resolve_path(value: str, harness_eval_root: Path, harness_evolve_root: Path) -> Path:
    value = value.replace("$HARNESS_EVAL_ROOT", str(harness_eval_root))
    value = value.replace("$HARNESS_EVOLVE_ROOT", str(harness_evolve_root))
    path = Path(value)
    if path.is_absolute():
        return path
    return harness_evolve_root / path


def dependency_errors(
    entry: dict[str, Any],
    *,
    harness_eval_root: Path,
    harness_evolve_root: Path,
) -> list[str]:
    missing: list[str] = []
    for path_value in entry.get("required_paths", []) or []:
        path = resolve_path(str(path_value), harness_eval_root, harness_evolve_root)
        if not path.exists():
            missing.append(f"path: {path}")
    for env_name in entry.get("required_env", []) or []:
        if not os.environ.get(str(env_name)):
            missing.append(f"env: {env_name}")
    for group in entry.get("required_env_any", []) or []:
        names = [str(item) for item in group]
        if not any(os.environ.get(name) for name in names):
            missing.append("one of env: " + ",".join(names))
    for executable in which_missing([str(item) for item in entry.get("required_executables", []) or []]):
        missing.append(f"executable: {executable}")
    return missing


def _avg_float(values: list[str]) -> float | None:
    floats = []
    for value in values:
        if value in ("", None):
            continue
        try:
            floats.append(float(value))
        except (TypeError, ValueError):
            continue
    if not floats:
        return None
    return statistics.mean(floats)


def _token_total(usage: dict[str, Any] | None) -> int | None:
    if not usage:
        return None
    value = usage.get("total_tokens")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _result_token_usage(result: HarnessRunResult) -> dict[str, Any]:
    if result.token_breakdown:
        return result.token_breakdown
    usage = extract_harness_token_usage_from_result(result)
    if usage:
        result.token_breakdown = usage
        total = _token_total(usage)
        if total is not None:
            result.harness_run_tokens = total
    return usage


def _aggregate_harness_tokens(results: list[HarnessRunResult]) -> tuple[int | None, dict[str, Any]]:
    usages = []
    per_task = []
    for index, result in enumerate(results):
        usage = _result_token_usage(result)
        total = _token_total(usage)
        if total is None:
            total = result.tokens if result.tokens is not None else result.harness_run_tokens
        if total is not None:
            usage = {**(usage or {}), "total_tokens": int(total)}
            usages.append(usage)
        per_task.append(
            {
                "index": index,
                "status": result.status,
                "tokens": int(total) if total is not None else None,
                "raw_result_path": result.raw_result_path,
            }
        )
    merged = merge_token_usages(usages)
    if per_task:
        merged["per_task"] = per_task
    total = _token_total(merged)
    return total, merged


def _sum_interactions(results: list[HarnessRunResult]) -> int | None:
    values = [result.interactions for result in results if result.interactions is not None]
    if not values:
        return None
    return int(sum(values))


def _classify_mle_grade_report(report: dict[str, Any]) -> tuple[str, float | None]:
    """Map an MLE-bench grade report to an honest (eval_status, score) pair.

    Only a real numeric metric value counts as success. Submissions the
    grader rejects (valid_submission false) and null/NaN metric values must
    not be reported as scored successes.
    """
    try:
        score = float(report.get("score"))
        if math.isnan(score):
            score = None
    except (TypeError, ValueError):
        score = None
    if report.get("valid_submission") is False:
        return "failed/invalid_submission", None
    if score is None:
        return "failed/non_numeric_score", None
    return "success", score


def _apply_result_token_fallback(result: HarnessRunResult, *paths: str | Path | None) -> HarnessRunResult:
    usage = result.token_breakdown or extract_harness_token_usage_from_result(result) or extract_harness_token_usage(*paths)
    total = _token_total(usage)
    if total is not None:
        result.harness_run_tokens = total
        result.token_breakdown = usage
    return result


def _parse_eqbench_csv(csv_path: Path) -> HarnessRunResult:
    if not csv_path.exists():
        return HarnessRunResult(status="failed", error=f"Missing EQ-Bench summary CSV: {csv_path}")
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    scored = [row for row in rows if row.get("score_100")]
    avg_score = _avg_float([row.get("score_100", "") for row in scored])
    total_tokens = _avg_float([row.get("agent_total_tokens", "") for row in rows])
    input_tokens = _avg_float([row.get("input_tokens", "") or row.get("agent_input_tokens", "") for row in rows])
    output_tokens = _avg_float([row.get("output_tokens", "") or row.get("agent_output_tokens", "") for row in rows])
    reasoning_tokens = _avg_float([row.get("reasoning_tokens", "") or row.get("agent_reasoning_tokens", "") for row in rows])
    interactions = _avg_float([row.get("agent_invocations", "") for row in rows])
    token_breakdown = {}
    if total_tokens is not None:
        token_breakdown = {
            "total_tokens": int(total_tokens),
            "input_tokens": int(input_tokens) if input_tokens is not None else None,
            "output_tokens": int(output_tokens) if output_tokens is not None else None,
            "reasoning_tokens": int(reasoning_tokens) if reasoning_tokens is not None else None,
            "source_files": [str(csv_path)],
            "source": "eqbench_summary_csv.agent_tokens",
        }
    pass_rate = len(scored) / len(rows) if rows else None
    return HarnessRunResult(
        status="success" if scored else "failed",
        score=avg_score,
        pass_rate=pass_rate,
        harness_run_tokens=int(total_tokens) if total_tokens is not None else None,
        token_breakdown={key: value for key, value in token_breakdown.items() if value is not None},
        interactions=int(interactions) if interactions is not None else None,
        raw_result_path=str(csv_path),
        score_breakdown={
            "scored_rows": len(scored),
            "total_rows": len(rows),
            "metric": "average score_100",
        },
    )


def _latest_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.rglob(name) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _write_llm_config(path: Path) -> None:
    payload = {
        "model": os.environ.get("MODEL_NAME")
        or os.environ.get("SEED2LITE_MODEL_ID")
        or os.environ.get("MODEL_ID")
        or "generated-harness",
        "base_url": os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("SEED2LITE_BASE_URL")
        or os.environ.get("BASE_URL")
        or "http://127.0.0.1:1/v1",
        "api_key": os.environ.get("OPENAI_API_KEY")
        or os.environ.get("SEED2LITE_API_KEY")
        or os.environ.get("API_KEY")
        or "not-used-by-generated-harness-runner",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_benchmark_report(report_path: Path) -> HarnessRunResult:
    if not report_path.exists():
        return HarnessRunResult(status="failed", error=f"Missing report file: {report_path}")
    report = read_json(report_path)
    completed = int(report.get("completed_instances") or 0)
    resolved = int(report.get("resolved_instances") or 0)
    submitted = int(report.get("submitted_instances") or completed or 0)
    empty_patches = int(report.get("empty_patch_instances") or 0)
    error_instances = int(report.get("error_instances") or 0)
    total = int(report.get("total_instances") or submitted or completed or 0)
    denominator = submitted or completed
    pass_rate = resolved / denominator if denominator else None
    aggregate = report.get("aggregate_metrics") or {}
    total_tokens = None
    prompt_tokens = aggregate.get("total_prompt_tokens")
    completion_tokens = aggregate.get("total_completion_tokens")
    token_breakdown: dict[str, Any] = {}
    if isinstance(prompt_tokens, int) or isinstance(completion_tokens, int):
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
        token_breakdown = {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": total_tokens,
            "source_files": [str(report_path)],
            "source": "benchmark_report.aggregate_metrics",
        }
    return HarnessRunResult(
        status="success" if submitted else "failed",
        score=pass_rate,
        pass_rate=pass_rate,
        harness_run_tokens=total_tokens,
        token_breakdown=token_breakdown,
        raw_result_path=str(report_path),
        score_breakdown={
            "metric": "resolved_instances / submitted_instances",
            "total_instances": total,
            "submitted_instances": submitted,
            "completed_instances": completed,
            "resolved_instances": resolved,
            "unresolved_instances": report.get("unresolved_instances"),
            "empty_patch_instances": empty_patches,
            "error_instances": error_instances,
        },
    )


def _common_generated_env(
    artifact: HarnessArtifact,
    *,
    harness_eval_root: Path,
    timeout: int,
) -> dict[str, str]:
    env = os.environ.copy()
    env["GENERATED_HARNESS_PATH"] = str(artifact.path)
    env["GENERATED_HARNESS_DOMAIN"] = artifact.domain
    env["GENERATED_HARNESS_TIMEOUT"] = str(timeout)
    env["PYTHONPATH"] = str(harness_eval_root) + os.pathsep + env.get("PYTHONPATH", "")
    for name in ["OPENAI_BASE_URL", "BASE_URL", "OPENAI_API_KEY", "API_KEY"]:
        container_value = os.environ.get(f"CONTAINER_{name}")
        if container_value:
            env[name] = container_value
    return env


def _container_env_value(name: str) -> str | None:
    return os.environ.get(f"CONTAINER_{name}") or os.environ.get(name)


def _read_harness_response(result: HarnessRunResult) -> str:
    return read_agent_cli_response(result)


def _http_head_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 400, f"http_status={response.status}"
    except urllib.error.HTTPError as exc:
        return 200 <= int(exc.code) < 400, f"http_status={exc.code}"
    except Exception as exc:  # noqa: BLE001 - dependency probe result is surfaced
        return False, f"{type(exc).__name__}: {exc}"


def _is_all(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"all", "full", "*"}


def _limit_value(value: Any, default: int | None = 1) -> int | None:
    if value is None:
        return default
    if _is_all(value):
        return None
    return int(value)


def _limit_sequence(rows: list[Any], value: Any, default: int | None = 1) -> list[Any]:
    limit = _limit_value(value, default)
    return rows if limit is None else rows[:limit]


def _load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
        return rows
    except json.JSONDecodeError:
        rows = []
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            obj, idx = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                rows.append(obj)
            if limit and len(rows) >= limit:
                break
        return rows


def _env_chat_config(prefix: str = "") -> dict[str, str] | None:
    key_names = [
        f"{prefix}_API_KEY" if prefix else "",
        "OPENAI_API_KEY",
        "SEED2LITE_API_KEY",
        "API_KEY",
    ]
    model_names = [
        f"{prefix}_MODEL" if prefix else "",
        "OPENAI_MODEL",
        "MODEL_NAME",
        "SEED2LITE_MODEL_ID",
        "MODEL_ID",
    ]
    url_names = [
        f"{prefix}_URL" if prefix else "",
        f"{prefix}_BASE_URL" if prefix else "",
        "API_URL",
        "SEED2LITE_CHAT_COMPLETIONS_URL_HTTP",
        "OPENAI_BASE_URL",
        "SEED2LITE_BASE_URL",
        "BASE_URL",
    ]
    api_key = next((os.environ[name] for name in key_names if name and os.environ.get(name)), "")
    model = next((os.environ[name] for name in model_names if name and os.environ.get(name)), "")
    url = next((os.environ[name] for name in url_names if name and os.environ.get(name)), "")
    if not api_key or not url:
        return None
    if not model:
        model = "ep-20260214145701-frz7j"
    if not url.rstrip("/").endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"
    return {"api_key": api_key, "model": model, "url": url}


def _call_chat(prompt: str, *, prefix: str = "", max_tokens: int = 2048, temperature: float = 0.0) -> tuple[str, dict[str, Any]]:
    config = _env_chat_config(prefix)
    if config is None:
        raise RuntimeError(f"Missing OpenAI-compatible judge config for prefix {prefix or 'default'}")
    import requests

    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    retry_sleep = float(os.environ.get("LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS", "5"))
    max_attempts = int(os.environ.get("LLM_RATE_LIMIT_MAX_ATTEMPTS", "5"))
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        response = requests.post(
            config["url"],
            headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
            json=payload,
            timeout=300,
        )
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
            break
        last_error = response.text[:1000]
        if attempt < max_attempts:
            import time

            time.sleep(retry_sleep)
            continue
    else:
        raise RuntimeError(f"Judge API rate limited after {max_attempts} attempts: {last_error}")
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Judge returned no choices: {data}")
    message = choices[0].get("message") or {}
    return str(message.get("content") or ""), data.get("usage") or {}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _judge_short_answer(question: str, correct_answer: str, response: str, *, prefix: str) -> tuple[bool, dict[str, Any]]:
    prompt = f"""Judge whether the following [response] to [question] is correct based on the precise [correct_answer].

[question]: {question}

[response]: {response}

[correct_answer]: {correct_answer}

Return only JSON with keys:
- extracted_final_answer: string
- reasoning: string
- correct: "yes" or "no"
"""
    content, usage = _call_chat(prompt, prefix=prefix, max_tokens=2048)
    parsed = _extract_json_object(content) or {}
    correct = str(parsed.get("correct", "")).lower().strip() in {"yes", "true", "correct"}
    return correct, {"judge": parsed or content, "usage": usage}


def _derive_key(password: str, length: int) -> bytes:
    hasher = hashlib.sha256()
    hasher.update(password.encode())
    key = hasher.digest()
    return key * (length // len(key)) + key[: length % len(key)]


def _decrypt_xor(ciphertext_b64: str, password: str) -> str:
    encrypted = base64.b64decode(ciphertext_b64)
    key = _derive_key(password, len(encrypted))
    return bytes(a ^ b for a, b in zip(encrypted, key)).decode()


def run_swebench_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    harness_evolve_root: Path,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    run_id = f"{output_dir.parent.parent.name}-{output_dir.name}"
    benchmarks_root = harness_evolve_root / "harness_house" / "benchmarks"
    stdout_path = output_dir / "swebench_stdout.log"
    stderr_path = output_dir / "swebench_stderr.log"
    infer_output_dir = output_dir / "swebench_infer"
    llm_config = output_dir / "generated_harness_llm_config.json"
    report_path = output_dir / "swebench_report.json"
    predictions_path = output_dir / "swebench_predictions.jsonl"

    if dry_run:
        return HarnessRunResult(
            status="skipped/dry_run",
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    _write_llm_config(llm_config)
    dataset = str(entry.get("dataset", "princeton-nlp/SWE-bench_Verified"))
    split = str(entry.get("split", "test"))
    n_limit = _limit_value(entry.get("n_limit"), default=1)
    infer_cmd = [
        "uv",
        "run",
        "swebench-infer",
        str(llm_config),
        "--dataset",
        dataset,
        "--split",
        split,
        "--workspace",
        str(entry.get("workspace", "docker")),
        "--num-workers",
        str(entry.get("threads", 1)),
        "--agent-type",
        "generated-harness",
        "--output-dir",
        str(infer_output_dir),
        "--note",
        run_id,
        "--n-critic-runs",
        "1",
        "--max-retries",
        str(entry.get("max_retries", 0)),
        "--max-iterations",
        str(entry.get("max_iterations", 1)),
    ]
    if n_limit is not None:
        infer_cmd.extend(["--n-limit", str(n_limit)])
    selected_instances = entry.get("selected_instances") or entry.get("selected_instance_ids")
    selected_instances_file = entry.get("selected_instances_file")
    if selected_instances and not selected_instances_file:
        selected_instances_file_path = output_dir / "selected_instances.txt"
        if isinstance(selected_instances, str):
            selected_values = [item.strip() for item in selected_instances.split(",") if item.strip()]
        else:
            selected_values = [str(item).strip() for item in selected_instances if str(item).strip()]
        selected_instances_file_path.write_text("\n".join(selected_values) + "\n", encoding="utf-8")
        selected_instances_file = str(selected_instances_file_path)
    if selected_instances_file:
        infer_cmd.extend(["--select", str(resolve_path(str(selected_instances_file), harness_eval_root, harness_evolve_root))])
    env = _common_generated_env(artifact, harness_eval_root=harness_eval_root, timeout=timeout)
    infer = run_command(infer_cmd, cwd=benchmarks_root, env=env, timeout=timeout)
    stdout_path.write_text(infer.stdout, encoding="utf-8")
    stderr_path.write_text(infer.stderr, encoding="utf-8")
    if infer.returncode != 0:
        return HarnessRunResult(
            status="failed/timeout" if infer.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=infer.stderr[-2000:] or infer.stdout[-2000:],
        )

    output_json = _latest_file(infer_output_dir, "output.jsonl")
    if output_json is None:
        return HarnessRunResult(
            status="failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=f"Missing SWE-bench output.jsonl under {infer_output_dir}",
        )

    eval_cmd = [
        "uv",
        "run",
        "swebench-eval",
        str(output_json),
        "--dataset",
        dataset,
        "--split",
        split,
        "--run-id",
        run_id,
        "--workers",
        str(entry.get("eval_workers", 1)),
        "--timeout",
        str(entry.get("eval_timeout", 1800)),
        "--output-file",
        str(predictions_path),
    ]
    if not bool(entry.get("modal", False)):
        eval_cmd.append("--no-modal")
    evaluate = run_command(eval_cmd, cwd=benchmarks_root, env=env, timeout=timeout)
    stdout_path.write_text(infer.stdout + "\n\n=== swebench-eval ===\n" + evaluate.stdout, encoding="utf-8")
    stderr_path.write_text(infer.stderr + "\n\n=== swebench-eval ===\n" + evaluate.stderr, encoding="utf-8")
    generated_report = output_json.with_suffix(".report.json")
    if generated_report.exists():
        generated_report.replace(report_path)
    if evaluate.returncode != 0 and not report_path.exists():
        return HarnessRunResult(
            status="failed/timeout" if evaluate.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(output_json),
            error=evaluate.stderr[-2000:] or evaluate.stdout[-2000:],
        )
    parsed = _parse_benchmark_report(report_path)
    parsed.stdout_path = str(stdout_path)
    parsed.stderr_path = str(stderr_path)
    parsed.raw_result_path = str(report_path)
    return parsed


def run_terminalbench_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    harness_evolve_root: Path,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    run_id = f"{output_dir.parent.parent.name}-{output_dir.name}"
    benchmarks_root = harness_evolve_root / "harness_house" / "benchmarks"
    stdout_path = output_dir / "terminalbench_stdout.log"
    stderr_path = output_dir / "terminalbench_stderr.log"
    harbor_output_dir = output_dir / "harbor_output"
    output_json = output_dir / "terminalbench_output.jsonl"
    report_path = output_dir / "terminalbench_report.json"

    if dry_run:
        return HarnessRunResult(
            status="skipped/dry_run",
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    dataset = str(entry.get("dataset", "terminal-bench@2.0"))
    env = _common_generated_env(artifact, harness_eval_root=harness_eval_root, timeout=timeout)
    harbor_cmd = [
        "uv",
        "tool",
        "run",
        "harbor",
        "run",
        "-d",
        dataset,
        "--agent-import-path",
        "harbor_generated_harness_agent:GeneratedHarnessAgent",
        "--jobs-dir",
        str(harbor_output_dir),
        "--n-concurrent",
        str(entry.get("threads", 1)),
        "--yes",
        "--ak",
        f"harness_path={artifact.path}",
        "--ak",
        f"domain={artifact.domain}",
        "--ak",
        f"task_work_dir={entry.get('task_work_dir', '/workspace')}",
        "--ak",
        f"timeout_sec={max(60, timeout - 60)}",
    ]
    n_limit = _limit_value(entry.get("n_limit"), default=1)
    if n_limit is not None:
        harbor_cmd.extend(["--n-tasks", str(n_limit)])
    for env_name in [
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "MODEL_NAME",
        "MODEL_ID",
        "API_KEY",
        "BASE_URL",
        "SEED2LITE_API_KEY",
        "SEED2LITE_BASE_URL",
        "SEED2LITE_MODEL_ID",
    ]:
        value = _container_env_value(env_name)
        if value:
            harbor_cmd.extend(["--ae", f"{env_name}={value}"])

    harbor = run_command(harbor_cmd, cwd=harness_eval_root, env=env, timeout=timeout)
    stdout_path.write_text(harbor.stdout, encoding="utf-8")
    stderr_path.write_text(harbor.stderr, encoding="utf-8")
    if harbor.returncode != 0:
        return HarnessRunResult(
            status="failed/timeout" if harbor.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=harbor.stderr[-2000:] or harbor.stdout[-2000:],
        )

    convert_code = (
        "from pathlib import Path; "
        "from benchmarks.terminalbench.run_infer import convert_harbor_to_eval_output; "
        f"convert_harbor_to_eval_output(Path({str(harbor_output_dir)!r}), Path({str(output_json)!r}))"
    )
    convert = run_command(["uv", "run", "python", "-c", convert_code], cwd=benchmarks_root, env=env, timeout=600)
    if convert.returncode != 0:
        stderr_path.write_text(harbor.stderr + "\n\n=== convert ===\n" + convert.stderr, encoding="utf-8")
        return HarnessRunResult(
            status="failed/timeout" if convert.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=convert.stderr[-2000:] or convert.stdout[-2000:],
        )

    eval_cmd = [
        "uv",
        "run",
        "terminalbench-eval",
        str(output_json),
        "--output-file",
        str(report_path),
    ]
    evaluate = run_command(eval_cmd, cwd=benchmarks_root, env=env, timeout=600)
    stdout_path.write_text(
        harbor.stdout + "\n\n=== convert ===\n" + convert.stdout + "\n\n=== terminalbench-eval ===\n" + evaluate.stdout,
        encoding="utf-8",
    )
    stderr_path.write_text(
        harbor.stderr + "\n\n=== convert ===\n" + convert.stderr + "\n\n=== terminalbench-eval ===\n" + evaluate.stderr,
        encoding="utf-8",
    )
    if evaluate.returncode != 0 and not report_path.exists():
        return HarnessRunResult(
            status="failed/timeout" if evaluate.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(output_json),
            error=evaluate.stderr[-2000:] or evaluate.stdout[-2000:],
        )
    parsed = _parse_benchmark_report(report_path)
    parsed.stdout_path = str(stdout_path)
    parsed.stderr_path = str(stderr_path)
    parsed.raw_result_path = str(report_path)
    return parsed


def run_eqbench3(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    harness_evolve_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    run_id = f"{output_dir.parent.parent.name}-{output_dir.name}"
    writing_root = harness_evolve_root / "writing_harness_eval"
    stdout_path = output_dir / "eqbench3_stdout.log"
    stderr_path = output_dir / "eqbench3_stderr.log"
    raw_run_file = writing_root / "outputs" / f"eqbench3_runs.{run_id}.json"
    csv_path = output_dir / "eqbench3_summary.csv"
    md_path = output_dir / "eqbench3_summary.md"

    if dry_run:
        return HarnessRunResult(
            status="skipped/dry_run",
            raw_result_path=str(raw_run_file),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    env = os.environ.copy()
    env.update(
        {
            "RUN_ID": run_id,
            "THREADS": str(entry.get("threads", 1)),
            "KIMI_WRITER_PATH": str(harness_eval_root / "generated_harness_cli.py"),
            "GENERATED_HARNESS_PATH": str(artifact.path),
            "GENERATED_HARNESS_DOMAIN": artifact.domain,
            "GENERATED_HARNESS_OUTPUT_DIR": str(output_dir / "harness_outputs"),
            "GENERATED_HARNESS_TIMEOUT": str(min(timeout, int(entry.get("harness_timeout", timeout)))),
            "HARNESS_EVAL_PYTHON": python_bin,
        }
    )
    scenarios = entry.get("default_subset", "1")
    eqbench_python = writing_root / ".venv" / "bin" / "python"
    python_for_eqbench = str(eqbench_python) if eqbench_python.exists() else python_bin
    eqbench_root = writing_root / "third_party" / "eqbench3"
    model_id = (
        env.get("MODEL_ID")
        or env.get("SEED2LITE_CODE_MODEL_ID")
        or env.get("SEED2LITE_MODEL_ID")
        or env.get("MODEL_NAME")
        or "generated-harness-model"
    )
    env.update(
        {
            "MOONSHOT_API_KEY": env.get("MOONSHOT_API_KEY") or env.get("SEED2LITE_API_KEY") or env.get("API_KEY", ""),
            "MOONSHOT_BASE_URL": env.get("MOONSHOT_BASE_URL") or env.get("SEED2LITE_BASE_URL") or env.get("BASE_URL", ""),
            "KIMI_WRITER_MODEL": env.get("KIMI_WRITER_MODEL") or model_id,
            "KIMI_WRITER_PYTHON": python_bin,
            "KIMI_WRITER_OUTPUT_DIR": str(writing_root / "outputs" / "kimi-writer"),
            "TEST_API_KEY": env.get("TEST_API_KEY") or env.get("SEED2LITE_API_KEY") or env.get("API_KEY", ""),
            "TEST_API_URL": env.get("TEST_API_URL") or env.get("SEED2LITE_CHAT_COMPLETIONS_URL_HTTP") or env.get("API_URL", ""),
            "JUDGE_API_KEY": env.get("JUDGE_API_KEY") or env.get("SEED2LITE_API_KEY") or env.get("API_KEY", ""),
            "JUDGE_API_URL": env.get("JUDGE_API_URL") or env.get("SEED2LITE_CHAT_COMPLETIONS_URL_HTTP") or env.get("API_URL", ""),
            "REQUEST_TIMEOUT": env.get("REQUEST_TIMEOUT", "300"),
            "MAX_RETRIES": env.get("MAX_RETRIES", "12"),
            "RETRY_DELAY": env.get("RETRY_DELAY", "30"),
            "RETRY_AFTER_CAP": env.get("RETRY_AFTER_CAP", "600"),
        }
    )
    eqbench_cmd = [
        python_for_eqbench,
        "eqbench3.py",
        "--test-model",
        model_id,
        "--judge-model",
        model_id,
        "--model-name",
        f"{model_id}-generated-writing-harness",
        "--run-id",
        run_id,
        "--runs-file",
        str(raw_run_file),
        "--elo-results-file",
        str(writing_root / "outputs" / f"eqbench3_elo.{run_id}.json"),
        "--threads",
        str(entry.get("threads", 1)),
        "--iterations",
        "1",
        "--no-elo",
        "--ignore-canonical",
        "--verbosity",
        "INFO",
    ]
    if not _is_all(scenarios):
        eqbench_cmd.extend(["--select-scenarios", str(scenarios)])
    cmd_result = run_command(
        eqbench_cmd,
        cwd=eqbench_root,
        env={**env, "USE_AGENT_FOR_TEST": "1"},
        timeout=timeout,
    )
    stdout_path.write_text(cmd_result.stdout, encoding="utf-8")
    stderr_path.write_text(cmd_result.stderr, encoding="utf-8")
    if cmd_result.returncode != 0:
        return HarnessRunResult(
            status="failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(raw_run_file),
            error=cmd_result.stderr[-1000:] or cmd_result.stdout[-1000:],
        )

    summarizer = writing_root / "scripts" / "summarize_eqbench_run.py"
    summarize = run_command(
        [
            os.environ.get("HARNESS_EVAL_PYTHON", "python3"),
            str(summarizer),
            str(raw_run_file),
            "--csv-out",
            str(csv_path),
            "--md-out",
            str(md_path),
        ],
        cwd=writing_root,
        env=env,
        timeout=300,
    )
    if summarize.returncode != 0:
        return HarnessRunResult(
            status="failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(raw_run_file),
            error=summarize.stderr[-1000:] or summarize.stdout[-1000:],
        )
    parsed = _parse_eqbench_csv(csv_path)
    parsed.stdout_path = str(stdout_path)
    parsed.stderr_path = str(stderr_path)
    return parsed


def run_browsecomp_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    responses_path = output_dir / "browsecomp_predictions.jsonl"
    report_path = output_dir / "browsecomp_report.json"
    stdout_path = output_dir / "browsecomp_stdout.log"
    stderr_path = output_dir / "browsecomp_stderr.log"
    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    import pandas as pd

    csv_url = str(
        entry.get("csv_url")
        or "https://openaipublic.blob.core.windows.net/simple-evals/browse_comp_test_set.csv"
    )
    local_candidates = [
        entry.get("csv_path"),
        os.environ.get("BROWSECOMP_CSV_PATH"),
        harness_eval_root / "external_benchmarks" / "simple-evals" / "browse_comp_test_set.csv",
        harness_eval_root / "external_benchmarks" / "simple-evals" / "browsecomp_test_set.csv",
    ]
    local_paths = [Path(str(item)).expanduser() for item in local_candidates if item]
    source_description = csv_url
    try:
        local_csv = next((path for path in local_paths if path.is_file()), None)
        if local_csv is not None:
            source_description = str(local_csv)
            df = pd.read_csv(local_csv)
        else:
            df = pd.read_csv(csv_url)
    except Exception as exc:  # noqa: BLE001 - report as missing dependency, not a fake score
        missing = [
            "BrowseComp official CSV is unavailable. "
            f"Tried remote URL {csv_url!r} and local cache paths: "
            + ", ".join(str(path) for path in local_paths)
            + f". Last error: {type(exc).__name__}: {exc}"
        ]
        write_json(
            report_path,
            {
                "status": "skipped/missing_dependency",
                "accuracy": None,
                "count": 0,
                "harness_failures": 0,
                "csv_url": csv_url,
                "local_cache_paths": [str(path) for path in local_paths],
                "missing_dependencies": missing,
            },
        )
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(missing[0] + "\n", encoding="utf-8")
        return HarnessRunResult(
            status="skipped/missing_dependency",
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            missing_dependencies=missing,
            error=missing[0],
        )
    browse_limit = _limit_value(entry.get("n_limit"), default=1)
    if browse_limit is not None:
        df = df.head(browse_limit)
    predictions: list[dict[str, Any]] = []
    correct_count = 0
    total_judge_tokens = 0
    harness_results: list[HarnessRunResult] = []
    harness_failures = 0
    for idx, row in df.iterrows():
        question = _decrypt_xor(str(row["problem"]), str(row["canary"]))
        answer = _decrypt_xor(str(row["answer"]), str(row["canary"]))
        prompt = (
            f"{question}\n\n"
            "Your response should include:\n"
            "Explanation: your evidence and reasoning\n"
            "Exact Answer: your succinct final answer\n"
            "Confidence: confidence between 0% and 100%"
        )
        result = run_agent_cli(
            artifact.path,
            "research",
            prompt,
            output_dir / "harness_outputs" / f"item_{idx}",
            python_bin=python_bin,
            timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
        )
        harness_results.append(result)
        response = _read_harness_response(result)
        if result.status != "success" or not response.strip():
            harness_failures += 1
            predictions.append(
                {
                    "question": question,
                    "answer": answer,
                    "prediction": response,
                    "correct": False,
                    "cli_status": result.status,
                    "harness_error": result.error,
                }
            )
            continue
        correct, detail = _judge_short_answer(question, answer, response, prefix="BROWSECOMP_JUDGE")
        total_judge_tokens += int((detail.get("usage") or {}).get("total_tokens") or 0)
        correct_count += int(correct)
        predictions.append({"question": question, "answer": answer, "prediction": response, "correct": correct, "judge": detail.get("judge")})
    write_jsonl(responses_path, predictions)
    accuracy = correct_count / len(predictions) if predictions and harness_failures == 0 else None
    write_json(
        report_path,
        {
            "accuracy": accuracy,
            "count": len(predictions),
            "harness_failures": harness_failures,
            "predictions_path": str(responses_path),
            "source": source_description,
        },
    )
    stdout_path.write_text("\n".join(r.stdout_path for r in harness_results), encoding="utf-8")
    stderr_path.write_text("\n".join(r.stderr_path for r in harness_results), encoding="utf-8")
    status = "success" if accuracy is not None else ("harness_failed" if harness_failures else "failed")
    harness_tokens, token_breakdown = _aggregate_harness_tokens(harness_results)
    return HarnessRunResult(
        status=status,
        score=accuracy,
        pass_rate=accuracy,
        raw_result_path=str(report_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        harness_run_tokens=harness_tokens,
        token_breakdown=token_breakdown,
        score_breakdown={
            "metric": "BrowseComp accuracy with encrypted official answer set",
            "items": len(predictions),
            "harness_failures": harness_failures,
            "judge_tokens": total_judge_tokens or None,
        },
        interactions=len(harness_results),
    )


def run_mlebench_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    mle_root = harness_eval_root / "external_benchmarks" / "mle-bench"
    competition_config = entry.get("competition_id", "spaceship-titanic")
    data_dir = Path(str(entry.get("data_dir") or os.environ.get("MLEBENCH_DATA_DIR") or Path.home() / ".cache" / "mle-bench" / "data")).expanduser()
    report_path = output_dir / "mlebench_report.json"
    stdout_path = output_dir / "mlebench_stdout.log"
    stderr_path = output_dir / "mlebench_stderr.log"
    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(mle_root) + os.pathsep + env.get("PYTHONPATH", "")
    if _is_all(competition_config):
        list_code = """
import json
from pathlib import Path
from mlebench.registry import registry
reg = registry.set_data_dir(Path(%r))
print(json.dumps(reg.list_competition_ids()))
""" % str(data_dir)
        listed = run_command([python_bin, "-c", list_code], cwd=mle_root, env=env, timeout=120)
        if listed.returncode != 0:
            return HarnessRunResult(
                status="skipped/missing_dependency",
                missing_dependencies=[listed.stderr[-1000:] or listed.stdout[-1000:]],
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
            )
        competition_ids = json.loads(listed.stdout.strip().splitlines()[-1])
        competition_ids = _limit_sequence(competition_ids, entry.get("n_limit"), default=None)
        child_results: list[dict[str, Any]] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        scores: list[float] = []
        missing_dependencies: list[str] = []
        total_interactions = 0
        child_token_usages: list[dict[str, Any]] = []
        for competition_id in competition_ids:
            child_entry = {**entry, "competition_id": competition_id}
            child_output = output_dir / "competitions" / str(competition_id)
            child_result = run_mlebench_generated(
                artifact,
                child_entry,
                child_output,
                harness_eval_root=harness_eval_root,
                python_bin=python_bin,
                timeout=timeout,
                dry_run=False,
            )
            total_interactions += child_result.interactions or 0
            child_usage = _result_token_usage(child_result)
            if child_usage or child_result.harness_run_tokens is not None:
                if child_result.harness_run_tokens is not None:
                    child_usage = {**(child_usage or {}), "total_tokens": child_result.harness_run_tokens}
                child_token_usages.append(child_usage)
            if child_result.stdout_path and Path(child_result.stdout_path).exists():
                stdout_parts.append(f"=== {competition_id} ===\n" + Path(child_result.stdout_path).read_text(encoding="utf-8", errors="replace"))
            if child_result.stderr_path and Path(child_result.stderr_path).exists():
                stderr_parts.append(f"=== {competition_id} ===\n" + Path(child_result.stderr_path).read_text(encoding="utf-8", errors="replace"))
            if child_result.score is not None:
                scores.append(float(child_result.score))
            missing_dependencies.extend(child_result.missing_dependencies or [])
            child_results.append(
                {
                    "competition_id": competition_id,
                    "status": child_result.status,
                    "score": child_result.score,
                    "raw_result_path": child_result.raw_result_path,
                    "harness_run_tokens": child_result.harness_run_tokens,
                    "missing_dependencies": child_result.missing_dependencies,
                    "error": child_result.error,
                }
            )
        report = {
            "competition_id": "all",
            "competitions_total": len(competition_ids),
            "scored_competitions": len(scores),
            "missing_or_failed_competitions": len(competition_ids) - len(scores),
            "score": statistics.mean(scores) if scores else None,
            "child_results": child_results,
        }
        write_json(report_path, report)
        stdout_path.write_text("\n\n".join(stdout_parts), encoding="utf-8")
        stderr_path.write_text("\n\n".join(stderr_parts), encoding="utf-8")
        status = "success" if scores else ("skipped/missing_dependency" if missing_dependencies else "failed")
        token_breakdown = merge_token_usages(child_token_usages)
        return HarnessRunResult(
            status=status,
            score=report["score"],
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            missing_dependencies=missing_dependencies[:50],
            score_breakdown={"metric": "MLE-bench mean grade_csv score over competitions", **report},
            harness_run_tokens=_token_total(token_breakdown),
            token_breakdown=token_breakdown,
            interactions=total_interactions,
        )

    competition_id = str(competition_config)
    check_code = f"""
import json
from pathlib import Path
from mlebench.registry import registry
from mlebench.data import is_dataset_prepared
reg = registry.set_data_dir(Path({str(data_dir)!r}))
competition = reg.get_competition({competition_id!r})
print(json.dumps({{
  "prepared": is_dataset_prepared(competition),
  "public_dir": str(competition.public_dir),
  "sample_submission": str(competition.sample_submission),
  "description": competition.description[:4000]
}}))
"""
    check = run_command([python_bin, "-c", check_code], cwd=mle_root, env=env, timeout=120)
    if check.returncode != 0:
        return HarnessRunResult(status="skipped/missing_dependency", missing_dependencies=[check.stderr[-1000:] or check.stdout[-1000:]], stdout_path=str(stdout_path), stderr_path=str(stderr_path))
    info = json.loads(check.stdout.strip().splitlines()[-1])
    if not info.get("prepared"):
        missing = [
            f"MLE-bench data not prepared for {competition_id}: run `cd {mle_root} && {python_bin} -m mlebench.cli prepare -c {competition_id} --data-dir {data_dir}`",
        ]
        if not (Path.home() / ".kaggle" / "kaggle.json").exists() and not os.environ.get("KAGGLE_USERNAME"):
            missing.append("Kaggle credential missing: ~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY")
        return HarnessRunResult(status="skipped/missing_dependency", missing_dependencies=missing, raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    task_workspace = output_dir / "mlebench_workspace"
    task_workspace.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"You are solving MLE-bench competition {competition_id}.\n"
        f"Competition description:\n{info.get('description', '')}\n\n"
        f"Public data directory: {info['public_dir']}\n"
        f"Sample submission: {info['sample_submission']}\n"
        f"Write your submission CSV into this output directory: {task_workspace}\n"
        "Submission requirements:\n"
        "- The official grader scores the submission CSV; follow the exact format the\n"
        "  competition description defines, not just the sample submission header.\n"
        "- Match the sample submission columns, row ids, and row order, and produce the\n"
        "  prediction value type the grader expects (string labels vs probabilities,\n"
        "  RLE-encoded mask strings, ordered id sequences, or free text).\n"
        "- Leave no missing or NaN cells.\n"
        "- If the metric is a correlation or rank statistic, constant predictions score\n"
        "  zero or NaN; produce varying predictions even when falling back to a baseline.\n"
        "- Validate the finished submission against these rules before finishing."
    )
    result = run_agent_cli(
        artifact.path,
        "data_analysis",
        prompt,
        output_dir / "harness_output",
        task_work_dir=Path(info["public_dir"]),
        python_bin=python_bin,
        timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
    )
    artifacts = read_json(Path(result.raw_result_path)).get("artifacts_dir") if result.raw_result_path else None
    csv_candidates = []
    for root in [Path(str(artifacts)) if artifacts else None, output_dir / "harness_output"]:
        if root and root.exists():
            csv_candidates.extend(path for path in root.rglob("*.csv") if path.is_file())
    if not csv_candidates:
        report = {
            "competition_id": competition_id,
            "score": 0.0,
            "submission_exists": False,
            "valid_submission": False,
            "failure_mode": "no_submission",
            "cli_status": result.status,
            "harness_error": result.error,
            "metric_source": "no_submission_zero_score",
        }
        write_json(report_path, report)
        stdout_path.write_text(
            (result.stdout_path and Path(result.stdout_path).read_text(encoding="utf-8", errors="replace") or "")
            + "\n\n=== grade ===\nNo submission CSV found; scored as 0.0.\n",
            encoding="utf-8",
        )
        stderr_path.write_text(
            (result.stderr_path and Path(result.stderr_path).read_text(encoding="utf-8", errors="replace") or ""),
            encoding="utf-8",
        )
        return HarnessRunResult(
            status="success",
            score=0.0,
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error="Generated harness did not produce a submission CSV",
            score_breakdown={"metric": "MLE-bench no-submission zero score", **report},
            harness_run_tokens=result.harness_run_tokens,
            token_breakdown=_result_token_usage(result),
            interactions=1,
        )
    submission = csv_candidates[0]
    grade_code = f"""
import json
from datetime import datetime
from pathlib import Path
from mlebench.registry import registry
from mlebench.grade import grade_csv
from mlebench.utils import load_answers, read_csv
reg = registry.set_data_dir(Path({str(data_dir)!r}))
competition = reg.get_competition({competition_id!r})
submission_path = Path({str(submission)!r})
try:
    report = grade_csv(submission_path, competition)
    payload = report.to_dict()
    payload["metric_source"] = "grade_csv"
except AssertionError as exc:
    # Some local MLE-bench registry snapshots have Kaggle leaderboard files
    # without a normalized `score` column. The actual competition metric can
    # still be computed from the private answers and official grader.
    if "Leaderboard must have a `score` column" not in str(exc):
        raise
    submission_df = read_csv(submission_path)
    answers = load_answers(competition.answers)
    score = competition.grader(submission_df, answers)
    payload = {{
        "competition_id": competition.id,
        "score": score,
        "submission_exists": submission_path.is_file(),
        "valid_submission": score is not None,
        "submission_path": str(submission_path),
        "metric_source": "competition_grader",
        "rank_unavailable_reason": str(exc),
        "created_at": datetime.now(),
    }}
print(json.dumps(payload, default=str))
"""
    grade = run_command([python_bin, "-c", grade_code], cwd=mle_root, env=env, timeout=timeout)
    stdout_path.write_text((result.stdout_path and Path(result.stdout_path).read_text(encoding="utf-8", errors="replace") or "") + "\n\n=== grade ===\n" + grade.stdout, encoding="utf-8")
    stderr_path.write_text((result.stderr_path and Path(result.stderr_path).read_text(encoding="utf-8", errors="replace") or "") + "\n\n=== grade ===\n" + grade.stderr, encoding="utf-8")
    if grade.returncode != 0:
        return HarnessRunResult(status="failed/timeout" if grade.returncode == 124 else "failed", raw_result_path=str(submission), stdout_path=str(stdout_path), stderr_path=str(stderr_path), error=grade.stderr[-2000:] or grade.stdout[-2000:])
    report = json.loads(grade.stdout.strip().splitlines()[-1])
    write_json(report_path, report)
    score = report.get("score")
    try:
        score_float = float(score)
    except (TypeError, ValueError):
        score_float = None
    return HarnessRunResult(
        status="success",
        score=score_float,
        raw_result_path=str(report_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        score_breakdown={"metric": "MLE-bench grade_csv score", "competition_id": competition_id, **report},
        harness_run_tokens=result.harness_run_tokens,
        token_breakdown=_result_token_usage(result),
        interactions=1,
    )


def run_the_agent_company_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    task_image = str(entry.get("task_image_name") or "ghcr.io/theagentcompany/admin-arrange-meeting-rooms-image:1.0.0")
    server_hostname = str(os.environ.get("TAC_SERVER_HOSTNAME") or entry.get("server_hostname") or "host.docker.internal")
    health_url = str(os.environ.get("TAC_SERVICE_HEALTH_URL") or entry.get("service_health_url") or "http://localhost:2999/api/healthcheck/rocketchat")
    stdout_path = output_dir / "the_agent_company_stdout.log"
    stderr_path = output_dir / "the_agent_company_stderr.log"
    eval_result_path = output_dir / "the_agent_company_eval.json"
    report_path = output_dir / "the_agent_company_report.json"
    workspace_dir = output_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    if _is_all(task_image):
        task_images: list[str] = []
        configured_images = entry.get("task_images")
        if isinstance(configured_images, list):
            task_images = [str(item).strip() for item in configured_images if str(item).strip()]
        if not task_images or (len(task_images) == 1 and _is_all(task_images[0])):
            tasks_url = str(entry.get("task_images_url") or "https://github.com/TheAgentCompany/TheAgentCompany/releases/download/1.0.0/tasks.md")
            try:
                with urllib.request.urlopen(tasks_url, timeout=60) as response:
                    tasks_text = response.read().decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001 - surface dependency failure
                missing = [f"TheAgentCompany task list is unavailable at {tasks_url}: {type(exc).__name__}: {exc}"]
                return HarnessRunResult(
                    status="skipped/missing_dependency",
                    missing_dependencies=missing,
                    raw_result_path=str(report_path),
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error=missing[0],
                )
            task_images = re.findall(r"ghcr\.io/theagentcompany/[^\s`]+", tasks_text)
        task_images = _limit_sequence(task_images, entry.get("n_limit"), default=None)
        child_results: list[dict[str, Any]] = []
        scores: list[float] = []
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        missing_dependencies: list[str] = []
        child_token_usages: list[dict[str, Any]] = []
        for image in task_images:
            task_name = image.split("/")[-1].split(":")[0].replace("-image", "")
            child_entry = {**entry, "task_image_name": image}
            child_output = output_dir / "tasks" / task_name
            child_result = run_the_agent_company_generated(
                artifact,
                child_entry,
                child_output,
                harness_eval_root=harness_eval_root,
                python_bin=python_bin,
                timeout=timeout,
                dry_run=False,
            )
            if child_result.stdout_path and Path(child_result.stdout_path).exists():
                stdout_parts.append(f"=== {image} ===\n" + Path(child_result.stdout_path).read_text(encoding="utf-8", errors="replace"))
            if child_result.stderr_path and Path(child_result.stderr_path).exists():
                stderr_parts.append(f"=== {image} ===\n" + Path(child_result.stderr_path).read_text(encoding="utf-8", errors="replace"))
            if child_result.score is not None:
                scores.append(float(child_result.score))
            child_usage = _result_token_usage(child_result)
            if child_usage or child_result.harness_run_tokens is not None:
                if child_result.harness_run_tokens is not None:
                    child_usage = {**(child_usage or {}), "total_tokens": child_result.harness_run_tokens}
                child_token_usages.append(child_usage)
            missing_dependencies.extend(child_result.missing_dependencies or [])
            child_results.append(
                {
                    "task_image": image,
                    "status": child_result.status,
                    "score": child_result.score,
                    "harness_run_tokens": child_result.harness_run_tokens,
                    "raw_result_path": child_result.raw_result_path,
                    "missing_dependencies": child_result.missing_dependencies,
                    "error": child_result.error,
                }
            )
        report = {
            "task_image": "all",
            "tasks_total": len(task_images),
            "scored_tasks": len(scores),
            "missing_or_failed_tasks": len(task_images) - len(scores),
            "score": statistics.mean(scores) if scores else None,
            "child_results": child_results,
        }
        write_json(report_path, report)
        stdout_path.write_text("\n\n".join(stdout_parts), encoding="utf-8")
        stderr_path.write_text("\n\n".join(stderr_parts), encoding="utf-8")
        status = "success" if scores else ("skipped/missing_dependency" if missing_dependencies else "failed")
        token_breakdown = merge_token_usages(child_token_usages)
        return HarnessRunResult(
            status=status,
            score=report["score"],
            pass_rate=report["score"],
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            missing_dependencies=missing_dependencies[:50],
            score_breakdown={"metric": "TheAgentCompany mean final_score.result / total over task images", **report},
            harness_run_tokens=_token_total(token_breakdown),
            token_breakdown=token_breakdown,
            interactions=len(task_images),
        )

    healthy, health_detail = _http_head_ok(health_url)
    if not healthy and "localhost:2999" in health_url:
        shim_log = output_dir / "tac_api_shim.log"
        shim_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = shim_log.open("a", encoding="utf-8")
        subprocess.Popen(
            [
                python_bin,
                str(harness_eval_root / "tools" / "tac_api_shim.py"),
                "--host",
                "0.0.0.0",
                "--port",
                "2999",
            ],
            cwd=harness_eval_root,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(1.5)
        healthy, health_detail = _http_head_ok(health_url)
    if not healthy:
        return HarnessRunResult(
            status="skipped/missing_dependency",
            missing_dependencies=[
                f"TheAgentCompany service stack is not reachable at {health_url}: {health_detail}",
                "Start the official service stack first: `curl -fsSL https://github.com/TheAgentCompany/the-agent-company-backup-data/releases/download/setup-script-20241208/setup.sh | sh`",
                "Docker Desktop on macOS must have host networking enabled for the official stack.",
            ],
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    docker_base = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{workspace_dir.resolve()}:/workspace",
        "-v",
        f"{output_dir.resolve()}:/outputs",
        "-e",
        f"SERVER_HOSTNAME={server_hostname}",
        "-e",
        f"LITELLM_API_KEY={os.environ.get('OPENAI_API_KEY') or os.environ.get('API_KEY') or 'proxy-placeholder'}",
        "-e",
        f"LITELLM_BASE_URL={os.environ.get('OPENAI_BASE_URL') or os.environ.get('BASE_URL') or 'http://127.0.0.1:1/v1'}",
        "-e",
        f"LITELLM_MODEL={os.environ.get('MODEL_NAME') or os.environ.get('OPENAI_MODEL') or 'generated-harness'}",
        task_image,
    ]

    task = run_command(
        docker_base + ["bash", "-lc", "cat /instruction/task.md && echo '\n---DEPENDENCIES---' && cat /utils/dependencies.yml"],
        cwd=output_dir,
        timeout=180,
    )
    if task.returncode != 0:
        stdout_path.write_text(task.stdout, encoding="utf-8")
        stderr_path.write_text(task.stderr, encoding="utf-8")
        return HarnessRunResult(
            status="failed",
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=task.stderr[-2000:] or task.stdout[-2000:],
        )
    task_text, _, deps_text = task.stdout.partition("\n---DEPENDENCIES---\n")
    (workspace_dir / "task.md").write_text(task_text, encoding="utf-8")

    init = run_command(docker_base + ["bash", "-lc", "bash /utils/init.sh"], cwd=output_dir, timeout=min(timeout, 1800))
    if init.returncode != 0:
        stdout_path.write_text(task.stdout + "\n\n=== init ===\n" + init.stdout, encoding="utf-8")
        stderr_path.write_text(task.stderr + "\n\n=== init ===\n" + init.stderr, encoding="utf-8")
        return HarnessRunResult(
            status="failed/timeout" if init.returncode == 124 else "failed",
            raw_result_path=str(report_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=init.stderr[-2000:] or init.stdout[-2000:],
            score_breakdown={"stage": "init", "task_image": task_image, "dependencies": deps_text.strip()},
        )

    browser_prompt = (
        "You are running a real TheAgentCompany browser task. Complete the task using the live local services.\n\n"
        f"Task image: {task_image}\n"
        f"Service hostname inside task containers: {server_hostname}\n"
        "For browser access from this host, prefer these URLs when applicable:\n"
        "- RocketChat: http://localhost:3000/  (username: theagentcompany, password: theagentcompany)\n"
        "- GitLab: http://localhost:8929/  (username: root, password: theagentcompany)\n"
        "- ownCloud: http://localhost:8092/  (username: theagentcompany, password: theagentcompany)\n"
        "- Plane: http://localhost:8091/\n\n"
        f"Workspace directory for required files: {workspace_dir.resolve()}\n"
        "If the task asks you to write /workspace/ans.txt, write the answer to the host file "
        f"{(workspace_dir / 'ans.txt').resolve()}.\n\n"
        "Original task:\n"
        f"{task_text.strip()}\n"
    )
    harness_result = run_agent_cli(
        artifact.path,
        "browser",
        browser_prompt,
        output_dir / "harness_outputs" / "the_agent_company",
        task_work_dir=workspace_dir,
        python_bin=python_bin,
        timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
    )
    trajectory_path = output_dir / "generated_trajectory.txt"
    trajectory_bits = {
        "cli_status": harness_result.status,
        "harness_error": harness_result.error,
        "raw_result_path": harness_result.raw_result_path,
        "stdout_path": harness_result.stdout_path,
        "stderr_path": harness_result.stderr_path,
        "response": _read_harness_response(harness_result),
    }
    trajectory_path.write_text(json.dumps(trajectory_bits, ensure_ascii=False, indent=2), encoding="utf-8")

    eval_cmd = docker_base + [
        "bash",
        "-lc",
        "DECRYPTION_KEY='theagentcompany is all you need' "
        "python /utils/eval.py --trajectory_path /outputs/generated_trajectory.txt "
        "--result_path /outputs/the_agent_company_eval.json",
    ]
    evaluate = run_command(eval_cmd, cwd=output_dir, timeout=min(timeout, 900))
    stdout_path.write_text(
        task.stdout
        + "\n\n=== init ===\n"
        + init.stdout
        + "\n\n=== harness ===\n"
        + (Path(harness_result.stdout_path).read_text(encoding="utf-8", errors="replace") if harness_result.stdout_path and Path(harness_result.stdout_path).exists() else "")
        + "\n\n=== evaluator ===\n"
        + evaluate.stdout,
        encoding="utf-8",
    )
    stderr_path.write_text(
        task.stderr
        + "\n\n=== init ===\n"
        + init.stderr
        + "\n\n=== harness ===\n"
        + (Path(harness_result.stderr_path).read_text(encoding="utf-8", errors="replace") if harness_result.stderr_path and Path(harness_result.stderr_path).exists() else "")
        + "\n\n=== evaluator ===\n"
        + evaluate.stderr,
        encoding="utf-8",
    )
    if evaluate.returncode != 0:
        return HarnessRunResult(
            status="failed/timeout" if evaluate.returncode == 124 else "failed",
            raw_result_path=str(eval_result_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=evaluate.stderr[-2000:] or evaluate.stdout[-2000:],
            score_breakdown={"stage": "evaluator", "task_image": task_image, "cli_status": harness_result.status},
            harness_run_tokens=harness_result.harness_run_tokens,
            token_breakdown=_result_token_usage(harness_result),
            interactions=1,
        )
    result = read_json(eval_result_path) if eval_result_path.exists() else {}
    final = result.get("final_score") or {}
    total = final.get("total")
    got = final.get("result")
    try:
        score = float(got) / float(total) if total else None
    except (TypeError, ValueError, ZeroDivisionError):
        score = None
    write_json(
        report_path,
        {
            "task_image": task_image,
            "dependencies": deps_text.strip(),
            "cli_status": harness_result.status,
            "score": score,
            "raw_eval": result,
        },
    )
    return HarnessRunResult(
        status="success" if score is not None else "failed",
        score=score,
        pass_rate=score,
        raw_result_path=str(report_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        score_breakdown={"metric": "TheAgentCompany final_score.result / total", "task_image": task_image, **final},
        harness_run_tokens=harness_result.harness_run_tokens,
        token_breakdown=_result_token_usage(harness_result),
        interactions=1,
    )


def run_proxy_smoke(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    python_bin: str,
    timeout: int,
) -> HarnessRunResult:
    prompt = str(entry.get("proxy_prompt") or entry.get("name") or artifact.task_id)
    result = run_agent_cli(
        artifact.path,
        artifact.domain,
        prompt,
        output_dir / "proxy_smoke",
        python_bin=python_bin,
        timeout=timeout,
    )
    result.status = "proxy_smoke_" + result.status
    result.score_breakdown["not_downstream_bmk"] = True
    result.score_breakdown["benchmark_requested"] = entry.get("name")
    return result


def run_benchmark(
    artifact: HarnessArtifact,
    validation: ValidationResult,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    harness_evolve_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
    proxy_smoke_for_unsupported: bool,
) -> HarnessRunResult:
    missing = dependency_errors(entry, harness_eval_root=harness_eval_root, harness_evolve_root=harness_evolve_root)
    if missing:
        return HarnessRunResult(status="skipped/missing_dependency", missing_dependencies=missing)

    if not validation.runnable:
        return HarnessRunResult(
            status="skipped/invalid_harness",
            missing_dependencies=validation.missing_dependencies,
            error="Generated harness failed validation",
        )

    runner = str(entry.get("runner", "unsupported"))
    if runner == "swebench_generated":
        return run_swebench_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            harness_evolve_root=harness_evolve_root,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "terminalbench_generated":
        return run_terminalbench_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            harness_evolve_root=harness_evolve_root,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "eqbench3":
        return run_eqbench3(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            harness_evolve_root=harness_evolve_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "browsecomp_generated":
        return run_browsecomp_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "mlebench_generated":
        return run_mlebench_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "the_agent_company_generated":
        return run_the_agent_company_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )

    if runner == "unsupported":
        if proxy_smoke_for_unsupported and not dry_run:
            return run_proxy_smoke(artifact, entry, output_dir, python_bin=python_bin, timeout=timeout)
        reason = str(entry.get("unsupported_reason") or "No generated-harness CLI runner is implemented for this benchmark yet")
        return HarnessRunResult(
            status="skipped/unsupported_harness_cli",
            missing_dependencies=[reason],
            score_breakdown={"runner": runner},
        )

    return HarnessRunResult(
        status="skipped/unknown_runner",
        missing_dependencies=[f"runner: {runner}"],
    )


def base_row(
    artifact: HarnessArtifact,
    validation: ValidationResult,
    entry: dict[str, Any],
    result: HarnessRunResult,
) -> dict[str, Any]:
    end_to_end_score = result.score
    result = _apply_result_token_fallback(result)
    harness_tokens = result.tokens if result.tokens is not None else result.harness_run_tokens
    return {
        "generation_model": artifact.generation_model,
        "eval_model": validation.meta.get("eval_model") or "",
        "eval_model_input": validation.meta.get("eval_model_input") or "",
        "eval_reasoning_effort": validation.meta.get("eval_reasoning_effort") or "",
        "creation_profile": validation.creation_profile,
        "domain": artifact.domain,
        "harness_task_id": artifact.task_id,
        "harness_path": str(artifact.path),
        "benchmark": entry.get("name", entry.get("id", "")),
        "benchmark_id": entry.get("id", ""),
        "generation_status": validation.generation_status,
        "creation_attempts": validation.creation_attempts,
        "syntax_ok": validation.syntax_ok,
        "import_ok": validation.import_ok,
        "cli_probe_ok": validation.cli_probe_ok,
        "cli_status": validation.cli_status,
        "harness_invocation": "python -m harness run",
        "eval_status": result.status,
        "score": result.score,
        "end_to_end_score": end_to_end_score,
        "score_breakdown": result.score_breakdown,
        "pass_rate": result.pass_rate,
        "win_rate": result.win_rate,
        "reward": result.reward,
        "harness_run_tokens": harness_tokens,
        "harness_run_token_breakdown": result.token_breakdown,
        "harness_run_interactions": result.interactions,
        "generation_tokens": validation.generation_tokens,
        "missing_dependencies": result.missing_dependencies or validation.missing_dependencies,
        "stdout_path": result.stdout_path or validation.stdout_path,
        "stderr_path": result.stderr_path or validation.stderr_path,
        "raw_result_path": result.raw_result_path or validation.raw_result_path,
    }
