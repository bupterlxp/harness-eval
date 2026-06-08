#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path
from typing import Any


BENCH_CONFIG = {
    "mle_bench": {
        "domain": "data_analysis",
        "task_id": "data-analysis-harness",
        "timeout": 604800,
        "resource": {"cpu": 16, "memory": 65536, "gpu": 0},
        "extra_env": {
            "HARNESS_EVAL_DATA_MAX_TURNS": "8",
            "MLEBENCH_DATA_DIR": "/opt/tiger/mle-bench-data",
        },
    },
    "eqbench3": {
        "domain": "writing",
        "task_id": "writing-harness",
        "timeout": 604800,
        "resource": {"cpu": 8, "memory": 32768, "gpu": 0},
        "extra_env": {},
    },
    "browsecomp": {
        "domain": "research",
        "task_id": "research-agent-harness",
        "timeout": 604800,
        "resource": {"cpu": 8, "memory": 32768, "gpu": 0},
        "extra_env": {
            "HARNESS_EVAL_RESEARCH_MAX_STEPS": "8",
            "HARNESS_EVAL_RESEARCH_BREADTH": "2",
            "HARNESS_EVAL_RESEARCH_DEPTH": "1",
        },
    },
}


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def read_template(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"empty template: {path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if line:
                return json.loads(line)
    raise ValueError(f"no JSON object found in template: {path}")


def get_nested(obj: dict[str, Any], path: list[str], default: Any = None) -> Any:
    current: Any = obj
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def ensure_nested(obj: dict[str, Any], path: list[str]) -> dict[str, Any]:
    current = obj
    for key in path:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    return current


def git_value(args: list[str], fallback: str = "") -> str:
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except Exception:  # noqa: BLE001 - fallback for generated job JSONL
        return fallback


def render_entrypoint(
    *,
    bench: str,
    generation_output: str,
    run_id: str,
    harness_eval_root: str,
    harness_evolve_root: str,
    output_root: str,
    python_bin: str,
    eval_model_name: str,
    eval_reasoning_effort: str,
    provider_extra_body_json: str,
    provider_strip_max_tokens: str,
) -> str:
    cfg = BENCH_CONFIG[bench]
    env_exports = "\n".join(
        f"export {key}={shlex_quote(value)}" for key, value in sorted(cfg["extra_env"].items())
    )
    mle_prepare = ""
    if bench == "mle_bench":
        data_dir = cfg["extra_env"]["MLEBENCH_DATA_DIR"]
        mle_prepare = f"""
mkdir -p {shlex_quote(data_dir)}
if [ ! -f "$HOME/.kaggle/kaggle.json" ] && [ -n "${{KAGGLE_JSON_B64:-}}" ]; then
  mkdir -p "$HOME/.kaggle"
  python3 - <<'PY'
import base64, os, pathlib
path = pathlib.Path.home() / ".kaggle" / "kaggle.json"
path.write_bytes(base64.b64decode(os.environ["KAGGLE_JSON_B64"]))
path.chmod(0o600)
PY
fi
if [ ! -f "$HOME/.kaggle/kaggle.json" ] && [ -n "${{KAGGLE_USERNAME:-}}" ] && [ -n "${{KAGGLE_KEY:-}}" ]; then
  mkdir -p "$HOME/.kaggle"
  python3 - <<'PY'
import json, os, pathlib
path = pathlib.Path.home() / ".kaggle" / "kaggle.json"
path.write_text(json.dumps({{"username": os.environ["KAGGLE_USERNAME"], "key": os.environ["KAGGLE_KEY"]}}))
path.chmod(0o600)
PY
fi
echo "[mle] preparing all competitions into {data_dir}"
"$PYTHON_BIN" -m mlebench.cli prepare --all --data-dir {shlex_quote(data_dir)}
"""
    provider_extra = (
        f"export PROVIDER_EXTRA_BODY_JSON={shlex_quote(provider_extra_body_json)}"
        if provider_extra_body_json
        else "unset PROVIDER_EXTRA_BODY_JSON"
    )
    strip_max = (
        f"export PROVIDER_STRIP_MAX_TOKENS={shlex_quote(provider_strip_max_tokens)}"
        if provider_strip_max_tokens
        else "unset PROVIDER_STRIP_MAX_TOKENS"
    )
    return f"""set -euo pipefail

cd {shlex_quote(harness_eval_root)}

export PATH="$HOME/.local/bin:$PATH"
export HARNESS_EVAL_ROOT={shlex_quote(harness_eval_root)}
export HARNESS_EVOLVE_ROOT={shlex_quote(harness_evolve_root)}
export PYTHONUNBUFFERED=1
{strip_max}
{provider_extra}
export EVAL_MODEL_NAME="${{EVAL_MODEL_NAME:-{eval_model_name}}}"
export EVAL_REASONING_EFFORT="${{EVAL_REASONING_EFFORT:-{eval_reasoning_effort}}}"
export EVAL_PROVIDER_PROXY_PORT="${{EVAL_PROVIDER_PROXY_PORT:-4568}}"
{env_exports}

if [ -n "${{GLM_API_KEY:-}}" ] && [ -z "${{EVAL_API_KEY:-}}" ]; then
  export EVAL_API_KEY="$GLM_API_KEY"
fi
if [ -n "${{GLM_API_KEY:-}}" ] && [ -z "${{EVAL_BASE_URL:-}}" ]; then
  export EVAL_BASE_URL="https://aidp.bytedance.net/api/modelhub/online/v2/crawl?ak=${{GLM_API_KEY}}"
fi
if [ -n "${{MODELHUB_AK:-}}" ] && [ -z "${{EVAL_API_KEY:-}}" ]; then
  export EVAL_API_KEY="$MODELHUB_AK"
fi
if [ -n "${{MODELHUB_AK:-}}" ] && [ -z "${{EVAL_BASE_URL:-}}" ]; then
  export EVAL_BASE_URL="https://aidp.bytedance.net/api/modelhub/online/v2/crawl?ak=${{MODELHUB_AK}}"
fi
if [ -z "${{EVAL_BASE_URL:-}}" ] || [ -z "${{EVAL_API_KEY:-}}" ]; then
  echo "ERROR: set EVAL_BASE_URL/EVAL_API_KEY, or set MODELHUB_AK/GLM_API_KEY for a ModelHub crawl endpoint."
  exit 2
fi

if [ ! -d {shlex_quote(generation_output)} ]; then
  echo "ERROR: missing generated harness artifact root: {generation_output}"
  exit 2
fi

mkdir -p "$HARNESS_EVAL_ROOT/external_benchmarks"
ln -sfn "$HARNESS_EVOLVE_ROOT/external_benchmarks/mle-bench" "$HARNESS_EVAL_ROOT/external_benchmarks/mle-bench"
ln -sfn "$HARNESS_EVOLVE_ROOT/external_benchmarks/simple-evals" "$HARNESS_EVAL_ROOT/external_benchmarks/simple-evals"

if ! command -v node >/dev/null 2>&1; then
  echo "[setup] node is missing; installing nodejs/npm"
  if command -v sudo >/dev/null 2>&1; then SUDO=sudo; else SUDO=; fi
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm
fi

PYTHON_BIN={shlex_quote(python_bin)}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
"$PYTHON_BIN" -m pip install --user -r requirements.txt
"$PYTHON_BIN" -m pip install --user -e "$HARNESS_EVAL_ROOT/external_benchmarks/mle-bench" || true

export PYTHONPATH="$HARNESS_EVAL_ROOT/external_benchmarks/mle-bench:$HARNESS_EVAL_ROOT:${{PYTHONPATH:-}}"

{mle_prepare}

mkdir -p {shlex_quote(output_root)}
"$PYTHON_BIN" run_creation_eval.py \\
  --generation-output {shlex_quote(generation_output)} \\
  --matrix eval_matrix.yaml \\
  --bench {shlex_quote(bench)} \\
  --domain {shlex_quote(cfg["domain"])} \\
  --run-id {shlex_quote(run_id)} \\
  --eval-output-root {shlex_quote(output_root)} \\
  --harness-evolve-root "$HARNESS_EVOLVE_ROOT" \\
  --python-bin "$PYTHON_BIN" \\
  --adapter-mode strict \\
  --eval-base-url "$EVAL_BASE_URL" \\
  --eval-api-key "$EVAL_API_KEY" \\
  --eval-model-name "$EVAL_MODEL_NAME" \\
  --eval-reasoning-effort "$EVAL_REASONING_EFFORT" \\
  --eval-provider-proxy-port "$EVAL_PROVIDER_PROXY_PORT" \\
  --timeout-seconds {cfg["timeout"]}

echo "DONE {bench}: {run_id}"
echo "summary: {output_root}/{run_id}/summary.csv"
"""


def patch_resource(job: dict[str, Any], resource: dict[str, int]) -> None:
    arnold = get_nested(job, ["jobRunParams", "resource", "arnoldConfig"], {})
    if isinstance(arnold, dict):
        roles = arnold.get("roles")
        if isinstance(roles, list) and roles:
            role = roles[0]
            role["cpu"] = resource["cpu"]
            role["memory"] = resource["memory"]
            role["gpu"] = resource["gpu"]
            role.setdefault("gpuv", "CPU_ONLY")
    job_def_resource = ensure_nested(job, ["jobDefVersion", "resource"])
    job_def_resource["cpu"] = resource["cpu"]
    job_def_resource["memory"] = resource["memory"]
    job_def_resource["gpu"] = resource["gpu"]


def patch_job(
    template: dict[str, Any],
    *,
    bench: str,
    run_id: str,
    generation_output: str,
    output_root: str,
    python_bin: str,
    preserve_template_env: bool,
    git_branch: str,
    git_commit: str,
    dependency_branch: str,
    dependency_commit: str,
    eval_model_name: str,
    eval_reasoning_effort: str,
    provider_extra_body_json: str,
    provider_strip_max_tokens: str,
) -> dict[str, Any]:
    job = copy.deepcopy(template)
    caption = f"he-{bench}-{run_id}"[:96]
    job["caption"] = caption
    jd = ensure_nested(job, ["jobDefVersion"])
    jd["name"] = caption
    jd["entrypointMode"] = "FULL_SCRIPT"
    main_repo = ensure_nested(jd, ["gitRepo"])
    main_repo["branchName"] = git_branch
    main_repo["commitSha"] = git_commit
    main_repo["useLatestCommit"] = False
    harness_eval_root = str(main_repo.get("mnt") or "/opt/tiger/Harness_evolve")
    subrepos = jd.get("subRepos") if isinstance(jd.get("subRepos"), list) else []
    if subrepos and isinstance(subrepos[0], dict):
        if dependency_branch:
            subrepos[0]["branchName"] = dependency_branch
        if dependency_commit:
            subrepos[0]["commitSha"] = dependency_commit
            subrepos[0]["useLatestCommit"] = False
    harness_evolve_root = (
        str(subrepos[0].get("mnt"))
        if subrepos and isinstance(subrepos[0], dict) and subrepos[0].get("mnt")
        else "/opt/tiger/harness_evolve_project"
    )
    script = render_entrypoint(
        bench=bench,
        generation_output=generation_output,
        run_id=run_id,
        harness_eval_root=harness_eval_root,
        harness_evolve_root=harness_evolve_root,
        output_root=output_root,
        python_bin=python_bin,
        eval_model_name=eval_model_name,
        eval_reasoning_effort=eval_reasoning_effort,
        provider_extra_body_json=provider_extra_body_json,
        provider_strip_max_tokens=provider_strip_max_tokens,
    )
    jd["entrypointFullScript"] = script
    run_params = ensure_nested(job, ["jobRunParams"])
    run_params["entrypointFullScript"] = script
    if not preserve_template_env:
        run_params["envsList"] = {}
    patch_resource(job, BENCH_CONFIG[bench]["resource"])
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Seed job JSONL for non-Docker downstream BMK full evals.")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benches", default="mle_bench,eqbench3,browsecomp")
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument(
        "--generation-output-root",
        default="/opt/tiger/Harness_evolve/outputs/creation-glm51-high-devfeedback-20260608-170801",
    )
    parser.add_argument("--output-root", default="/opt/tiger/Harness_evolve/eval_results/cluster_full")
    parser.add_argument("--python-bin", default="python3")
    parser.add_argument("--preserve-template-env", action="store_true")
    parser.add_argument("--git-branch", default=git_value(["branch", "--show-current"], "codex/platform-native-bmk-shards"))
    parser.add_argument("--git-commit", default=git_value(["rev-parse", "HEAD"], ""))
    parser.add_argument("--dependency-branch", default="")
    parser.add_argument("--dependency-commit", default="")
    parser.add_argument("--eval-model-name", default="glm-5.1")
    parser.add_argument("--eval-reasoning-effort", default="high")
    parser.add_argument("--provider-extra-body-json", default='{"reasoning_effort":"high","thinking":{"type":"enabled"}}')
    parser.add_argument("--provider-strip-max-tokens", default="1")
    args = parser.parse_args()

    template = read_template(args.template)
    benches = [item.strip() for item in args.benches.split(",") if item.strip()]
    unknown = [bench for bench in benches if bench not in BENCH_CONFIG]
    if unknown:
        raise ValueError(f"unknown bench(es): {unknown}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for bench in benches:
            cfg = BENCH_CONFIG[bench]
            generation_output = f"{args.generation_output_root.rstrip('/')}/{cfg['task_id']}"
            run_id = f"{args.run_id_prefix}-{bench}"
            job = patch_job(
                template,
                bench=bench,
                run_id=run_id,
                generation_output=generation_output,
                output_root=args.output_root,
                python_bin=args.python_bin,
                preserve_template_env=args.preserve_template_env,
                git_branch=args.git_branch,
                git_commit=args.git_commit,
                dependency_branch=args.dependency_branch,
                dependency_commit=args.dependency_commit,
                eval_model_name=args.eval_model_name,
                eval_reasoning_effort=args.eval_reasoning_effort,
                provider_extra_body_json=args.provider_extra_body_json,
                provider_strip_max_tokens=args.provider_strip_max_tokens,
            )
            handle.write(json.dumps(job, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(benches)} jobs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
