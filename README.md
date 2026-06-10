# Harness-Eval

这个仓库只保留一条清晰主链路：

```text
Claude Code / Codex meta harness
  -> claude_code_scaffold_native creation
  -> generated harness 标准 CLI
  -> downstream BMK eval
  -> summary / trajectories / token usage
```

当前不再维护旧的 adapter/fallback 路径，也不再暴露 `freeform`、`interface_tool`、`full_loop` 等多套 creation profile。正式实验统一使用 Claude Code atomic scaffold-native substrate，让 generation LLM 主要设计高层 harness 逻辑，而不是重复实现文件、shell、patch、logging、trajectory 等底层原子能力。

Meta harness 仍保留两条分支：

```text
--meta-harness claude-code
--meta-harness codex
```

也就是说，驱动 creation 的外层 agent 可以换 Claude Code 或 Codex；但生成出的 harness 仍必须满足同一个公开 CLI。

## 核心契约

生成出来的 harness 必须是一个可执行 agent，并暴露统一 CLI：

```bash
python -m harness run \
  --task-json <task.json> \
  --model-config <model_config.json> \
  --output-dir <output_dir>
```

BMK runner 只调用这个 CLI，不做智能补救、不猜入口、不 patch 运行时。生成物如果不能满足这个协议，就记为 `harness_failed`。

输出目录至少应包含：

```text
response.md          # agent 对当前 BMK task 的最终输出
trajectory.jsonl     # 可选但强烈建议，用于分析每道题轨迹
metadata.json        # 可选，建议记录 usage/token/tool calls
result.json          # 可选，结构化执行结果
stdout/stderr logs   # 由 runner 统一保存
```

## 目录结构

```text
run.py                         # creation 入口
run_creation_eval.py            # downstream eval 入口
generated_harness_cli.py        # 给外部 wrapper 调 generated harness 的薄 CLI
creation_eval/
  agent_cli.py                  # 唯一 generated harness 调用层
  benchmarks.py                 # BMK runners
  schema.py                     # summary schema
  token_usage.py                # eval-time harness token 提取
  pre_bmk_validation/           # public contract / artifact checks
prompts/
  system_prompt.md
  *_harness.md                  # 五类 domain prompt
  creation/profiles/
    claude_code_scaffold_native.md
vendor/harness_scaffold/        # Claude Code atomic scaffold runtime
tools/
  run_platform_bmk_shard.py     # 平台单 shard BMK 入口
  generate_platform_bmk_jobs.py # SWE/Terminal 等平台任务 JSONL 生成
  generate_noncode_bmk_jobs.py  # MLE/EQ/BrowseComp 等平台任务 JSONL 生成
```

## Creation

```bash
cd /Users/bytedance/Downloads/harness-eval

.venv/bin/python run.py config.yaml \
  --task-id code-agent-harness \
  --meta-harness claude-code \
  --creation-profile claude_code_scaffold_native \
  --run-id <creation_run_id>
```

`--creation-profile` 目前只支持 `claude_code_scaffold_native` 及少量等价别名（如 `native`、`cc_native`）。这不是一个可调 profile 矩阵，而是当前主实验固定设定。

## Eval Existing Harness

```bash
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/<creation_run_id> \
  --matrix eval_matrix.yaml \
  --bench eqbench3 \
  --domain writing \
  --run-id <eval_run_id> \
  --eval-output-root eval_results \
  --python-bin .venv/bin/python \
  --eval-base-url "$EVAL_BASE_URL" \
  --eval-api-key "$EVAL_API_KEY" \
  --eval-model-name "$EVAL_MODEL_NAME" \
  --eval-reasoning-effort high
```

`run_creation_eval.py` 会发现生成物，调用 `creation_eval.agent_cli.run_agent_cli`，并把结果写入：

```text
eval_results/<eval_run_id>/summary.csv
eval_results/<eval_run_id>/summary.jsonl
```

## Active BMKs

当前下游正式评测只保留这些：

| Domain | BMK |
|---|---|
| Code | SWE-bench Pro / SWE-compatible |
| Code | Terminal 2.0 / TerminalBench |
| Data | MLE-bench |
| Writing | EQBench3 |
| Research | BrowseComp |
| Browser | TheAgentCompany |

已从当前 active downstream eval 移除：DAComp、WritingBench、DeepResearch bench、LongBench-Write。

## Token Usage

`harness_run_tokens` 表示 generated/evolved harness 配上 eval LLM 做题时的 token 消耗。提取来源包括：

```text
metadata.json
metrics.json
result.json
harness_result.json
trajectory.jsonl
harness_stdout.log / harness_stderr.log
```

Judge token 或 BMK 自身 scorer token 应写在 `score_breakdown` 或 BMK 专用字段里，不和 `harness_run_tokens` 混在一起。

## 平台 Shard Eval

平台任务入口只跑一个 BMK shard，并调用同一个 generated harness CLI：

```bash
.venv/bin/python tools/run_platform_bmk_shard.py \
  --benchmark swebench_pro \
  --instance-json <instance.json> \
  --harness-path <generated_harness_path> \
  --domain code \
  --output-dir <shard_output_dir> \
  --python-bin .venv/bin/python \
  --eval-base-url "$EVAL_BASE_URL" \
  --eval-api-key "$EVAL_API_KEY" \
  --eval-model-name glm-5.1 \
  --eval-reasoning-effort high
```

批量任务 JSONL 由 `tools/generate_platform_bmk_jobs.py` 或 `tools/generate_noncode_bmk_jobs.py` 生成。API key 通过环境变量传入，不写入 JSONL。

## Summary 关键字段

```text
generation_model
creation_profile
domain
harness_task_id
harness_path
generation_status
cli_status
harness_invocation
eval_status
score
end_to_end_score
harness_run_tokens
harness_run_interactions
stdout_path
stderr_path
raw_result_path
missing_dependencies
```

正式分数只来自 downstream BMK。Public validation / creation-dev feedback 只用于 creation 阶段调试和诊断，不伪造成正式分数。

## 仓库维护说明

- **RQ2 / self-evolve**：`run_self_evolve.py`、`self_evolve/` 已从本分支（RQ1 主线）移除，RQ2 代码以 `self-evolve` 分支为 source of truth；历史版本可从本分支删除 commit 之前的提交找回。
- **`harbor_generated_harness_agent.py`**：本地 `terminal_2_bench` runner 通过 `harbor run --agent-import-path harbor_generated_harness_agent:GeneratedHarnessAgent` 使用该文件，不是遗留代码，不要删除。
- **git 内追踪的 `outputs/` artifact**：`.gitignore` 默认忽略 `outputs/`，但 4 个 creation run 的 artifact 被有意提交，因为平台 job 按 `gitRepo.commitSha` clone 本仓库取 harness（`/opt/tiger/Harness_evolve/outputs/...`）。在平台侧改为从 HDFS 下载 artifact 之前，不要 untrack 这些目录；之后应改走 HDFS 并停止向 git 提交新 artifact。
- **本地实验产物**：`eval_results/`、`logs/`、`exports/`、`memory.md` 均不入 git；已废弃 BMK（DAComp/WritingBench/DeepResearch/LongBench-Write）的旧结果和 verify-*/smoke-* 调试 run 统一移入 `archive/`（gitignored），写聚合脚本时不要扫 `archive/`。

## Secrets

不要提交 API key、Kaggle token、HDFS token、平台票据或本地实验输出。使用环境变量、忽略的本地配置文件或任务平台 secret 注入。
