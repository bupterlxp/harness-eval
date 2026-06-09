from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schema import HarnessRunResult
from .token_usage import extract_harness_token_usage
from .utils import read_json, run_command, write_json


def _llm_config_from_env(model_name: str | None = None) -> dict[str, Any]:
    model = (
        model_name
        or os.environ.get("MODEL_NAME")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or ""
    )
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or ""
    )
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or ""
    )
    reasoning_effort = os.environ.get("REASONING_EFFORT") or os.environ.get("EVAL_REASONING_EFFORT") or ""
    config: dict[str, Any] = {
        "provider": "openai_compatible",
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }
    if reasoning_effort:
        config["reasoning_effort"] = reasoning_effort
    return config


def _write_task_files(
    output_dir: Path,
    *,
    domain: str,
    prompt: str,
    task_work_dir: Path | None,
    model_name: str | None,
) -> tuple[Path, Path]:
    task_json = output_dir / "task.json"
    model_config_json = output_dir / "model_config.json"
    write_json(
        task_json,
        {
            "task_id": f"{domain}-downstream-task",
            "domain": domain,
            "prompt": prompt,
            "workdir": str((task_work_dir or output_dir).resolve()),
            "output_dir": str(output_dir.resolve()),
        },
    )
    write_json(
        model_config_json,
        {
            "llm": _llm_config_from_env(model_name),
            "policy": {},
            "include_optional_tools": True,
        },
    )
    return task_json, model_config_json


def _pythonpath(artifact_path: Path) -> str:
    shim_dir = Path(__file__).resolve().parent / "shims"
    parts = [str(artifact_path), str(shim_dir)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def _response_path(output_dir: Path) -> Path:
    return output_dir / "response.md"


def _attach_token_usage(result: HarnessRunResult, *paths: Path | str | None) -> HarnessRunResult:
    usage = extract_harness_token_usage(*paths, result.raw_result_path, result.stdout_path, result.stderr_path)
    total = usage.get("total_tokens") if usage else None
    if isinstance(total, (int, float)):
        result.harness_run_tokens = int(total)
        result.token_breakdown = usage
    return result


def read_harness_response(result: HarnessRunResult) -> str:
    raw = read_json(Path(result.raw_result_path)) if result.raw_result_path else {}
    response_path = raw.get("response_path")
    if response_path and Path(str(response_path)).is_file():
        return Path(str(response_path)).read_text(encoding="utf-8", errors="replace")
    out_dir = raw.get("output_dir")
    if out_dir:
        candidate = _response_path(Path(str(out_dir)))
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def run_agent_cli(
    artifact_path: Path,
    domain: str,
    prompt: str,
    output_dir: Path,
    *,
    task_work_dir: Path | None = None,
    python_bin: str,
    timeout: int,
    model_name: str | None = None,
) -> HarnessRunResult:
    """Run a generated harness through its public CLI contract.

    The contract is intentionally simple and benchmark-facing:

    ``python -m harness run --task-json TASK --model-config MODEL --output-dir OUT``

    No legacy fallback, entrypoint guessing, runtime patching, or output repair is
    performed here. If the generated harness cannot satisfy this CLI contract,
    the benchmark row records a harness failure.
    """

    artifact_path = artifact_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "harness_stdout.log"
    stderr_path = output_dir / "harness_stderr.log"
    raw_result_path = output_dir / "harness_result.json"

    harness_pkg = artifact_path / "harness"
    if not harness_pkg.is_dir():
        write_json(
            raw_result_path,
            {
                "status": "harness_failed",
                "error": "missing harness/ package with python -m harness entrypoint",
                "output_dir": str(output_dir),
            },
        )
        return HarnessRunResult(
            status="harness_failed",
            raw_result_path=str(raw_result_path),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error="missing harness/ package with python -m harness entrypoint",
        )

    task_json, model_config_json = _write_task_files(
        output_dir,
        domain=domain,
        prompt=prompt,
        task_work_dir=task_work_dir,
        model_name=model_name,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = _pythonpath(artifact_path)
    env["GENERATED_HARNESS_PATH"] = str(artifact_path)
    env["GENERATED_HARNESS_DOMAIN"] = domain
    if task_work_dir:
        env["TASK_WORK_DIR"] = str(task_work_dir.resolve())

    command = [
        python_bin,
        "-m",
        "harness",
        "run",
        "--task-json",
        str(task_json),
        "--model-config",
        str(model_config_json),
        "--output-dir",
        str(output_dir),
    ]
    completed = run_command(command, cwd=artifact_path, env=env, timeout=timeout)
    stdout_path.write_text(completed.stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(completed.stderr, encoding="utf-8", errors="replace")
    response_path = _response_path(output_dir)
    response_text = response_path.read_text(encoding="utf-8", errors="replace").strip() if response_path.is_file() else ""
    status = "success" if completed.returncode == 0 and response_text else "harness_failed"
    payload = {
        "status": status,
        "command": command,
        "returncode": completed.returncode,
        "elapsed_sec": completed.elapsed_sec,
        "output_dir": str(output_dir),
        "response_path": str(response_path) if response_path.is_file() else "",
        "task_json": str(task_json),
        "model_config_json": str(model_config_json),
    }
    if status != "success":
        payload["error"] = (
            "generated harness did not produce response.md"
            if completed.returncode == 0
            else (completed.stderr or completed.stdout)[-2000:]
        )
    write_json(raw_result_path, payload)

    result = HarnessRunResult(
        status=status,
        raw_result_path=str(raw_result_path),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        error=str(payload.get("error") or ""),
        score_breakdown={"harness_cli": "python -m harness run"},
        interactions=1,
    )
    return _attach_token_usage(result, output_dir, raw_result_path, stdout_path, stderr_path)
