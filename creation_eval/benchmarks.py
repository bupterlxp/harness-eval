from __future__ import annotations

import csv
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import statistics
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .adapter import run_generated_harness
from .schema import HarnessArtifact, HarnessRunResult, ValidationResult
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


def _parse_eqbench_csv(csv_path: Path) -> HarnessRunResult:
    if not csv_path.exists():
        return HarnessRunResult(status="failed", error=f"Missing EQ-Bench summary CSV: {csv_path}")
    rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8")))
    scored = [row for row in rows if row.get("score_100")]
    avg_score = _avg_float([row.get("score_100", "") for row in scored])
    total_tokens = _avg_float([row.get("agent_total_tokens", "") for row in rows])
    interactions = _avg_float([row.get("agent_invocations", "") for row in rows])
    pass_rate = len(scored) / len(rows) if rows else None
    return HarnessRunResult(
        status="success" if scored else "failed",
        score=avg_score,
        pass_rate=pass_rate,
        harness_run_tokens=int(total_tokens) if total_tokens is not None else None,
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
    if isinstance(prompt_tokens, int) or isinstance(completion_tokens, int):
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    return HarnessRunResult(
        status="success" if submitted else "failed",
        score=pass_rate,
        pass_rate=pass_rate,
        harness_run_tokens=total_tokens,
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
    env["GENERATED_HARNESS_ADAPTER"] = str(harness_eval_root / "generated_harness_adapter.py")
    env["GENERATED_HARNESS_TIMEOUT"] = str(timeout)
    env["PYTHONPATH"] = str(harness_eval_root) + os.pathsep + env.get("PYTHONPATH", "")
    for name in ["OPENAI_BASE_URL", "BASE_URL", "OPENAI_API_KEY", "API_KEY"]:
        container_value = os.environ.get(f"CONTAINER_{name}")
        if container_value:
            env[name] = container_value
    return env


def _container_env_value(name: str) -> str | None:
    return os.environ.get(f"CONTAINER_{name}") or os.environ.get(name)


def _read_adapter_response(result: HarnessRunResult) -> str:
    raw = read_json(Path(result.raw_result_path)) if result.raw_result_path else {}
    selected_file = raw.get("selected_file")
    if selected_file and Path(str(selected_file)).exists():
        return Path(str(selected_file)).read_text(encoding="utf-8", errors="replace")
    if result.stdout_path and Path(result.stdout_path).exists():
        return Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    return ""


def _http_head_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 400, f"http_status={response.status}"
    except urllib.error.HTTPError as exc:
        return 200 <= int(exc.code) < 400, f"http_status={exc.code}"
    except Exception as exc:  # noqa: BLE001 - dependency probe result is surfaced
        return False, f"{type(exc).__name__}: {exc}"


def _load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
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
        if response.status_code != 429:
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


def _export_sqlite_tables(sqlite_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    with sqlite3.connect(sqlite_path) as conn:
        table_rows = conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        ).fetchall()
        for (table_name,) in table_rows:
            target = output_dir / f"{table_name}.csv"
            cursor = conn.execute(f'SELECT * FROM "{table_name}"')
            columns = [desc[0] for desc in cursor.description or []]
            with target.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(cursor.fetchall())
            exported.append(target)
    return exported


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
    n_limit = str(entry.get("n_limit", 1))
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
        "--n-limit",
        n_limit,
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
    if evaluate.returncode != 0:
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
        "--n-tasks",
        str(entry.get("n_limit", 1)),
        "--yes",
        "--ak",
        f"harness_path={artifact.path}",
        "--ak",
        f"adapter_path={harness_eval_root / 'generated_harness_adapter.py'}",
        "--ak",
        f"domain={artifact.domain}",
        "--ak",
        f"task_work_dir={entry.get('task_work_dir', '/workspace')}",
        "--ak",
        f"timeout_sec={max(60, timeout - 60)}",
    ]
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
    if evaluate.returncode != 0:
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
            "KIMI_WRITER_PATH": str(harness_eval_root / "generated_harness_adapter.py"),
            "GENERATED_HARNESS_PATH": str(artifact.path),
            "GENERATED_HARNESS_DOMAIN": artifact.domain,
            "GENERATED_HARNESS_ADAPTER_OUTPUT_DIR": str(output_dir / "adapter_outputs"),
            "HARNESS_EVAL_PYTHON": python_bin,
        }
    )
    scenarios = str(entry.get("default_subset", "1"))
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
    cmd_result = run_command(
        [
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
            "--select-scenarios",
            scenarios,
            "--threads",
            str(entry.get("threads", 1)),
            "--iterations",
            "1",
            "--no-elo",
            "--ignore-canonical",
            "--verbosity",
            "INFO",
        ],
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


def run_dacomp_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_evolve_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    run_id = output_dir.name
    dacomp_root = harness_evolve_root / "harness_house" / "DAComp"
    eval_root = dacomp_root / "dacomp-da" / "evaluation_suite"
    task_file = dacomp_root / "dacomp-da" / "tasks" / "dacomp-da.jsonl"
    stdout_path = output_dir / "dacomp_stdout.log"
    stderr_path = output_dir / "dacomp_stderr.log"
    score_dir = output_dir / "model_scores"
    model_dir = output_dir / "agent_results" / f"generated-harness-{run_id}"

    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(score_dir), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    task_ids = entry.get("task_ids") or ["dacomp-001"]
    if isinstance(task_ids, str):
        task_ids = [item.strip() for item in task_ids.split(",") if item.strip()]
    tasks = [task for task in _load_jsonl(task_file) if task.get("instance_id") in set(task_ids)]
    if not tasks:
        return HarnessRunResult(status="failed", error=f"No DAComp tasks selected from {task_file}: {task_ids}")

    env = os.environ.copy()
    env["SEED2LITE_API_KEY"] = env.get("SEED2LITE_API_KEY", env.get("API_KEY", ""))
    env["SEED2LITE_BASE_URL"] = env.get("SEED2LITE_BASE_URL", env.get("BASE_URL", "http://ark-cn-beijing.bytedance.net/api/v3"))
    env["SEED2LITE_CHAT_COMPLETIONS_URL_HTTP"] = env.get(
        "SEED2LITE_CHAT_COMPLETIONS_URL_HTTP",
        env["SEED2LITE_BASE_URL"].rstrip("/") + "/chat/completions",
    )
    env["API_URL"] = env["SEED2LITE_CHAT_COMPLETIONS_URL_HTTP"]
    env["AUTH_TOKEN"] = env["SEED2LITE_API_KEY"]
    env["PYTHONPATH"] = str(eval_root) + os.pathsep + env.get("PYTHONPATH", "")
    judge_model = str(entry.get("judge_model") or env.get("DACOMP_JUDGE_MODEL_CONFIG") or "ep-20260214145701-frz7j")

    adapter_results: list[HarnessRunResult] = []
    for task in tasks:
        instance_id = str(task["instance_id"])
        task_workspace = output_dir / "task_workspaces" / instance_id
        task_workspace.mkdir(parents=True, exist_ok=True)
        sqlite_src = dacomp_root / "dacomp-da" / "tasks" / instance_id / f"{instance_id}.sqlite"
        table_summary = "No sqlite task data was found."
        if sqlite_src.exists():
            sqlite_dst = task_workspace / sqlite_src.name
            shutil.copy2(sqlite_src, sqlite_dst)
            exported = _export_sqlite_tables(sqlite_dst, task_workspace)
            table_summary = "Exported sqlite tables:\n" + "\n".join(f"- {path.name}" for path in exported)
        prompt = (
            f"You are solving DAComp data-analysis task {instance_id}.\n"
            f"Instruction:\n{task.get('instruction', '')}\n\n"
            f"Task data directory: {task_workspace}\n{table_summary}\n\n"
            "Produce a complete English markdown report with quantitative analysis, conclusions, and any referenced chart files."
        )
        adapter_result = run_generated_harness(
            artifact.path,
            "data_analysis",
            prompt,
            output_dir / "adapter_outputs" / instance_id,
            task_work_dir=task_workspace,
            python_bin=python_bin,
            timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
        )
        adapter_results.append(adapter_result)
        response = _read_adapter_response(adapter_result)
        instance_dir = model_dir / instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        (instance_dir / f"{instance_id}.md").write_text(response, encoding="utf-8")
        (instance_dir / f"{instance_id}-traj.txt").write_text(
            json.dumps(
                {
                    "adapter_status": adapter_result.status,
                    "raw_result_path": adapter_result.raw_result_path,
                    "stdout_path": adapter_result.stdout_path,
                    "stderr_path": adapter_result.stderr_path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    judge_timeout = int(entry.get("judge_timeout", min(timeout, 240)))
    judge = run_command(
        [
            python_bin,
            "llm_judge.py",
            "--rubrics-model",
            judge_model,
            "--gsb-model-text",
            judge_model,
            "--gsb-model-vis",
            judge_model,
            "--inputs",
            str(model_dir),
            "--output-dir",
            str(score_dir),
            "--max-workers",
            str(entry.get("threads", 1)),
            "--language",
            "en",
        ],
        cwd=eval_root,
        env=env,
        timeout=judge_timeout,
    )
    score_csvs = [
        path
        for path in score_dir.glob("*.csv")
        if path.name != "overall_results.csv"
    ]
    if judge.returncode != 0 and not score_csvs:
        stdout_path.write_text("\n\n=== adapter ===\n" + "\n".join(r.stdout_path for r in adapter_results) + "\n\n=== judge ===\n" + judge.stdout, encoding="utf-8")
        stderr_path.write_text("\n\n=== judge ===\n" + judge.stderr, encoding="utf-8")
        return HarnessRunResult(
            status="failed/timeout" if judge.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(score_dir),
            error=(judge.stderr or judge.stdout)[-2000:],
        )
    score = run_command(
        [python_bin, "get_score.py", "--scores-dir", str(score_dir), "--src-dir", "src"],
        cwd=eval_root,
        env=env,
        timeout=600,
    )
    stdout_path.write_text("\n\n=== adapter ===\n" + "\n".join(r.stdout_path for r in adapter_results) + "\n\n=== judge ===\n" + judge.stdout + "\n\n=== score ===\n" + score.stdout, encoding="utf-8")
    stderr_path.write_text("\n\n=== judge ===\n" + judge.stderr + "\n\n=== score ===\n" + score.stderr, encoding="utf-8")
    if score.returncode != 0:
        return HarnessRunResult(
            status="failed/timeout" if score.returncode == 124 else "failed",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            raw_result_path=str(score_dir),
            error=(score.stderr or score.stdout or judge.stderr or judge.stdout)[-2000:],
        )

    overall = score_dir / "overall_results.csv"
    rows = list(csv.DictReader(overall.open("r", encoding="utf-8"))) if overall.exists() else []
    total = None
    breakdown: dict[str, Any] = {"tasks": [task["instance_id"] for task in tasks], "metric": "DAComp weighted total"}
    if rows:
        row = rows[0]
        breakdown.update(row)
        try:
            total = float(row.get("total") or "")
        except ValueError:
            total = None
    return HarnessRunResult(
        status="success" if total is not None else "failed",
        score=total,
        raw_result_path=str(overall if overall.exists() else score_dir),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        score_breakdown=breakdown,
        interactions=len(adapter_results),
    )


def run_writingbench_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_eval_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    bench_root = harness_eval_root / "external_benchmarks" / "WritingBench"
    query_file = bench_root / "benchmark_query" / "benchmark_all.jsonl"
    responses_path = output_dir / "writingbench_responses.jsonl"
    scores_path = output_dir / "writingbench_scores.jsonl"
    stdout_path = output_dir / "writingbench_stdout.log"
    stderr_path = output_dir / "writingbench_stderr.log"
    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(responses_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    all_rows = _load_jsonl(query_file)
    lang = str(entry.get("lang", "en"))
    selected = [row for row in all_rows if row.get("lang") == lang][: int(entry.get("n_limit", 1))]
    if not selected:
        selected = all_rows[: int(entry.get("n_limit", 1))]
    adapter_results: list[HarnessRunResult] = []
    response_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    total_judge_tokens = 0
    for row in selected:
        result = run_generated_harness(
            artifact.path,
            "writing",
            str(row["query"]),
            output_dir / "adapter_outputs" / f"index_{row['index']}",
            python_bin=python_bin,
            timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
        )
        adapter_results.append(result)
        response = _read_adapter_response(result)
        response_rows.append({"index": row["index"], "response": response, "adapter_status": result.status})
        criteria_scores: dict[str, list[dict[str, Any]]] = {}
        for criteria in row.get("checklist", [])[: int(entry.get("criteria_limit", 5))]:
            prompt = f"""You are an expert evaluator with extensive experience in evaluating responses to writing queries.

Evaluate the Response based on the Query and Criteria. Assign an integer score from 1 to 10 and provide a concrete reason.

Return only JSON:
{{"score": 1, "reason": "specific reason"}}

Criteria:
{json.dumps(criteria, ensure_ascii=False)}

Query:
{row["query"]}

Response:
{response}
"""
            content, usage = _call_chat(prompt, prefix="WRITINGBENCH_JUDGE", max_tokens=2048, temperature=0)
            total_judge_tokens += int((usage or {}).get("total_tokens") or 0)
            parsed = _extract_json_object(content) or {"score": None, "reason": content}
            criteria_scores.setdefault(str(criteria.get("name", "criteria")), []).append(parsed)
        score_rows.append({"index": row["index"], "scores": criteria_scores})
    write_jsonl(responses_path, response_rows)
    write_jsonl(scores_path, score_rows)
    stdout_path.write_text("\n".join(r.stdout_path for r in adapter_results), encoding="utf-8")
    stderr_path.write_text("\n".join(r.stderr_path for r in adapter_results), encoding="utf-8")
    numeric_scores: list[float] = []
    for score_row in score_rows:
        for entries in score_row["scores"].values():
            for item in entries:
                try:
                    numeric_scores.append(float(item.get("score")))
                except (TypeError, ValueError):
                    continue
    score = statistics.mean(numeric_scores) * 10 if numeric_scores else None
    return HarnessRunResult(
        status="success" if score is not None else "failed",
        score=score,
        pass_rate=sum(1 for value in numeric_scores if value >= 7) / len(numeric_scores) if numeric_scores else None,
        raw_result_path=str(scores_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        harness_run_tokens=total_judge_tokens or None,
        score_breakdown={"metric": "WritingBench average criterion score x10", "queries": len(selected), "criterion_scores": len(numeric_scores)},
        interactions=len(adapter_results),
    )


def run_deepresearch_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
    harness_evolve_root: Path,
    python_bin: str,
    timeout: int,
    dry_run: bool,
) -> HarnessRunResult:
    data_path = harness_evolve_root / "harness_house" / "DeepResearch" / "DeepResearch" / "eval_data" / "hle_test.jsonl"
    pred_path = output_dir / "deepresearch_predictions.jsonl"
    details_path = output_dir / "deepresearch_eval_details.jsonl"
    report_path = output_dir / "deepresearch_report.json"
    stdout_path = output_dir / "deepresearch_stdout.log"
    stderr_path = output_dir / "deepresearch_stderr.log"
    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    all_rows = _load_jsonl(data_path)
    rows = [
        row
        for row in all_rows
        if "Uploaded " not in str(row.get("question", ""))
        and not re.search(r"\.(jpg|jpeg|png|webp|gif)\b", str(row.get("question", "")), re.IGNORECASE)
    ][: int(entry.get("n_limit", 1))]
    predictions: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    adapter_results: list[HarnessRunResult] = []
    adapter_failures = 0
    correct_count = 0
    total_judge_tokens = 0
    for idx, row in enumerate(rows):
        result = run_generated_harness(
            artifact.path,
            "research",
            str(row["question"]),
            output_dir / "adapter_outputs" / f"item_{idx}",
            python_bin=python_bin,
            timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
        )
        adapter_results.append(result)
        response = _read_adapter_response(result)
        if result.status != "success" or not response.strip():
            adapter_failures += 1
            predictions.append({"question": row["question"], "answer": row.get("answer", ""), "prediction": response, "adapter_status": result.status})
            details.append(
                {
                    "question": row["question"],
                    "answer": row.get("answer", ""),
                    "prediction": response,
                    "correct": False,
                    "adapter_status": result.status,
                    "adapter_error": result.error,
                }
            )
            continue
        correct, detail = _judge_short_answer(str(row["question"]), str(row.get("answer", "")), response, prefix="DEEPRESEARCH_JUDGE")
        total_judge_tokens += int((detail.get("usage") or {}).get("total_tokens") or 0)
        correct_count += int(correct)
        predictions.append({"question": row["question"], "answer": row.get("answer", ""), "prediction": response, "adapter_status": result.status})
        details.append({"question": row["question"], "answer": row.get("answer", ""), "prediction": response, "correct": correct, **detail})
    write_jsonl(pred_path, predictions)
    write_jsonl(details_path, details)
    evaluated_count = len(rows) - adapter_failures
    accuracy = correct_count / len(rows) if rows and adapter_failures == 0 else None
    write_json(report_path, {"accuracy": accuracy, "count": len(rows), "evaluated_count": evaluated_count, "adapter_failures": adapter_failures, "details_path": str(details_path)})
    stdout_path.write_text("\n".join(r.stdout_path for r in adapter_results), encoding="utf-8")
    stderr_path.write_text("\n".join(r.stderr_path for r in adapter_results), encoding="utf-8")
    status = "success" if accuracy is not None else ("adapter_failed" if adapter_failures else "failed")
    return HarnessRunResult(
        status=status,
        score=accuracy,
        pass_rate=accuracy,
        raw_result_path=str(report_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        harness_run_tokens=total_judge_tokens or None,
        score_breakdown={"metric": "HLE-style short-answer judge accuracy", "items": len(rows), "adapter_failures": adapter_failures},
        interactions=len(adapter_results),
    )


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

    csv_url = "https://openaipublic.blob.core.windows.net/simple-evals/browse_comp_test_set.csv"
    df = pd.read_csv(csv_url).head(int(entry.get("n_limit", 1)))
    predictions: list[dict[str, Any]] = []
    correct_count = 0
    total_judge_tokens = 0
    adapter_results: list[HarnessRunResult] = []
    adapter_failures = 0
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
        result = run_generated_harness(
            artifact.path,
            "research",
            prompt,
            output_dir / "adapter_outputs" / f"item_{idx}",
            python_bin=python_bin,
            timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
        )
        adapter_results.append(result)
        response = _read_adapter_response(result)
        if result.status != "success" or not response.strip():
            adapter_failures += 1
            predictions.append(
                {
                    "question": question,
                    "answer": answer,
                    "prediction": response,
                    "correct": False,
                    "adapter_status": result.status,
                    "adapter_error": result.error,
                }
            )
            continue
        correct, detail = _judge_short_answer(question, answer, response, prefix="BROWSECOMP_JUDGE")
        total_judge_tokens += int((detail.get("usage") or {}).get("total_tokens") or 0)
        correct_count += int(correct)
        predictions.append({"question": question, "answer": answer, "prediction": response, "correct": correct, "judge": detail.get("judge")})
    write_jsonl(responses_path, predictions)
    accuracy = correct_count / len(predictions) if predictions and adapter_failures == 0 else None
    write_json(report_path, {"accuracy": accuracy, "count": len(predictions), "adapter_failures": adapter_failures, "predictions_path": str(responses_path)})
    stdout_path.write_text("\n".join(r.stdout_path for r in adapter_results), encoding="utf-8")
    stderr_path.write_text("\n".join(r.stderr_path for r in adapter_results), encoding="utf-8")
    status = "success" if accuracy is not None else ("adapter_failed" if adapter_failures else "failed")
    return HarnessRunResult(
        status=status,
        score=accuracy,
        pass_rate=accuracy,
        raw_result_path=str(report_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        harness_run_tokens=total_judge_tokens or None,
        score_breakdown={"metric": "BrowseComp accuracy with encrypted official answer set", "items": len(predictions), "adapter_failures": adapter_failures},
        interactions=len(adapter_results),
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
    competition_id = str(entry.get("competition_id", "spaceship-titanic"))
    data_dir = Path(str(entry.get("data_dir") or os.environ.get("MLEBENCH_DATA_DIR") or Path.home() / ".cache" / "mle-bench" / "data")).expanduser()
    report_path = output_dir / "mlebench_report.json"
    stdout_path = output_dir / "mlebench_stdout.log"
    stderr_path = output_dir / "mlebench_stderr.log"
    if dry_run:
        return HarnessRunResult(status="skipped/dry_run", raw_result_path=str(report_path), stdout_path=str(stdout_path), stderr_path=str(stderr_path))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(mle_root) + os.pathsep + env.get("PYTHONPATH", "")
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
        f"Write a valid submission CSV into this output directory: {task_workspace}\n"
        "Use the same columns and row ids as the sample submission."
    )
    result = run_generated_harness(
        artifact.path,
        "data_analysis",
        prompt,
        output_dir / "adapter_output",
        task_work_dir=Path(info["public_dir"]),
        python_bin=python_bin,
        timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
    )
    artifacts = read_json(Path(result.raw_result_path)).get("artifacts_dir") if result.raw_result_path else None
    csv_candidates = []
    for root in [Path(str(artifacts)) if artifacts else None, output_dir / "adapter_output"]:
        if root and root.exists():
            csv_candidates.extend(path for path in root.rglob("*.csv") if path.is_file())
    if not csv_candidates:
        report = {
            "competition_id": competition_id,
            "score": 0.0,
            "submission_exists": False,
            "valid_submission": False,
            "failure_mode": "no_submission",
            "adapter_status": result.status,
            "adapter_error": result.error,
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
        interactions=1,
    )


def run_the_agent_company_generated(
    artifact: HarnessArtifact,
    entry: dict[str, Any],
    output_dir: Path,
    *,
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
    adapter_result = run_generated_harness(
        artifact.path,
        "browser",
        browser_prompt,
        output_dir / "adapter_outputs" / "the_agent_company",
        task_work_dir=workspace_dir,
        python_bin=python_bin,
        timeout=min(timeout, int(entry.get("harness_timeout", timeout))),
    )
    trajectory_path = output_dir / "generated_trajectory.txt"
    trajectory_bits = {
        "adapter_status": adapter_result.status,
        "adapter_error": adapter_result.error,
        "raw_result_path": adapter_result.raw_result_path,
        "stdout_path": adapter_result.stdout_path,
        "stderr_path": adapter_result.stderr_path,
        "response": _read_adapter_response(adapter_result),
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
        + "\n\n=== adapter ===\n"
        + (Path(adapter_result.stdout_path).read_text(encoding="utf-8", errors="replace") if adapter_result.stdout_path and Path(adapter_result.stdout_path).exists() else "")
        + "\n\n=== evaluator ===\n"
        + evaluate.stdout,
        encoding="utf-8",
    )
    stderr_path.write_text(
        task.stderr
        + "\n\n=== init ===\n"
        + init.stderr
        + "\n\n=== adapter ===\n"
        + (Path(adapter_result.stderr_path).read_text(encoding="utf-8", errors="replace") if adapter_result.stderr_path and Path(adapter_result.stderr_path).exists() else "")
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
            score_breakdown={"stage": "evaluator", "task_image": task_image, "adapter_status": adapter_result.status},
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
            "adapter_status": adapter_result.status,
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
    result = run_generated_harness(
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
    if runner == "dacomp_generated":
        return run_dacomp_generated(
            artifact,
            entry,
            output_dir,
            harness_evolve_root=harness_evolve_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "writingbench_generated":
        return run_writingbench_generated(
            artifact,
            entry,
            output_dir,
            harness_eval_root=harness_eval_root,
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )
    if runner == "deepresearch_generated":
        return run_deepresearch_generated(
            artifact,
            entry,
            output_dir,
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
            python_bin=python_bin,
            timeout=timeout,
            dry_run=dry_run,
        )

    if runner == "unsupported":
        if proxy_smoke_for_unsupported and not dry_run:
            return run_proxy_smoke(artifact, entry, output_dir, python_bin=python_bin, timeout=timeout)
        reason = str(entry.get("unsupported_reason") or "No generated-harness adapter is implemented for this benchmark runner yet")
        return HarnessRunResult(
            status="skipped/unsupported_adapter",
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
    return {
        "generation_model": artifact.generation_model,
        "domain": artifact.domain,
        "harness_task_id": artifact.task_id,
        "harness_path": str(artifact.path),
        "benchmark": entry.get("name", entry.get("id", "")),
        "benchmark_id": entry.get("id", ""),
        "generation_status": validation.generation_status,
        "syntax_ok": validation.syntax_ok,
        "import_ok": validation.import_ok,
        "cli_probe_ok": validation.cli_probe_ok,
        "adapter_status": validation.adapter_status,
        "eval_status": result.status,
        "score": result.score,
        "score_breakdown": result.score_breakdown,
        "pass_rate": result.pass_rate,
        "win_rate": result.win_rate,
        "reward": result.reward,
        "harness_run_tokens": result.tokens if result.tokens is not None else result.harness_run_tokens,
        "harness_run_interactions": result.interactions,
        "generation_tokens": validation.generation_tokens,
        "missing_dependencies": result.missing_dependencies or validation.missing_dependencies,
        "stdout_path": result.stdout_path or validation.stdout_path,
        "stderr_path": result.stderr_path or validation.stderr_path,
        "raw_result_path": result.raw_result_path or validation.raw_result_path,
    }
