# Platform-native BMK eval shards

This path is for Seed/Arnold task platforms that cannot run Docker-in-Docker.
Instead of launching Docker inside one eval task, the platform launches one task
container per benchmark instance or repo family. The task image must already be
the prepared environment for that instance or repo family.

## What This Solves

The existing `swebench_pro` and `terminal_2_bench` runners use Docker:

- SWE-bench Pro: `uv run swebench-infer --workspace docker`, then `swebench-eval`.
- Terminal 2.0: `harbor run`, then `terminalbench-eval`.

Those runners fail on Seed tasks when the container cannot access a Docker
daemon. The platform-native path avoids Docker entirely.

## Required Inputs

1. A generated harness artifact, for example:

```text
/opt/tiger/Harness_evolve/outputs/creation-code-glm51-high-nomax-20260605-181801/code-agent-harness
```

2. A Seed job template JSON or JSONL, copied from the UI.

3. An instance manifest JSONL. Each row maps an instance or repo family to a
prebuilt task image:

```json
{"benchmark":"swebench_pro","instance_id":"django__django-00000","repo":"django/django","repo_family":"django","imageVid":"...","imageSource":"vid","task_work_dir":"/workspace","problem_statement":"...","verify_cmd":"python -m pytest -q tests/example.py"}
```

Fields:

- `benchmark`: `swebench_pro` or `terminal_2_bench`.
- `instance_id`: unique instance id.
- `repo` / `repo_family`: used for reporting and task naming.
- `imageVid`, `imageSid`, `icmName` + `icmVersion`, or `imageMeta`: the prebuilt image to run.
- `task_work_dir`: repository/task directory inside the prebuilt image.
- `problem_statement` or `task_prompt`: public task text shown to the generated harness.
- `verify_cmd`: optional public/dev verifier command inside the image.
- `resource`: optional per-row CPU/memory/queue override.

Do not put hidden labels, hidden patches, or hidden answers in this manifest.

## Generate One-line Job JSONL

The generator accepts a pretty JSON template or a one-line JSONL template and
always writes one compressed JSON object per output line:

```bash
cd /opt/tiger/Harness_evolve

python tools/generate_platform_bmk_jobs.py \
  --template outputs/platform_jobs/template.seed_job.json \
  --instances configs/platform_bmk_instances.swepro.jsonl \
  --output outputs/platform_jobs/swepro_glm51_jobs.jsonl \
  --benchmark swebench_pro \
  --run-id swepro-glm51-platform-$(date +%Y%m%d-%H%M%S) \
  --harness-path /opt/tiger/Harness_evolve/outputs/creation-code-glm51-high-nomax-20260605-181801/code-agent-harness
```

If you want to keep env vars from the UI template, pass:

```bash
--preserve-template-env
```

Only use that for local/private files, because it can copy API keys into the
generated JSONL.

If you only want to test with the template image instead of per-instance image
rows:

```bash
--allow-template-image
```

## Submit Jobs

The submit helper follows the same pattern as `RAY_TAGGING/submit/submit_tasks.py`:
successful rows are removed from the pending JSONL and recorded in watch/events
files.

```bash
export SEC_TOKEN_PATH=/path/to/sec_token

python tools/submit_seed_job_jsonl.py \
  --tasks outputs/platform_jobs/swepro_glm51_jobs.jsonl \
  --watch outputs/platform_jobs/watch_tasks.jsonl \
  --events outputs/platform_jobs/events.jsonl
```

## Container Entrypoint Behavior

Each generated job runs:

```bash
python tools/run_platform_bmk_shard.py \
  --benchmark swebench_pro \
  --instance-json <written by entrypoint> \
  --harness-path <generated harness artifact> \
  --domain code \
  --adapter-mode strict \
  --eval-model-name glm-5.1 \
  --eval-reasoning-effort high
```

The runner:

1. starts the local eval provider proxy for GLM/other crawl-style endpoints;
2. calls the generated harness in strict adapter mode;
3. lets the harness edit the current task repo;
4. writes `prediction.patch` from `git diff --binary`;
5. runs `verify_cmd` if provided;
6. writes `shard_result.json` and `shard_result.jsonl`.

If no verifier is provided, the shard status is `success/no_verifier` and the
patch/logs are preserved for external scoring.

## Merge Results

After task outputs are copied back under one directory:

```bash
python tools/merge_platform_bmk_shards.py \
  --root platform_eval_results/swepro-glm51-platform-20260608-000000 \
  --out-jsonl platform_eval_results/swepro-glm51-platform-20260608-000000/summary.jsonl \
  --out-csv platform_eval_results/swepro-glm51-platform-20260608-000000/summary.csv
```

## Important Semantics

This path is not the same as the Docker runner unless the prebuilt image and
`verify_cmd` exactly reproduce the official instance environment and verifier.
It is the no-DinD execution strategy:

```text
platform task image = instance/repo-family environment
generated harness + eval LLM = agent under test
verify_cmd or external scorer = BMK score source
```

Use the Docker runner on a DevBox with Docker socket when you need the closest
official SWE/Terminal semantics. Use this platform-native shard path when the
online task platform cannot run Docker.

