# Harness Self-Evolve Runner

`run_self_evolve.py` 是 RQ2 的当前可运行入口。它从 RQ1 已生成的 harness artifact 出发，让 meta harness 在同一类任务上继续修改 harness，并在每轮后调用 downstream BMK eval。

这个 runner 不负责重新 creation。`--creation-profile` 在这里表示 base artifact 的结构和 contract，用来告诉 prompt、snapshot、validation 和 adapter 如何保留产物。

## 两种实验模式

### RQ2-A：Commit-guided Evolution

给 agent 一个功能级 evolve task，让它在不看 human diff / PR / GitHub 的情况下实现等价 harness 能力。

```bash
.venv/bin/python run_self_evolve.py config.yaml \
  --mode commit \
  --base-generation-output outputs/<rq1_run_id> \
  --task-id code-agent-harness \
  --creation-profile claude_code_scaffold_native \
  --evolution-tasks-file self_evolve/tasks/<tasks>.jsonl \
  --max-tasks-per-harness 10 \
  --eval-bench terminal_2_bench \
  --run-id rq2a-code-terminal
```

结构化任务输入使用 `harness` 字段做分组；缺失时依次回退 `repo`、`source_harness`，仍缺失则归入 `unknown` 并在 summary 记录 warning。当前人类可读 fused task 文件可以先用脚本校验：

```bash
tools/validate_fused_update_counts.py \
  "/Users/bytedance/Downloads/harness evolve project/outputs/pr_fused_harness_updates/five_domain_pr_fused_updates.md" \
  --max-per-harness 10
```

### RQ2-B：Target-driven Self-Evolve

不给具体功能任务，只给高层目标和上一轮 eval feedback，让 agent 自己决定下一轮改什么。

```bash
.venv/bin/python run_self_evolve.py config.yaml \
  --mode goal \
  --base-generation-output outputs/<rq1_run_id> \
  --task-id data-analysis-harness \
  --creation-profile claude_code_scaffold_native \
  --goal-preset mle_bench \
  --rounds 30 \
  --eval-bench mle_bench \
  --run-id rq2b-data-mle
```

内置 preset：

| Preset | 目标 BMK |
|---|---|
| `terminal_2_bench` | Code / Terminal 2.0 |
| `mle_bench` | Data / MLE-bench |
| `browsecomp` | Research / BrowseComp |

如果传入 `--goal`，会覆盖 `--goal-preset`。prompt 不暴露 hidden score、hidden answer 或 `Round i of N`；`--rounds` 只在实验层截断。

## Artifact Contract

runner 同时支持两种 base artifact：

| Artifact | Contract |
|---|---|
| legacy harness | 保留 `harness/`，并保持 `python -m harness` 或 `python -m harness.cli` 可运行 |
| scaffold-native | 保留 `generated_program.py`、`scaffold_manifest.json`、`harness_scaffold/` 和 scaffold CLI/program contract |

每轮 snapshot 会记录 `self_evolve_artifact_contract`，用于排查 adapter 是否走了正确分支。不要删除 `generated_program.py`、`scaffold_manifest.json` 或 `harness_scaffold/`，否则 scaffold-native base 可能无法进入 eval。

## 输出

默认输出到：

```text
self_evolve_outputs/<run_id>/
```

关键文件：

| 文件 | 含义 |
|---|---|
| `run_config.json` | 实验配置、goal、task selection、plateau 参数 |
| `rounds.csv` | 每轮主要指标表 |
| `rounds.jsonl` | 每轮完整结构化指标 |
| `summary.json` | 实验摘要 |
| `experiment_summary.json` | 与 summary 等价，供后续分析脚本稳定读取 |
| `artifacts/round_*` | 每轮 harness snapshot |
| `eval_results/` | 每轮 downstream BMK eval summary |

主要指标：

| 字段 | 含义 |
|---|---|
| `avg_score` / `avg_end_to_end_score` | downstream BMK 分数和端到端分数 |
| `score_delta_from_base` | 相对 base harness 的提升 |
| `score_delta_from_previous` | 相对上一轮的变化 |
| `best_score_so_far` / `best_round` | 当前 best checkpoint |
| `regression_from_previous` | 是否相对上一轮退化 |
| `gate_fail` | 本轮 eval rows 是否出现 gate failure |
| `round_to_plateau` | 分数停止提升的轮次估计 |
| `creation_or_evolve_tokens` | creation/base 或 evolve 轮 token |
| `eval_harness_run_tokens` | harness + eval LLM 跑 downstream BMK 的 token |
| `eval_judge_tokens` | judge/grader token |
| `eval_total_tokens` | eval harness run + judge token |
| `cost_adjusted_gain` | 分数提升除以本轮 evolve+eval token |

Plateau 默认口径：连续 `--plateau-patience 3` 个完成 eval 的 evolution round 没有让 `best_score_so_far` 提升超过 `--plateau-min-delta 1e-6`，则 `round_to_plateau` 记为该停滞窗口的第一轮。

## 本地检查

```bash
.venv/bin/python -m py_compile \
  run_self_evolve.py \
  creation_eval/token_usage.py \
  creation_eval/adapter.py \
  creation_eval/benchmarks.py \
  tools/validate_fused_update_counts.py

.venv/bin/python run_self_evolve.py --help

.venv/bin/python -m pytest \
  tests/test_token_usage.py \
  tests/test_self_evolve_utils.py
```

不要提交 `outputs/`、`eval_results/`、`self_evolve_outputs/`、API key 或本地缓存。
