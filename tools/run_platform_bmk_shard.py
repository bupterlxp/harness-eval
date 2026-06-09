#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from creation_eval.agent_cli import read_harness_response, run_agent_cli
from creation_eval.llm_runtime import LLMRuntime, configure_eval_llm
from creation_eval.token_usage import extract_harness_token_usage_from_result
from creation_eval.utils import write_json


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_cmd(command: list[str] | str, cwd: Path, timeout: int | None = None) -> dict[str, Any]:
    started = time.time()
    shell = isinstance(command, str)
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=shell,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "command": command if isinstance(command, str) else shlex.join(command),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_sec": time.time() - started,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command if isinstance(command, str) else shlex.join(command),
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"command timed out after {timeout}s",
            "elapsed_sec": time.time() - started,
        }


def resolve_path(value: str | None, default: Path) -> Path:
    if not value:
        return default.resolve()
    return Path(value).expanduser().resolve()


def field(instance: dict[str, Any], name: str, default: Any = "") -> Any:
    env_name = "BMK_" + name.upper()
    if os.environ.get(env_name):
        return os.environ[env_name]
    return instance.get(name, default)


def load_instance(args: argparse.Namespace) -> dict[str, Any]:
    if args.instance_json:
        return read_json(args.instance_json)
    env_json = os.environ.get("BMK_INSTANCE_JSON")
    if env_json:
        return json.loads(env_json)
    return {
        "benchmark": args.benchmark,
        "instance_id": os.environ.get("BMK_INSTANCE_ID", "unknown"),
        "repo": os.environ.get("BMK_REPO", ""),
        "repo_family": os.environ.get("BMK_REPO_FAMILY", ""),
        "problem_statement": os.environ.get("BMK_PROBLEM_STATEMENT", ""),
        "task_prompt": os.environ.get("BMK_TASK_PROMPT", ""),
        "task_work_dir": os.environ.get("BMK_TASK_WORK_DIR", ""),
        "verify_cmd": os.environ.get("BMK_VERIFY_CMD", ""),
    }


def build_prompt(benchmark: str, instance: dict[str, Any], task_work_dir: Path) -> str:
    instance_id = str(field(instance, "instance_id", "unknown"))
    repo = str(field(instance, "repo", ""))
    repo_family = str(field(instance, "repo_family", ""))
    problem = str(
        field(instance, "problem_statement", "")
        or field(instance, "task_prompt", "")
        or field(instance, "prompt", "")
    )
    hints = str(field(instance, "hints", "") or field(instance, "test_command", ""))
    if benchmark in {"swebench_pro", "swebench", "swe_bench"}:
        return (
            "You are running inside a platform-native SWE-style benchmark shard. "
            "The current container already contains the target repository and task environment; "
            "do not start Docker.\n\n"
            f"Instance ID: {instance_id}\n"
            f"Repository: {repo}\n"
            f"Repo family: {repo_family}\n"
            f"Repository work directory: {task_work_dir}\n\n"
            "Task:\n"
            f"{problem}\n\n"
            "Requirements:\n"
            "- Inspect the repository before editing.\n"
            "- Make real source-code changes in the repository work directory.\n"
            "- Run relevant tests or validation commands when available.\n"
            "- Preserve the benchmark protocol; do not hardcode hidden answers or modify the scorer.\n"
            "- Finish with a concise summary of changed files, commands run, and verification status.\n"
            f"{'Additional public hints or commands: ' + hints if hints else ''}\n"
        )
    if benchmark in {"terminal_2_bench", "terminalbench", "terminal_bench"}:
        return (
            "You are running inside a platform-native Terminal 2.0 style benchmark shard. "
            "The current container is the task environment; do not start Docker.\n\n"
            f"Instance ID: {instance_id}\n"
            f"Work directory: {task_work_dir}\n\n"
            "Terminal task:\n"
            f"{problem}\n\n"
            "Requirements:\n"
            "- Use shell/file tools through the harness to complete the task in this environment.\n"
            "- Record commands, observations, and final state.\n"
            "- Preserve the benchmark protocol; do not modify hidden verifier logic.\n"
            f"{'Additional public hints or commands: ' + hints if hints else ''}\n"
        )
    return problem or f"Run benchmark shard {benchmark} instance {instance_id} in {task_work_dir}."


def git_diff(repo_dir: Path, output_path: Path) -> dict[str, Any]:
    if not (repo_dir / ".git").exists():
        return {"available": False, "reason": "task_work_dir is not a git repository"}
    diff = run_cmd(["git", "diff", "--binary"], cwd=repo_dir)
    output_path.write_text(diff["stdout"], encoding="utf-8")
    changed = run_cmd(["git", "status", "--short"], cwd=repo_dir)
    return {
        "available": True,
        "path": str(output_path),
        "bytes": len(diff["stdout"].encode("utf-8")),
        "changed_files": [
            line[3:].strip() for line in changed["stdout"].splitlines() if len(line) >= 4
        ],
        "status_stdout": changed["stdout"],
    }


def score_from_verify(verify: dict[str, Any] | None) -> tuple[str, float | None]:
    if not verify:
        return "success/no_verifier", None
    if verify["returncode"] == 0:
        return "success", 1.0
    if verify["returncode"] == 124:
        return "failed/verify_timeout", 0.0
    return "failed/verify", 0.0


def parse_list_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    for loader in (json.loads, ast.literal_eval):
        try:
            loaded = loader(text)
        except Exception:
            continue
        if isinstance(loaded, list):
            return [str(item) for item in loaded if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def build_base_setup_cmd(instance: dict[str, Any]) -> str:
    base_commit = str(field(instance, "base_commit", "") or "").strip()
    if not base_commit:
        return ""
    return " && ".join(
        [
            f"git reset --hard {shlex.quote(base_commit)}",
            "git clean -fd",
            f"git checkout {shlex.quote(base_commit)}",
        ]
    )


def build_test_injection_cmd(instance: dict[str, Any]) -> str:
    before_cmd = str(field(instance, "before_repo_set_cmd", "") or "")
    for line in before_cmd.splitlines():
        stripped = line.strip()
        if stripped.startswith("git checkout ") and " -- " in stripped:
            return stripped
    return ""


def infer_verify_cmd(instance: dict[str, Any]) -> str:
    selected = parse_list_field(field(instance, "selected_test_files_to_run", ""))
    if not selected:
        return ""
    repo_family = str(field(instance, "repo_family", "") or "").lower()
    quoted = " ".join(shlex.quote(item) for item in selected)

    if any(name in repo_family for name in ("qutebrowser", "ansible", "openlibrary")):
        return f"python -m pytest -q {quoted}"

    if "nodebb" in repo_family:
        return (
            "if [ -x ./node_modules/.bin/mocha ]; then "
            f"./node_modules/.bin/mocha {quoted}; "
            "elif command -v npx >/dev/null 2>&1; then "
            f"npx mocha {quoted}; "
            "else "
            f"npm test -- {quoted}; "
            "fi"
        )

    if "element-hq__element-web" in repo_family or "element-web" in repo_family:
        return (
            "if [ -x ./node_modules/.bin/jest ]; then "
            f"./node_modules/.bin/jest --runInBand {quoted}; "
            "elif command -v yarn >/dev/null 2>&1; then "
            f"yarn jest --runInBand {quoted}; "
            "else "
            f"npm test -- --runInBand {quoted}; "
            "fi"
        )

    if any(name in repo_family for name in ("flipt", "navidrome", "vuls", "teleport")):
        test_names = [item for item in selected if not item.endswith(".go") and "/" not in item]
        if test_names:
            regex = "^(" + "|".join(re.escape(item) for item in test_names) + ")$"
            return f"go test ./... -run {shlex.quote(regex)}"
        package_dirs = sorted({str(Path(item).parent) for item in selected if item.endswith(".go")})
        package_args = " ".join(shlex.quote("./" + d if d != "." else ".") for d in package_dirs)
        return f"go test {package_args or './...'}"

    return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one platform-native benchmark shard. The container must already be "
            "the prebuilt image for the target instance or repo family."
        )
    )
    parser.add_argument("--benchmark", required=True, help="swebench_pro or terminal_2_bench.")
    parser.add_argument("--instance-json", type=Path, default=None)
    parser.add_argument("--harness-path", type=Path, required=True)
    parser.add_argument("--domain", default="code")
    parser.add_argument("--task-work-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--verify-cmd", default=None, help="Optional verifier command in the task image.")
    parser.add_argument("--run-id", default=os.environ.get("BMK_RUN_ID", "platform-native-shard"))
    parser.add_argument("--eval-base-url", default=os.environ.get("EVAL_BASE_URL"))
    parser.add_argument("--eval-api-key", default=os.environ.get("EVAL_API_KEY"))
    parser.add_argument("--eval-model-name", default=os.environ.get("EVAL_MODEL_NAME"))
    parser.add_argument("--eval-reasoning-effort", default=os.environ.get("EVAL_REASONING_EFFORT"))
    parser.add_argument("--eval-provider-proxy-port", type=int, default=int(os.environ.get("EVAL_PROVIDER_PROXY_PORT", "4568")))
    parser.add_argument("--no-eval-provider-proxy", action="store_true")
    args = parser.parse_args()

    instance = load_instance(args)
    benchmark = str(field(instance, "benchmark", args.benchmark) or args.benchmark)
    instance_id = str(field(instance, "instance_id", "unknown"))
    task_work_dir = resolve_path(
        str(field(instance, "task_work_dir", "")) or str(args.task_work_dir or ""),
        Path.cwd(),
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base_setup_cmd = build_base_setup_cmd(instance)
    base_setup_result = None
    if base_setup_cmd:
        base_setup_result = run_cmd(base_setup_cmd, cwd=task_work_dir, timeout=args.timeout_seconds)
        (output_dir / "base_setup_stdout.log").write_text(base_setup_result["stdout"], encoding="utf-8")
        (output_dir / "base_setup_stderr.log").write_text(base_setup_result["stderr"], encoding="utf-8")
        if base_setup_result["returncode"] != 0:
            row = {
                "run_id": args.run_id,
                "benchmark": benchmark,
                "instance_id": instance_id,
                "repo": field(instance, "repo", ""),
                "repo_family": field(instance, "repo_family", ""),
                "task_work_dir": str(task_work_dir),
                "eval_status": "failed/base_setup",
                "score": 0.0,
                "base_setup": {key: value for key, value in base_setup_result.items() if key not in {"stdout", "stderr"}},
            }
            write_json(output_dir / "shard_result.json", row)
            write_jsonl(output_dir / "shard_result.jsonl", row)
            print(json.dumps(row, ensure_ascii=False))
            return 1

    prompt = build_prompt(benchmark, instance, task_work_dir)
    prompt_path = output_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    instance_path = output_dir / "instance.json"
    write_json(instance_path, instance)

    harness_output = output_dir / "harness_output"
    started = time.time()
    runtime = LLMRuntime()
    try:
        runtime = configure_eval_llm(
            harness_eval_root=Path(__file__).resolve().parents[1],
            base_url=args.eval_base_url,
            api_key=args.eval_api_key,
            model_name=args.eval_model_name,
            reasoning_effort=args.eval_reasoning_effort,
            provider_proxy=not args.no_eval_provider_proxy,
            provider_proxy_port=args.eval_provider_proxy_port,
            log_path=output_dir / "eval_provider_proxy.log",
        )
        harness_result = run_agent_cli(
            args.harness_path.resolve(),
            args.domain,
            prompt,
            harness_output,
            task_work_dir=task_work_dir,
            python_bin=args.python_bin,
            timeout=args.timeout_seconds,
        )
    finally:
        runtime.close()

    patch_info = git_diff(task_work_dir, output_dir / "prediction.patch")
    test_injection_cmd = build_test_injection_cmd(instance)
    test_injection_result = None
    if test_injection_cmd:
        test_injection_result = run_cmd(test_injection_cmd, cwd=task_work_dir, timeout=args.timeout_seconds)
        (output_dir / "test_injection_stdout.log").write_text(test_injection_result["stdout"], encoding="utf-8")
        (output_dir / "test_injection_stderr.log").write_text(test_injection_result["stderr"], encoding="utf-8")

    verify_cmd = args.verify_cmd or str(field(instance, "verify_cmd", "")) or infer_verify_cmd(instance)
    verify_result = None
    if test_injection_result and test_injection_result["returncode"] != 0:
        verify_result = {
            "command": test_injection_cmd,
            "returncode": test_injection_result["returncode"],
            "stdout": test_injection_result["stdout"],
            "stderr": test_injection_result["stderr"],
            "elapsed_sec": test_injection_result["elapsed_sec"],
        }
        (output_dir / "verify_stdout.log").write_text(verify_result["stdout"], encoding="utf-8")
        (output_dir / "verify_stderr.log").write_text(verify_result["stderr"], encoding="utf-8")
    elif verify_cmd:
        verify_result = run_cmd(verify_cmd, cwd=task_work_dir, timeout=args.timeout_seconds)
        (output_dir / "verify_stdout.log").write_text(verify_result["stdout"], encoding="utf-8")
        (output_dir / "verify_stderr.log").write_text(verify_result["stderr"], encoding="utf-8")

    eval_status, score = score_from_verify(verify_result)
    if harness_result.status != "success":
        eval_status = "failed/harness"
        score = 0.0

    usage = extract_harness_token_usage_from_result(harness_result)
    row = {
        "run_id": args.run_id,
        "benchmark": benchmark,
        "instance_id": instance_id,
        "repo": field(instance, "repo", ""),
        "repo_family": field(instance, "repo_family", ""),
        "harness_path": str(args.harness_path.resolve()),
        "task_work_dir": str(task_work_dir),
        "harness_invocation": "python -m harness run",
        "harness_status": harness_result.status,
        "eval_status": eval_status,
        "score": score,
        "harness_run_tokens": usage.get("total_tokens"),
        "harness_run_token_breakdown": usage,
        "patch": patch_info,
        "base_setup": {
            key: value
            for key, value in (base_setup_result or {}).items()
            if key not in {"stdout", "stderr"}
        } if base_setup_result else None,
        "test_injection": {
            key: value
            for key, value in (test_injection_result or {}).items()
            if key not in {"stdout", "stderr"}
        } if test_injection_result else None,
        "verify_cmd": verify_cmd,
        "verify": {
            key: value
            for key, value in (verify_result or {}).items()
            if key not in {"stdout", "stderr"}
        } if verify_result else None,
        "stdout_path": harness_result.stdout_path,
        "stderr_path": harness_result.stderr_path,
        "raw_result_path": harness_result.raw_result_path,
        "elapsed_sec": time.time() - started,
    }
    write_json(output_dir / "shard_result.json", row)
    write_jsonl(output_dir / "shard_result.jsonl", row)
    print(json.dumps(row, ensure_ascii=False))
    return 0 if eval_status.startswith("success") or eval_status == "failed/verify" else 1


if __name__ == "__main__":
    raise SystemExit(main())
