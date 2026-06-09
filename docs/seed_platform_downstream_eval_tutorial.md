# Seed 平台批量运行 Generated Harness 下游 BMK 教程

本文从一个已经创建好的 generated harness 出发，教你把它批量送到 Seed/Arnold 任务平台的任务容器里跑 downstream benchmark eval。

目标读者：没有接触过 Seed 平台、不了解 Harness-Evolve 项目、代码基础较弱的人。你只需要按步骤替换路径、模型名和环境变量即可。

本文不讲 harness creation。它默认你已经有一个可用的 harness artifact，例如：

```text
generated_harnesses/gpt55/modelhub-full-20260608/writing-harness
generated_harnesses/gpt55/modelhub-full-20260608/data-analysis-harness
generated_harnesses/glm51/high-devfeedback-20260608/code-agent-harness
```

## 1. 先理解四个概念

### 1.1 Generated harness

Generated harness 是模型创建出来的“任务执行框架”。下游 BMK eval 时，我们不是直接测模型裸能力，而是测：

```text
generated harness + eval LLM
```

例如：

```text
GLM 生成的 code harness + GLM 5.1 high -> SWE Pro
GPT-5.5 生成的 writing harness + GPT-5.5 -> EQBench3
```

### 1.2 任务容器

Seed/Arnold 平台上每一条任务都会启动一个容器。容器里会挂载你的主仓库和依赖仓库，然后执行一段入口脚本。

你在 Mac 上看到的路径，例如：

```text
/Users/bytedance/Downloads/harness-eval
```

在任务容器里通常不是这个路径，而是类似：

```text
/opt/tiger/Harness_evolve
/opt/tiger/harness_evolve_project
```

所以生成 job JSONL 时，必须填写“容器内路径”，不是本地 Mac 路径。

### 1.3 Job JSONL

Job JSONL 是提交给 Seed 平台的任务列表文件。每一行是一个完整 JSON object，代表一个平台任务。

例如：

```text
logs/platform_jobs/modelhub_noncode/gpt55_noncode_full_jobs.private.jsonl
```

注意：

- 每一行必须是单行 JSON。
- 私有版 JSONL 可能包含环境变量名或密钥值，不能提交到 Git。
- 公共版可以叫 `*.no_secret.jsonl`，里面不应该包含真实 API key。

### 1.4 Watch / Events 文件

提交任务后，脚本会写两个跟踪文件：

```text
watch.jsonl
events.jsonl
```

- `watch.jsonl`：记录已经提交成功的平台任务 ID。
- `events.jsonl`：记录提交、跳过、失败等事件。

后面查状态、补跑失败任务，都靠这两个文件。

## 2. 两种下游 BMK 运行方式

当前项目里有两条批量运行链路。

### 2.1 普通任务容器链路

适合不需要 Docker-in-Docker 的 BMK：

```text
MLE-bench
EQBench3
BrowseComp
```

特点：

- 一个 BMK 通常一个任务容器。
- 容器里直接运行 `run_creation_eval.py`。
- 任务容器会安装依赖、准备数据、调用 generated harness、调用 eval LLM。

使用脚本：

```text
tools/generate_noncode_bmk_jobs.py
tools/submit_seed_job_jsonl.py
tools/submit_seed_job_jsonl_batched.py
```

### 2.2 Platform-native shard 链路

适合原始 runner 依赖 Docker 的 BMK：

```text
SWE-bench Pro
Terminal 2.0
```

Seed 平台任务容器不能稳定运行 Docker-in-Docker，所以这里不在容器里再起 Docker。做法是：

```text
每个 benchmark instance 对应一个已经准备好的平台镜像。
平台直接启动这个镜像。
容器内只运行 generated harness + eval LLM。
```

特点：

- 一行 job JSONL 通常对应一个 SWE/Terminal instance。
- 全量 SWE Pro 可能是几百个任务容器。
- 必须有 `imageSource=vid` 和非空 `imageVid`。
- 不要用未解析的 `icmName/icmVersion` 直接跑全量，否则可能误触发平台构建镜像并失败。

使用脚本：

```text
tools/generate_platform_bmk_jobs.py
tools/validate_platform_direct_images.py
tools/submit_seed_job_jsonl_batched.py
tools/merge_platform_bmk_shards.py
```

## 3. 准备工作

### 3.1 确认本地仓库

本地操作都在：

```bash
cd "/Users/bytedance/Downloads/harness-eval"
git status -sb
```

如果本机没有 `python` 命令，使用：

```bash
.venv/bin/python
```

不要在教程命令里随手写裸 `python`。

### 3.2 确认任务容器里的仓库路径

平台任务通常挂载两个仓库。

主仓库：

```text
repo: zhangjingyuan.seed/Harness_evolve
container path: /opt/tiger/Harness_evolve
```

依赖仓库：

```text
repo: zhangjingyuan.seed/harness_evolve_benchmarks
container path: /opt/tiger/harness_evolve_project
```

主仓库放运行脚本：

```text
run_creation_eval.py
tools/
creation_eval/
eval_matrix.yaml
```

依赖仓库放 benchmark 依赖和 generated harness artifacts：

```text
external_benchmarks/
generated_harnesses/
```

### 3.3 确认 generated harness 在容器里能看见

如果 harness 放在依赖仓库里，容器路径通常类似：

```text
/opt/tiger/harness_evolve_project/generated_harnesses/gpt55/modelhub-full-20260608
```

这个目录下面应该有各个任务类型：

```text
data-analysis-harness/
writing-harness/
research-agent-harness/
code-agent-harness/
```

普通 BMK 任务生成器会自动按 BMK 找子目录：

| BMK | 自动使用的 harness 子目录 |
|---|---|
| `mle_bench` | `data-analysis-harness` |
| `eqbench3` | `writing-harness` |
| `browsecomp` | `research-agent-harness` |

### 3.4 准备平台任务模板

任务模板是一个从 Seed UI 或已有成功任务里复制出的 JSON 文件。它保存：

- 主仓库；
- 依赖仓库；
- 镜像；
- 资源配置；
- 环境变量；
- 入口脚本模式。

常见模板路径示例：

```text
logs/platform_jobs/swepro_glm51_template.current.json
```

如果你没有模板，先在 Seed UI 里手动创建一个最小任务：

1. 选择主仓库 `zhangjingyuan.seed/Harness_evolve`。
2. 选择正确分支和 commit。
3. 添加依赖仓库 `zhangjingyuan.seed/harness_evolve_benchmarks`。
4. 选择一个能启动的基础镜像。
5. 填一个简单入口命令，例如 `echo hello && sleep 10`。
6. 成功运行后，把这个任务的 JSON 请求体保存成本地模板。

后续批量任务都会基于这个模板自动改入口脚本和资源。

### 3.5 准备 API key，但不要写进 Git

下游 eval 要调用 LLM API。推荐只在私有任务 JSONL 或平台环境变量里传：

```text
MODELHUB_AK
GLM_API_KEY
EVAL_BASE_URL
EVAL_API_KEY
KAGGLE_JSON_B64
KAGGLE_USERNAME
KAGGLE_KEY
```

规则：

- 不要把真实 key 写进 README、docs、tracked config。
- 不要提交 `*.private.jsonl`。
- 可以生成 `*.no_secret.jsonl` 给别人 review 任务结构。

## 4. 跑普通 BMK：MLE / EQBench3 / BrowseComp

这一节适合：

```text
data-analysis-harness -> MLE-bench
writing-harness -> EQBench3
research-agent-harness -> BrowseComp
```

### 4.1 生成 job JSONL

示例：使用 GPT-5.5 生成的三类 harness，并用 GPT-5.5 作为 eval LLM 跑全量普通 BMK。

```bash
cd "/Users/bytedance/Downloads/harness-eval"

RUN_PREFIX="gpt55-noncode-full-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_noncode_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --output "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  --benches mle_bench,eqbench3,browsecomp \
  --run-id-prefix "$RUN_PREFIX" \
  --generation-output-root "/opt/tiger/harness_evolve_project/generated_harnesses/gpt55/modelhub-full-20260608" \
  --output-root "/opt/tiger/Harness_evolve/eval_results/cluster_full" \
  --python-bin "python3" \
  --dependency-branch "gpt55-generated-harnesses-20260608" \
  --dependency-commit "<dependency_repo_commit>" \
  --eval-model-name "gpt-5.5-2026-04-24" \
  --eval-reasoning-effort "high" \
  --provider-strip-max-tokens "1"
```

如果是 Gemini：

```bash
RUN_PREFIX="gemini31-noncode-full-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_noncode_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --output "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  --benches mle_bench,eqbench3,browsecomp \
  --run-id-prefix "$RUN_PREFIX" \
  --generation-output-root "/opt/tiger/harness_evolve_project/generated_harnesses/gemini31/modelhub-full-20260608" \
  --output-root "/opt/tiger/Harness_evolve/eval_results/cluster_full" \
  --python-bin "python3" \
  --dependency-branch "<dependency_branch_with_gemini_harnesses>" \
  --dependency-commit "<dependency_repo_commit>" \
  --eval-model-name "gemini-3.1-p" \
  --eval-reasoning-effort "high" \
  --provider-extra-body-json '{"use_search_gpt":true,"thinking":{"include_thoughts":false,"budget_tokens":2000}}' \
  --provider-strip-max-tokens "1"
```

如果是 GLM 5.1 high：

```bash
RUN_PREFIX="glm51-noncode-full-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_noncode_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --output "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  --benches mle_bench,eqbench3,browsecomp \
  --run-id-prefix "$RUN_PREFIX" \
  --generation-output-root "/opt/tiger/harness_evolve_project/generated_harnesses/glm51/high-devfeedback-20260608" \
  --output-root "/opt/tiger/Harness_evolve/eval_results/cluster_full" \
  --python-bin "python3" \
  --eval-model-name "glm-5.1" \
  --eval-reasoning-effort "high" \
  --provider-extra-body-json '{"reasoning_effort":"high","thinking":{"type":"enabled"}}' \
  --provider-strip-max-tokens "1"
```

说明：

- `--generation-output-root` 是容器内路径，不是 Mac 本地路径。
- `--benches mle_bench,eqbench3,browsecomp` 会生成 3 行任务。
- 每一行是一个完整 BMK eval 任务。
- `mle_bench` 会尝试准备 Kaggle 数据，需要 Kaggle 凭据或已经挂载好的数据目录。

### 4.2 检查 job JSONL 是否是单行 JSONL

```bash
wc -l "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl"

export JOB_JSONL="logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl"
.venv/bin/python - <<'PY'
import json, os, pathlib
path = pathlib.Path(os.environ["JOB_JSONL"])
for i, line in enumerate(path.read_text().splitlines(), 1):
    json.loads(line)
print("ok:", path)
PY
```

如果解析失败，说明 JSONL 不是合法单行 JSON，不能提交。

### 4.3 把任务文件和提交脚本同步到开发机

开发机示例：

```text
121399.zhangjingyuan-seed.ws@ssh-candy-wlby.workspace.byted.org
```

同步：

```bash
REMOTE="121399.zhangjingyuan-seed.ws@ssh-candy-wlby.workspace.byted.org"
REMOTE_DIR="/home/tiger/harness_eval_submit"

ssh "$REMOTE" "mkdir -p $REMOTE_DIR/modelhub_noncode"

rsync -av tools/submit_seed_job_jsonl.py \
  tools/submit_seed_job_jsonl_batched.py \
  "$REMOTE:$REMOTE_DIR/"

rsync -av "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  "$REMOTE:$REMOTE_DIR/modelhub_noncode/"
```

### 4.4 在开发机提交任务

普通 BMK 只有 3 行任务，可以直接提交，也可以用 batched submitter。

```bash
ssh "$REMOTE"

cd /home/tiger/harness_eval_submit

python3 submit_seed_job_jsonl.py \
  --tasks "modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  --watch "modelhub_noncode/${RUN_PREFIX}.watch.jsonl" \
  --events "modelhub_noncode/${RUN_PREFIX}.events.jsonl" \
  --sleep-seconds 1
```

提交成功后，`private.jsonl` 里的成功行会被移除，提交记录会写到：

```text
modelhub_noncode/<run_prefix>.watch.jsonl
modelhub_noncode/<run_prefix>.events.jsonl
```

### 4.5 查看结果

任务完成后，结果在容器内：

```text
/opt/tiger/Harness_evolve/eval_results/cluster_full/<run_id>/summary.csv
/opt/tiger/Harness_evolve/eval_results/cluster_full/<run_id>/summary.jsonl
```

如果 job 里设置了 `--output-uri-prefix`，入口脚本还会把：

```text
summary.csv
summary.jsonl
cluster_artifacts.tgz
```

上传到对应 HDFS 路径。

如果没有设置 HDFS，需要从平台日志、容器产物或任务挂载盘里取结果。

## 5. 跑 SWE Pro / Terminal 2.0：Platform-native shard

这一节适合：

```text
code-agent-harness -> SWE-bench Pro
code-agent-harness -> Terminal 2.0
```

### 5.1 为什么不能直接用普通 Docker runner

SWE Pro 和 Terminal 2.0 原始 runner 通常会在 eval 过程中启动 Docker。如果 Seed 任务平台不支持 Docker-in-Docker，这会失败。

所以这里使用 platform-native 方案：

```text
一个 instance 一个平台任务容器。
这个容器的镜像本身就是该 instance 的环境。
容器里不再启动 Docker。
```

### 5.2 准备 instance manifest

manifest 是一个 JSONL，每行一个 instance。

示例字段：

```json
{"benchmark":"swebench_pro","instance_id":"django__django-00000","repo":"django/django","repo_family":"django","imageVid":"...","imageSource":"vid","task_work_dir":"/workspace","problem_statement":"...","verify_cmd":"python -m pytest -q tests/example.py","resource":{"cpu":8,"memory":32768,"gpu":0,"gpuv":"CPU_ONLY"}}
```

关键要求：

- `imageSource` 必须是 `vid`。
- `imageVid` 必须非空。
- `needBuild` 必须是 `false`。
- 不要使用未解析的 `icmName/icmVersion` 跑正式全量。

验证：

```bash
.venv/bin/python tools/validate_platform_direct_images.py \
  configs/platform_bmk_instances.swepro.vid.jsonl \
  --expected-count 731 \
  --check-direct-image \
  --check-no-secrets
```

如果这里失败，先修 manifest，不要提交任务。

### 5.3 生成 SWE Pro job JSONL

```bash
RUN_ID="swepro-glm51-platform-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_platform_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --instances configs/platform_bmk_instances.swepro.vid.jsonl \
  --output "logs/platform_jobs/${RUN_ID}.private.jsonl" \
  --benchmark swebench_pro \
  --run-id "$RUN_ID" \
  --harness-path "/opt/tiger/harness_evolve_project/generated_harnesses/glm51/high-devfeedback-20260608/code-agent-harness" \
  --output-root "/opt/tiger/Harness_evolve/platform_eval_results" \
  --require-direct-image \
  --preserve-template-env
```

说明：

- `--harness-path` 仍然是容器内路径。
- `--require-direct-image` 会强制检查每行都有直接可运行的 `imageVid`。
- `--preserve-template-env` 会保留模板里的环境变量。只有私有 JSONL 可以这么做。

### 5.4 先提交 1 个 probe

全量 SWE Pro 一次可能有几百行。不要一上来全提交，先跑 1 行。

```bash
REMOTE="121399.zhangjingyuan-seed.ws@ssh-candy-wlby.workspace.byted.org"
REMOTE_DIR="/home/tiger/harness_eval_submit"

ssh "$REMOTE" "mkdir -p $REMOTE_DIR/swepro"

rsync -av tools/submit_seed_job_jsonl.py \
  tools/submit_seed_job_jsonl_batched.py \
  "$REMOTE:$REMOTE_DIR/"

rsync -av "logs/platform_jobs/${RUN_ID}.private.jsonl" \
  "$REMOTE:$REMOTE_DIR/swepro/"

ssh "$REMOTE"
cd /home/tiger/harness_eval_submit

python3 submit_seed_job_jsonl_batched.py \
  --tasks "swepro/${RUN_ID}.private.jsonl" \
  --watch "swepro/${RUN_ID}.probe.watch.jsonl" \
  --events "swepro/${RUN_ID}.probe.events.jsonl" \
  --max-active 1 \
  --max-submit 1 \
  --poll-seconds 60 \
  --submit-sleep-seconds 1
```

probe 通过的最低标准：

- Seed UI 里任务真正启动了容器；
- 不是启动前就失败；
- 日志里能看到 `run_platform_bmk_shard.py` 或入口脚本输出；
- 没有 `base_image in service config must be completed when build service image`。

如果 probe 没过，不要全量提交。

### 5.5 全量提交，限制并发

probe 过了以后，使用同一个任务 JSONL 继续提交剩余行。建议并发先用 32。

```bash
python3 submit_seed_job_jsonl_batched.py \
  --tasks "swepro/${RUN_ID}.private.jsonl" \
  --watch "swepro/${RUN_ID}.watch.jsonl" \
  --events "swepro/${RUN_ID}.events.jsonl" \
  --max-active 32 \
  --poll-seconds 60 \
  --submit-sleep-seconds 1
```

如果资源排队严重，可以把 `--max-active` 降到 16。如果平台很稳定，再考虑升到 64。

### 5.6 合并 shard 结果

所有 shard 完成后，把结果目录汇总：

```bash
.venv/bin/python tools/merge_platform_bmk_shards.py \
  --root "platform_eval_results/${RUN_ID}" \
  --out-jsonl "platform_eval_results/${RUN_ID}/summary.jsonl" \
  --out-csv "platform_eval_results/${RUN_ID}/summary.csv"
```

最终看：

```text
platform_eval_results/<run_id>/summary.csv
platform_eval_results/<run_id>/summary.jsonl
```

## 6. 如何选择 eval LLM

### 6.1 GLM 5.1 high

平台环境变量建议：

```text
GLM_API_KEY=<放在私有环境变量里>
EVAL_MODEL_NAME=glm-5.1
EVAL_REASONING_EFFORT=high
```

普通 BMK generator 中可写：

```bash
--eval-model-name "glm-5.1" \
--eval-reasoning-effort "high" \
--provider-extra-body-json '{"reasoning_effort":"high","thinking":{"type":"enabled"}}' \
--provider-strip-max-tokens "1"
```

### 6.2 GPT-5.5

平台环境变量建议：

```text
MODELHUB_AK=<放在私有环境变量里>
EVAL_MODEL_NAME=gpt-5.5-2026-04-24
EVAL_REASONING_EFFORT=high
```

普通 BMK generator 中可写：

```bash
--eval-model-name "gpt-5.5-2026-04-24" \
--eval-reasoning-effort "high" \
--provider-strip-max-tokens "1"
```

### 6.3 Gemini 3.1 Pro

平台环境变量建议：

```text
MODELHUB_AK=<放在私有环境变量里>
EVAL_MODEL_NAME=gemini-3.1-p
EVAL_REASONING_EFFORT=high
```

普通 BMK generator 中可写：

```bash
--eval-model-name "gemini-3.1-p" \
--eval-reasoning-effort "high" \
--provider-extra-body-json '{"use_search_gpt":true,"thinking":{"include_thoughts":false,"budget_tokens":2000}}' \
--provider-strip-max-tokens "1"
```

## 7. 新人最容易犯的错误

### 错误 1：把 Mac 本地路径写进 job

错误：

```text
/Users/bytedance/Downloads/harness-eval/outputs/...
```

正确：

```text
/opt/tiger/Harness_evolve/outputs/...
/opt/tiger/harness_evolve_project/generated_harnesses/...
```

任务容器看不到 Mac 本地路径。

### 错误 2：把真实 API key 提交进 Git

错误做法：

```text
把 *.private.jsonl commit 到仓库
```

正确做法：

```text
private JSONL 只放本地或开发机
公共 review 只用 *.no_secret.jsonl
真实 key 走平台环境变量
```

### 错误 3：SWE Pro 用 icmName/icmVersion 直接跑全量

这可能触发平台 build service image，启动前失败：

```text
base_image in service config must be completed when build service image
```

正式 platform-native SWE Pro 必须先变成：

```text
imageSource=vid
imageVid=<non-empty>
needBuild=false
```

### 错误 4：没有先跑 probe

全量任务之前一定先跑 1 个 probe。probe 不过就全量提交，只会批量失败。

### 错误 5：把 submission 成功等同于 BMK 成功

任务提交成功只表示 Seed 接收了 job。真正成功要看：

```text
summary.csv
summary.jsonl
score
eval_status
stdout_path
stderr_path
raw_result_path
```

### 错误 6：MLE 没有 Kaggle 数据或凭据

MLE-bench 需要数据。至少要有一种：

```text
KAGGLE_JSON_B64
KAGGLE_USERNAME + KAGGLE_KEY
已挂载的 /opt/tiger/mle-bench-data
```

否则任务可能启动成功，但 MLE 准备或评分失败。

## 8. 失败时怎么判断问题在哪里

### 8.1 任务启动前失败

现象：

- Seed UI 没有容器日志；
- trial logs 为空；
- runtime 很短；
- 报镜像 build 或 base image 错。

优先检查：

```text
imageMeta
imageVid
imageSource
needBuild
模板镜像配置
```

这类不是 harness 问题。

### 8.2 容器启动了，但入口脚本失败

现象：

- 有 stdout/stderr；
- 能看到 `run_creation_eval.py` 或 `run_platform_bmk_shard.py`；
- summary 可能是 `failed/cluster_entrypoint`。

优先检查：

```text
容器内 harness 路径是否存在
依赖仓库是否挂载成功
API key 环境变量是否存在
pip install 是否失败
Kaggle 数据是否存在
```

### 8.3 Harness CLI failed

说明 generated harness 本身没有满足固定协议，或者路径不对。

检查：

```text
harness 目录是否完整
generated_program.py 是否存在
scaffold_manifest.json 是否存在
python -m harness run --task-json ... --model-config ... --output-dir ... 是否能运行
```

正式实验只调用标准 harness CLI，不再提供 permissive fallback。

### 8.4 BMK score 低

score 低不一定是链路坏了，可能是 harness 能力差。

需要看：

```text
trajectory.jsonl
stdout/stderr
result.json
submission.csv / patch / final answer
score_breakdown
token usage
```

## 9. 推荐目录命名

### 9.1 本地任务文件

```text
logs/platform_jobs/modelhub_noncode/<model>_<domain>_<date>.private.jsonl
logs/platform_jobs/modelhub_noncode/<model>_<domain>_<date>.no_secret.jsonl
logs/platform_jobs/swepro_<model>_<date>.private.jsonl
```

### 9.2 平台 watch 文件

```text
modelhub_noncode/<run_prefix>.watch.jsonl
modelhub_noncode/<run_prefix>.events.jsonl
swepro/<run_id>.watch.jsonl
swepro/<run_id>.events.jsonl
```

### 9.3 结果目录

普通 BMK：

```text
/opt/tiger/Harness_evolve/eval_results/cluster_full/<run_id>/
```

Platform-native SWE/Terminal：

```text
/opt/tiger/Harness_evolve/platform_eval_results/<run_id>/
```

## 10. 最小可执行流程

如果你只想照着跑，按这个顺序。

### 普通 BMK 最小流程

```bash
cd "/Users/bytedance/Downloads/harness-eval"

RUN_PREFIX="gpt55-noncode-full-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_noncode_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --output "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" \
  --benches mle_bench,eqbench3,browsecomp \
  --run-id-prefix "$RUN_PREFIX" \
  --generation-output-root "/opt/tiger/harness_evolve_project/generated_harnesses/gpt55/modelhub-full-20260608" \
  --output-root "/opt/tiger/Harness_evolve/eval_results/cluster_full" \
  --python-bin "python3" \
  --eval-model-name "gpt-5.5-2026-04-24" \
  --eval-reasoning-effort "high" \
  --provider-strip-max-tokens "1"

REMOTE="121399.zhangjingyuan-seed.ws@ssh-candy-wlby.workspace.byted.org"
REMOTE_DIR="/home/tiger/harness_eval_submit"

ssh "$REMOTE" "mkdir -p $REMOTE_DIR/modelhub_noncode"
rsync -av tools/submit_seed_job_jsonl.py tools/submit_seed_job_jsonl_batched.py "$REMOTE:$REMOTE_DIR/"
rsync -av "logs/platform_jobs/modelhub_noncode/${RUN_PREFIX}.private.jsonl" "$REMOTE:$REMOTE_DIR/modelhub_noncode/"

ssh "$REMOTE" "cd $REMOTE_DIR && python3 submit_seed_job_jsonl.py \
  --tasks modelhub_noncode/${RUN_PREFIX}.private.jsonl \
  --watch modelhub_noncode/${RUN_PREFIX}.watch.jsonl \
  --events modelhub_noncode/${RUN_PREFIX}.events.jsonl \
  --sleep-seconds 1"
```

### SWE Pro 最小流程

```bash
cd "/Users/bytedance/Downloads/harness-eval"

.venv/bin/python tools/validate_platform_direct_images.py \
  configs/platform_bmk_instances.swepro.vid.jsonl \
  --expected-count 731 \
  --check-direct-image \
  --check-no-secrets

RUN_ID="swepro-glm51-platform-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python tools/generate_platform_bmk_jobs.py \
  --template logs/platform_jobs/swepro_glm51_template.current.json \
  --instances configs/platform_bmk_instances.swepro.vid.jsonl \
  --output "logs/platform_jobs/${RUN_ID}.private.jsonl" \
  --benchmark swebench_pro \
  --run-id "$RUN_ID" \
  --harness-path "/opt/tiger/harness_evolve_project/generated_harnesses/glm51/high-devfeedback-20260608/code-agent-harness" \
  --output-root "/opt/tiger/Harness_evolve/platform_eval_results" \
  --require-direct-image \
  --preserve-template-env

REMOTE="121399.zhangjingyuan-seed.ws@ssh-candy-wlby.workspace.byted.org"
REMOTE_DIR="/home/tiger/harness_eval_submit"

ssh "$REMOTE" "mkdir -p $REMOTE_DIR/swepro"
rsync -av tools/submit_seed_job_jsonl.py tools/submit_seed_job_jsonl_batched.py "$REMOTE:$REMOTE_DIR/"
rsync -av "logs/platform_jobs/${RUN_ID}.private.jsonl" "$REMOTE:$REMOTE_DIR/swepro/"

# 先 probe 1 个
ssh "$REMOTE" "cd $REMOTE_DIR && python3 submit_seed_job_jsonl_batched.py \
  --tasks swepro/${RUN_ID}.private.jsonl \
  --watch swepro/${RUN_ID}.probe.watch.jsonl \
  --events swepro/${RUN_ID}.probe.events.jsonl \
  --max-active 1 \
  --max-submit 1 \
  --poll-seconds 60 \
  --submit-sleep-seconds 1"

# probe 通过后，再全量并发 32
ssh "$REMOTE" "cd $REMOTE_DIR && python3 submit_seed_job_jsonl_batched.py \
  --tasks swepro/${RUN_ID}.private.jsonl \
  --watch swepro/${RUN_ID}.watch.jsonl \
  --events swepro/${RUN_ID}.events.jsonl \
  --max-active 32 \
  --poll-seconds 60 \
  --submit-sleep-seconds 1"
```

## 11. 正式实验记录表

每次跑正式实验，至少记录这些字段：

```text
creation_model
creation_run_id
harness_artifact_path
eval_model
eval_reasoning_effort
benchmark
job_jsonl_path
watch_jsonl_path
events_jsonl_path
platform_job_ids
summary_csv_path
summary_jsonl_path
score
eval_status
token_usage
failure_reason
```

建议每次实验都新建一个小 Markdown 或 CSV，避免后面找不到对应 run。

## 12. 判断“链路跑通”的标准

不要只看任务提交成功。完整跑通至少满足：

1. Seed 平台成功创建任务。
2. 任务容器实际启动。
3. 入口脚本执行到 `run_creation_eval.py` 或 `run_platform_bmk_shard.py`。
4. Generated harness 被标准 CLI 调起。
5. Eval LLM API 被正常调用。
6. BMK runner 输出 `summary.csv` 或 `shard_result.json`。
7. `score` 或明确的 `eval_status` 被写入结果。
8. stdout/stderr/raw result 路径可追溯。

只有满足这些，才算“从 create 好的 harness 到 downstream BMK eval 的任务容器链路跑通”。
