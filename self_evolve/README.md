# Self-Evolve 预留目录

这一目录用于 Harness-Evolve 的第二阶段实验：从已经生成出的 harness 出发，让 meta harness 根据公开任务指令、开发集 trace 或 downstream eval summary 继续修改 harness，再接入现有 BMK eval。

当前状态：**预留 / 实验性**。主实验仍以 `run.py -> run_creation_eval.py` 的 creation+eval 链路为准。`run_self_evolve.py` 是当前临时 runner，后续会把稳定逻辑迁到本目录。

## 计划结构

- `tasks/`：human commit 转写任务、goal-driven evolution task、以及数据 schema。
- `runners/`：commit-mode、goal-mode、self-debug-mode 等 runner。
- `analysis/`：learning curve、human-gap、regression rate、cost-adjusted gain 分析。

## 需要补齐

1. 固定 evolution task schema：只暴露任务目标，不暴露 human diff / hidden answer。
2. 明确每轮 selection：最后一轮、best dev round、还是 cost-adjusted best。
3. 与 creation summary 对齐：复用 `score`、`end_to_end_score`、gate 字段和 token/cost 字段。
4. 加 human reference eval：同一 BMK、同一 eval LLM 下比较 human-evolved 和 agent-evolved harness。
5. 防止 hidden BMK 泄露：repair/evolution 只能使用 public gate、dev trace、公开错误和 eval summary。

