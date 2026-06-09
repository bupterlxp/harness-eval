#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any


def read_template(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty template: {path}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if line:
                return json.loads(line)
    raise ValueError(f"No JSON object found in {path}")


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSONL row: {exc}") from exc
    return rows


def slug(value: str, max_len: int = 96) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return text[:max_len] or "unknown"


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


def image_meta(
    row: dict[str, Any],
    template: dict[str, Any],
    allow_template_image: bool,
    require_direct_image: bool,
) -> dict[str, Any]:
    explicit = row.get("imageMeta") or row.get("image_meta")
    if isinstance(explicit, dict):
        meta = dict(explicit)
    else:
        meta = {
            "imageSid": row.get("imageSid") or row.get("image_sid") or "",
            "imageVid": row.get("imageVid") or row.get("image_vid") or row.get("image") or "",
            "imageSource": (
                row.get("imageSource")
                or row.get("image_source")
                or ("vid" if (row.get("imageVid") or row.get("image_vid") or row.get("image")) else "")
                or ("icm" if (row.get("icmName") or row.get("icm_name") or row.get("icmVersion") or row.get("icm_version")) else "")
            ),
            "needBuild": bool(row.get("needBuild") or row.get("need_build") or False),
            "icmName": row.get("icmName") or row.get("icm_name") or "",
            "icmVersion": row.get("icmVersion") or row.get("icm_version") or "",
        }
    has_image = any(str(meta.get(key) or "") for key in ("imageSid", "imageVid", "icmName", "icmVersion"))
    if not has_image:
        if allow_template_image:
            return copy.deepcopy(get_nested(template, ["jobDefVersion", "imageMeta"], {}))
        raise ValueError(
            "Instance row is missing image mapping. Provide imageMeta/imageVid/imageSid/icmName, "
            "or pass --allow-template-image."
        )
    meta.setdefault("imageSid", "")
    meta.setdefault("imageVid", "")
    if not meta.get("imageSource"):
        meta["imageSource"] = "vid" if meta.get("imageVid") else "icm"
    meta.setdefault("needBuild", False)
    meta.setdefault("icmName", "")
    meta.setdefault("icmVersion", "")
    if require_direct_image:
        if meta.get("imageSource") != "vid" or not str(meta.get("imageVid") or "").strip():
            instance_id = row.get("instance_id") or row.get("task_id") or "unknown"
            raise ValueError(
                f"{instance_id}: direct runnable platform image required. "
                "Use imageSource='vid' with a non-empty imageVid; icmName/icmVersion "
                "can trigger service-image build and is intentionally rejected."
            )
        meta["needBuild"] = False
        meta["icmName"] = ""
        meta["icmVersion"] = ""
    return meta


def platform_image_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Convert local camelCase imageMeta to Seed's persisted image_meta shape."""
    return {
        "image_sid": str(meta.get("imageSid") or meta.get("image_sid") or ""),
        "image_vid": str(meta.get("imageVid") or meta.get("image_vid") or ""),
        "image_source": str(meta.get("imageSource") or meta.get("image_source") or ""),
        "need_build": bool(meta.get("needBuild") or meta.get("need_build") or False),
        "icm_name": str(meta.get("icmName") or meta.get("icm_name") or ""),
        "icm_version": str(meta.get("icmVersion") or meta.get("icm_version") or ""),
        "image_url": str(meta.get("imageUrl") or meta.get("image_url") or ""),
        "task_id": int(meta.get("taskId") or meta.get("task_id") or 0),
    }


def render_entrypoint(
    *,
    instance: dict[str, Any],
    benchmark: str,
    harness_path: str,
    run_id: str,
    harness_eval_root: str,
    harness_evolve_root: str,
    output_root: str,
    install_deps: bool,
) -> str:
    instance_id = slug(str(instance.get("instance_id") or instance.get("task_id") or "unknown"))
    instance_json = json.dumps(instance, ensure_ascii=False, indent=2)
    setup = ""
    if install_deps:
        setup = r'''
if ! command -v node >/dev/null 2>&1; then
  echo "[setup] node is missing; installing nodejs/npm"
  if command -v sudo >/dev/null 2>&1; then
    SUDO=sudo
  else
    SUDO=
  fi
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get update
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs npm
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
'''
    else:
        setup = r'''
if [ -d .venv ]; then
  . .venv/bin/activate
fi
'''
    return f'''set -euo pipefail

cd {shlex_quote(harness_eval_root)}

export PATH="$HOME/.local/bin:$PATH"
export HARNESS_EVAL_ROOT={shlex_quote(harness_eval_root)}
export HARNESS_EVOLVE_ROOT={shlex_quote(harness_evolve_root)}
export PYTHONUNBUFFERED=1
export PROVIDER_STRIP_MAX_TOKENS=1
export PROVIDER_EXTRA_BODY_JSON='{{"reasoning_effort":"high","thinking":{{"type":"enabled"}}}}'
export EVAL_MODEL_NAME="${{EVAL_MODEL_NAME:-glm-5.1}}"
export EVAL_REASONING_EFFORT="${{EVAL_REASONING_EFFORT:-high}}"
export EVAL_PROVIDER_PROXY_PORT="${{EVAL_PROVIDER_PROXY_PORT:-4568}}"

if [ -n "${{GLM_API_KEY:-}}" ] && [ -z "${{EVAL_API_KEY:-}}" ]; then
  export EVAL_API_KEY="$GLM_API_KEY"
fi
if [ -n "${{GLM_API_KEY:-}}" ] && [ -z "${{EVAL_BASE_URL:-}}" ]; then
  export EVAL_BASE_URL="https://aidp.bytedance.net/api/modelhub/online/v2/crawl?ak=${{GLM_API_KEY}}"
fi
if [ -z "${{EVAL_BASE_URL:-}}" ] || [ -z "${{EVAL_API_KEY:-}}" ]; then
  echo "ERROR: set EVAL_BASE_URL/EVAL_API_KEY, or set GLM_API_KEY for the GLM crawl endpoint."
  exit 2
fi

if [ ! -d {shlex_quote(harness_path)} ]; then
  echo "ERROR: missing generated harness artifact: {harness_path}"
  exit 2
fi

{setup}

mkdir -p {shlex_quote(output_root)}/{shlex_quote(run_id)}/{shlex_quote(instance_id)}
cat > {shlex_quote(output_root)}/{shlex_quote(run_id)}/{shlex_quote(instance_id)}/instance.json <<'JSON'
{instance_json}
JSON

PYTHON_BIN="${{PYTHON_BIN:-.venv/bin/python}}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" tools/run_platform_bmk_shard.py \\
  --benchmark {shlex_quote(benchmark)} \\
  --instance-json {shlex_quote(output_root)}/{shlex_quote(run_id)}/{shlex_quote(instance_id)}/instance.json \\
  --harness-path {shlex_quote(harness_path)} \\
  --domain code \\
  --output-dir {shlex_quote(output_root)}/{shlex_quote(run_id)}/{shlex_quote(instance_id)} \\
  --python-bin "$PYTHON_BIN" \\
  --timeout-seconds "${{BMK_TIMEOUT_SECONDS:-604800}}" \\
  --eval-base-url "$EVAL_BASE_URL" \\
  --eval-api-key "$EVAL_API_KEY" \\
  --eval-model-name "$EVAL_MODEL_NAME" \\
  --eval-reasoning-effort "$EVAL_REASONING_EFFORT" \\
  --eval-provider-proxy-port "$EVAL_PROVIDER_PROXY_PORT" \\
  --run-id {shlex_quote(run_id)}

echo "DONE shard: {benchmark}/{instance_id}"
echo "result: {output_root}/{run_id}/{instance_id}/shard_result.json"
'''


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def patch_resource(job: dict[str, Any], row: dict[str, Any]) -> None:
    resource = row.get("resource")
    if not isinstance(resource, dict):
        return
    arnold = get_nested(job, ["jobRunParams", "resource", "arnoldConfig"], {})
    if not isinstance(arnold, dict):
        return
    for key in ("clusterName", "clusterId", "groupIds", "multiResourcePool"):
        if key in resource:
            arnold[key] = resource[key]
    roles = arnold.get("roles")
    if isinstance(roles, list) and roles:
        role = roles[0]
        for key in ("cpu", "memory", "gpu", "gpuv", "queueName", "num"):
            if key in resource:
                role[key] = resource[key]
    job_def_resource = ensure_nested(job, ["jobDefVersion", "resource"])
    if "cpu" in resource:
        job_def_resource["cpu"] = resource["cpu"]
    if "memory" in resource:
        job_def_resource["memory"] = resource["memory"]
    if "gpu" in resource:
        job_def_resource["gpu"] = resource["gpu"]


def patch_env(job: dict[str, Any], row: dict[str, Any], preserve_template_env: bool) -> None:
    run_params = ensure_nested(job, ["jobRunParams"])
    envs = dict(run_params.get("envsList") or {}) if preserve_template_env else {}
    row_env = row.get("env")
    if isinstance(row_env, dict):
        envs.update({str(k): str(v) for k, v in row_env.items()})
    # Instance identity is safe and useful in the platform UI.
    for source, env_name in [
        ("benchmark", "BMK_BENCHMARK"),
        ("instance_id", "BMK_INSTANCE_ID"),
        ("repo", "BMK_REPO"),
        ("repo_family", "BMK_REPO_FAMILY"),
    ]:
        value = row.get(source)
        if value is not None:
            envs[env_name] = str(value)
    run_params["envsList"] = envs


def patch_job(
    template: dict[str, Any],
    row: dict[str, Any],
    *,
    benchmark: str,
    harness_path: str,
    run_id: str,
    output_root: str,
    allow_template_image: bool,
    require_direct_image: bool,
    preserve_template_env: bool,
    install_deps: bool,
) -> dict[str, Any]:
    job = copy.deepcopy(template)
    instance_id = slug(str(row.get("instance_id") or row.get("task_id") or "unknown"))
    repo_family = slug(str(row.get("repo_family") or row.get("repo") or "repo"))
    default_caption = slug(f"he-{benchmark}-{repo_family}-{instance_id}", max_len=88)
    caption = slug(str(row.get("caption") or default_caption), max_len=88)
    job["caption"] = str(caption)
    jd = ensure_nested(job, ["jobDefVersion"])
    main_mnt = str(get_nested(job, ["jobDefVersion", "gitRepo", "mnt"], "/opt/tiger/Harness_evolve"))
    subrepos = jd.get("subRepos") if isinstance(jd.get("subRepos"), list) else []
    evolve_root = str(subrepos[0].get("mnt")) if subrepos and isinstance(subrepos[0], dict) and subrepos[0].get("mnt") else "/opt/tiger/harness_evolve_project"
    meta = image_meta(row, template, allow_template_image, require_direct_image)
    jd["imageMeta"] = meta
    jd["image_meta"] = platform_image_meta(meta)
    jd["entrypointMode"] = "FULL_SCRIPT"
    jd["name"] = str(caption)
    script = render_entrypoint(
        instance=row | {"benchmark": benchmark},
        benchmark=benchmark,
        harness_path=harness_path,
        run_id=run_id,
        harness_eval_root=main_mnt,
        harness_evolve_root=evolve_root,
        output_root=output_root,
        install_deps=install_deps,
    )
    jd["entrypointFullScript"] = script
    run_params = ensure_nested(job, ["jobRunParams"])
    run_params["entrypointFullScript"] = script
    patch_env(job, row | {"benchmark": benchmark}, preserve_template_env)
    patch_resource(job, row)
    return job


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Seed/Arnold job JSONL for platform-native BMK shards. "
            "Each output line is one compressed JSON object."
        )
    )
    parser.add_argument("--template", type=Path, required=True, help="Pretty JSON or single-line JSONL task template.")
    parser.add_argument("--instances", type=Path, required=True, help="JSONL instance-to-image manifest.")
    parser.add_argument("--output", type=Path, required=True, help="Output job JSONL; one job per line.")
    parser.add_argument("--benchmark", required=True, choices=["swebench_pro", "terminal_2_bench"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--harness-path",
        default="/opt/tiger/Harness_evolve/outputs/creation-code-glm51-high-nomax-20260605-181801/code-agent-harness",
    )
    parser.add_argument("--output-root", default="/opt/tiger/Harness_evolve/platform_eval_results")
    parser.add_argument("--allow-template-image", action="store_true")
    parser.add_argument(
        "--require-direct-image",
        action="store_true",
        help=(
            "Reject rows unless imageMeta resolves to imageSource=vid and a non-empty imageVid. "
            "Use this for full platform-native runs to avoid accidental service-image builds."
        ),
    )
    parser.add_argument("--preserve-template-env", action="store_true", help="Keep envsList from template. Use only for local/private JSONL with secrets.")
    parser.add_argument("--no-install-deps", action="store_true", help="Assume image already has venv/deps installed.")
    args = parser.parse_args()

    template = read_template(args.template)
    rows = iter_jsonl(args.instances)
    if not rows:
        raise ValueError(f"No instance rows found in {args.instances}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            job = patch_job(
                template,
                row,
                benchmark=args.benchmark,
                harness_path=args.harness_path,
                run_id=args.run_id,
                output_root=args.output_root,
                allow_template_image=args.allow_template_image,
                require_direct_image=args.require_direct_image,
                preserve_template_env=args.preserve_template_env,
                install_deps=not args.no_install_deps,
            )
            handle.write(json.dumps(job, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(rows)} jobs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
