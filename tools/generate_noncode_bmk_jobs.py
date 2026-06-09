#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
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
    scenario_id: str,
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
    output_uri_prefix: str,
) -> str:
    cfg = BENCH_CONFIG[bench]
    run_output_dir = f"{output_root.rstrip('/')}/{run_id}"
    cluster_dir = f"{run_output_dir}/_cluster"
    env_exports = "\n".join(
        f"export {key}={shlex_quote(value)}" for key, value in sorted(cfg["extra_env"].items())
    )
    bench_setup = ""
    if bench == "eqbench3":
        bench_setup = """
"$PYTHON_BIN" -m pip install --user trueskill
"""
    matrix_setup = """
export MATRIX_PATH=eval_matrix.yaml
"""
    if bench == "eqbench3" and scenario_id:
        matrix_setup = f"""
export EQBENCH3_SCENARIO={shlex_quote(scenario_id)}
export MATRIX_PATH="$CLUSTER_DIR/eval_matrix_eqbench3_${{EQBENCH3_SCENARIO}}.yaml"
"$PYTHON_BIN" - <<'PY'
import os
import pathlib
import yaml

scenario = os.environ["EQBENCH3_SCENARIO"]
src = pathlib.Path("eval_matrix.yaml")
data = yaml.safe_load(src.read_text())
for entry in data.get("benchmarks", []):
    if entry.get("id") == "eqbench3":
        entry["default_subset"] = scenario
        entry["threads"] = 1
path = pathlib.Path(os.environ["MATRIX_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
PY
"""
    mle_prepare = ""
    if bench == "mle_bench":
        data_dir = cfg["extra_env"]["MLEBENCH_DATA_DIR"]
        prepare_target = "--all"
        if scenario_id:
            prepare_target = f"-c {shlex_quote(scenario_id)}"
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
echo "[mle] preparing {scenario_id or 'all competitions'} into {data_dir}"
set +e
"$PYTHON_BIN" -m mlebench.cli prepare {prepare_target} --data-dir {shlex_quote(data_dir)} > "$CLUSTER_DIR/mle_prepare_stdout.log" 2> "$CLUSTER_DIR/mle_prepare_stderr.log"
MLE_PREPARE_RC=$?
set -e
export MLE_PREPARE_RC
python3 - <<'PY'
import json, os, pathlib, time
path = pathlib.Path(os.environ["CLUSTER_DIR"]) / "mle_prepare_status.json"
path.write_text(json.dumps({{
    "stage": "mle_prepare",
    "returncode": int(os.environ.get("MLE_PREPARE_RC", "0")),
    "timestamp": int(time.time()),
    "stdout_path": str(path.parent / "mle_prepare_stdout.log"),
    "stderr_path": str(path.parent / "mle_prepare_stderr.log"),
}}, ensure_ascii=False, indent=2))
PY
if [ "$MLE_PREPARE_RC" -ne 0 ]; then
  echo "[mle] prepare failed rc=$MLE_PREPARE_RC; continuing so run_creation_eval can emit a structured failure row"
fi
"""
    if bench == "mle_bench" and scenario_id:
        matrix_setup = f"""
export MLE_COMPETITION_ID={shlex_quote(scenario_id)}
export MATRIX_PATH="$CLUSTER_DIR/eval_matrix_mle_${{MLE_COMPETITION_ID}}.yaml"
"$PYTHON_BIN" - <<'PY'
import os
import pathlib
import yaml

competition_id = os.environ["MLE_COMPETITION_ID"]
src = pathlib.Path("eval_matrix.yaml")
data = yaml.safe_load(src.read_text())
for entry in data.get("benchmarks", []):
    if entry.get("id") == "mle_bench":
        entry["competition_id"] = competition_id
        entry["default_subset"] = competition_id
path = pathlib.Path(os.environ["MATRIX_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
PY
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
    upload_block = ""
    if output_uri_prefix:
        upload_block = f"""
  HDFS_BIN="$(command -v hdfs || true)"
  if [ -z "$HDFS_BIN" ] && [ -x /opt/tiger/arnold/hdfs_client/hdfs ]; then
    HDFS_BIN=/opt/tiger/arnold/hdfs_client/hdfs
  fi
  if [ -n "$HDFS_BIN" ]; then
    if [ -f /usr/local/bin/import_hdfs_envs.sh ]; then
      # shellcheck disable=SC1091
      source /usr/local/bin/import_hdfs_envs.sh >/dev/null 2>&1 || true
    fi
    HDFS_TARGET={shlex_quote(output_uri_prefix.rstrip('/') + '/' + run_id)}
    "$HDFS_BIN" dfs -mkdir -p "$HDFS_TARGET" >/dev/null 2>&1 || true
    "$HDFS_BIN" dfs -put -f "$RUN_OUTPUT_DIR/cluster_artifacts.tgz" "$HDFS_TARGET/cluster_artifacts.tgz" >/dev/null 2>&1 || true
    "$HDFS_BIN" dfs -put -f "$RUN_OUTPUT_DIR/summary.csv" "$HDFS_TARGET/summary.csv" >/dev/null 2>&1 || true
    "$HDFS_BIN" dfs -put -f "$RUN_OUTPUT_DIR/summary.jsonl" "$HDFS_TARGET/summary.jsonl" >/dev/null 2>&1 || true
  fi
"""
    return f"""set -euo pipefail

cd {shlex_quote(harness_eval_root)}

export PATH="$HOME/.local/bin:$PATH"
export HARNESS_EVAL_ROOT={shlex_quote(harness_eval_root)}
export HARNESS_EVOLVE_ROOT={shlex_quote(harness_evolve_root)}
export PYTHONUNBUFFERED=1
export RUN_ID={shlex_quote(run_id)}
export BENCH_NAME={shlex_quote(bench)}
export BENCH_DOMAIN={shlex_quote(cfg["domain"])}
export RUN_OUTPUT_DIR={shlex_quote(run_output_dir)}
export CLUSTER_DIR={shlex_quote(cluster_dir)}
mkdir -p "$CLUSTER_DIR"
touch "$CLUSTER_DIR/entrypoint_stdout.log" "$CLUSTER_DIR/entrypoint_stderr.log"
exec > >(tee -a "$CLUSTER_DIR/entrypoint_stdout.log") 2> >(tee -a "$CLUSTER_DIR/entrypoint_stderr.log" >&2)

finalize_cluster_artifacts() {{
  rc="${{CLUSTER_EXIT_RC:-$?}}"
  set +e
  python3 - <<'PY'
import csv, json, os, pathlib, time
run_dir = pathlib.Path(os.environ["RUN_OUTPUT_DIR"])
cluster_dir = pathlib.Path(os.environ["CLUSTER_DIR"])
run_dir.mkdir(parents=True, exist_ok=True)
cluster_dir.mkdir(parents=True, exist_ok=True)
status = {{
    "run_id": os.environ.get("RUN_ID"),
    "benchmark": os.environ.get("BENCH_NAME"),
    "returncode": int(os.environ.get("CLUSTER_EXIT_RC", "0")),
    "timestamp": int(time.time()),
    "stdout_path": str(cluster_dir / "entrypoint_stdout.log"),
    "stderr_path": str(cluster_dir / "entrypoint_stderr.log"),
}}
(cluster_dir / "entrypoint_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
summary_jsonl = run_dir / "summary.jsonl"
summary_csv = run_dir / "summary.csv"
if not summary_jsonl.exists():
    row = {{
        "generation_model": "",
        "domain": os.environ.get("BENCH_DOMAIN", ""),
        "harness_task_id": "",
        "harness_path": os.environ.get("GENERATION_OUTPUT", ""),
        "benchmark": os.environ.get("BENCH_NAME", ""),
        "generation_status": "",
        "syntax_ok": "",
        "cli_status": "",
        "eval_status": "failed/cluster_entrypoint",
        "score": "",
        "score_breakdown": json.dumps({{"cluster_returncode": status["returncode"]}}, ensure_ascii=False),
        "pass_rate": "",
        "win_rate": "",
        "reward": "",
        "harness_run_tokens": "",
        "harness_run_interactions": "",
        "generation_tokens": "",
        "missing_dependencies": "",
        "stdout_path": str(cluster_dir / "entrypoint_stdout.log"),
        "stderr_path": str(cluster_dir / "entrypoint_stderr.log"),
        "raw_result_path": str(cluster_dir / "entrypoint_status.json"),
    }}
    summary_jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\\n")
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)
PY
  tar --exclude=cluster_artifacts.tgz -czf "$RUN_OUTPUT_DIR/cluster_artifacts.tgz" -C "$RUN_OUTPUT_DIR" . >/dev/null 2>&1 || true
{upload_block}
  exit "$rc"
}}
trap 'rc=$?; export CLUSTER_EXIT_RC="$rc"; finalize_cluster_artifacts' EXIT

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
export GENERATION_OUTPUT={shlex_quote(generation_output)}

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
{bench_setup}

export PYTHONPATH="$HARNESS_EVAL_ROOT/external_benchmarks/mle-bench:$HARNESS_EVAL_ROOT:${{PYTHONPATH:-}}"

{mle_prepare}
{matrix_setup}

mkdir -p {shlex_quote(output_root)}
"$PYTHON_BIN" run_creation_eval.py \\
  --generation-output {shlex_quote(generation_output)} \\
  --matrix "$MATRIX_PATH" \\
  --bench {shlex_quote(bench)} \\
  --domain {shlex_quote(cfg["domain"])} \\
  --run-id {shlex_quote(run_id)} \\
  --eval-output-root {shlex_quote(output_root)} \\
  --harness-evolve-root "$HARNESS_EVOLVE_ROOT" \\
  --python-bin "$PYTHON_BIN" \\
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


def patch_outputs(job: dict[str, Any], *, output_root: str, run_id: str, output_uri_prefix: str = "") -> None:
    _ = (output_root, run_id, output_uri_prefix)
    # Seed's jobDefVersion.outputs and jobRunParams.outputs are UI/product
    # schemas, not filesystem artifact schemas; they reject sourcePath/targetPath.
    # Cluster artifacts are persisted by the entrypoint itself via optional HDFS
    # upload, so keep both platform output fields empty.
    ensure_nested(job, ["jobDefVersion"])["outputs"] = []
    ensure_nested(job, ["jobRunParams"])["outputs"] = {}


def patch_job(
    template: dict[str, Any],
    *,
    bench: str,
    scenario_id: str,
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
    output_uri_prefix: str,
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
        scenario_id=scenario_id,
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
        output_uri_prefix=output_uri_prefix,
    )
    jd["entrypointFullScript"] = script
    run_params = ensure_nested(job, ["jobRunParams"])
    run_params["entrypointFullScript"] = script
    if not preserve_template_env:
        run_params["envsList"] = {}
    patch_resource(job, BENCH_CONFIG[bench]["resource"])
    patch_outputs(job, output_root=output_root, run_id=run_id, output_uri_prefix=output_uri_prefix)
    return job


def parse_eqbench3_scenario_ids(value: str, harness_evolve_root: Path) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.lower() != "all":
        return [item.strip() for item in value.split(",") if item.strip()]

    scenario_file = (
        harness_evolve_root
        / "writing_harness_eval"
        / "third_party"
        / "eqbench3"
        / "data"
        / "scenario_prompts.txt"
    )
    if not scenario_file.exists():
        raise FileNotFoundError(f"Cannot auto-discover EQBench3 scenarios: {scenario_file}")
    text = scenario_file.read_text(encoding="utf-8", errors="replace")
    ids = re.findall(r"^#{5,}\s*(\d+)\s*\|", text, flags=re.MULTILINE)
    if not ids:
        raise RuntimeError(f"No EQBench3 scenario ids parsed from {scenario_file}")
    return ids


def parse_mle_competition_ids(value: str, harness_eval_root: Path) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.lower() != "all":
        return [item.strip() for item in value.split(",") if item.strip()]

    mle_root = harness_eval_root / "external_benchmarks" / "mle-bench"
    code = """
import json
from mlebench.registry import registry
print(json.dumps(registry.list_competition_ids()))
"""
    out = subprocess.check_output(
        ["python3", "-c", code],
        cwd=mle_root,
        text=True,
        stderr=subprocess.STDOUT,
    )
    ids = json.loads(out.strip().splitlines()[-1])
    if not ids:
        raise RuntimeError(f"No MLE competitions parsed from {mle_root}")
    return [str(item) for item in ids]


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
    parser.add_argument(
        "--preserve-template-env",
        dest="preserve_template_env",
        action="store_true",
        default=True,
        help="Keep envsList from the template job. This is the default so API envs survive template patching.",
    )
    parser.add_argument(
        "--clear-template-env",
        dest="preserve_template_env",
        action="store_false",
        help="Clear template envsList before writing the generated job JSONL.",
    )
    parser.add_argument("--git-branch", default=git_value(["branch", "--show-current"], "codex/platform-native-bmk-shards"))
    parser.add_argument("--git-commit", default=git_value(["rev-parse", "HEAD"], ""))
    parser.add_argument("--dependency-branch", default="")
    parser.add_argument("--dependency-commit", default="")
    parser.add_argument("--eval-model-name", default="glm-5.1")
    parser.add_argument("--eval-reasoning-effort", default="high")
    parser.add_argument("--provider-extra-body-json", default='{"reasoning_effort":"high","thinking":{"type":"enabled"}}')
    parser.add_argument("--provider-strip-max-tokens", default="1")
    parser.add_argument(
        "--eqbench3-scenarios",
        default="",
        help=(
            "Optional comma-separated EQBench3 scenario ids, or 'all' to parse "
            "the local scenario_prompts.txt and emit one job per scenario."
        ),
    )
    parser.add_argument(
        "--mle-competitions",
        default="",
        help=(
            "Optional comma-separated MLE competition ids, or 'all' to emit "
            "one Seed job per registered MLE-bench competition."
        ),
    )
    parser.add_argument(
        "--output-uri-prefix",
        default="",
        help=(
            "Optional persistent URI prefix, for example hdfs://.../harness_eval. "
            "When set, the entrypoint uploads summary files and cluster_artifacts.tgz there."
        ),
    )
    args = parser.parse_args()

    template = read_template(args.template)
    benches = [item.strip() for item in args.benches.split(",") if item.strip()]
    unknown = [bench for bench in benches if bench not in BENCH_CONFIG]
    if unknown:
        raise ValueError(f"unknown bench(es): {unknown}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    harness_evolve_root_local = Path(args.generation_output_root).anchor
    _ = harness_evolve_root_local
    eqbench3_scenarios = parse_eqbench3_scenario_ids(
        args.eqbench3_scenarios,
        Path("/Users/bytedance/Downloads/harness evolve project"),
    ) if args.eqbench3_scenarios else []
    mle_competitions = parse_mle_competition_ids(args.mle_competitions, Path.cwd()) if args.mle_competitions else []

    jobs_written = 0
    with args.output.open("w", encoding="utf-8") as handle:
        for bench in benches:
            cfg = BENCH_CONFIG[bench]
            generation_output = f"{args.generation_output_root.rstrip('/')}/{cfg['task_id']}"
            scenario_ids = [""]
            if bench == "eqbench3" and eqbench3_scenarios:
                scenario_ids = eqbench3_scenarios
            elif bench == "mle_bench" and mle_competitions:
                scenario_ids = mle_competitions
            for scenario_id in scenario_ids:
                scenario_suffix = f"-s{scenario_id}" if scenario_id and bench == "eqbench3" else ""
                if scenario_id and bench == "mle_bench":
                    scenario_suffix = f"-{scenario_id}"
                run_id = f"{args.run_id_prefix}-{bench}{scenario_suffix}"
                job = patch_job(
                    template,
                    bench=bench,
                    scenario_id=scenario_id,
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
                    output_uri_prefix=args.output_uri_prefix,
                )
                handle.write(json.dumps(job, ensure_ascii=False, separators=(",", ":")) + "\n")
                jobs_written += 1
    print(f"Wrote {jobs_written} jobs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
