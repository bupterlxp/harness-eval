# Creation Profile: Claude Code Atomic Scaffold

本 profile 会在工作区中提供一个可复用的 `harness_scaffold/` runtime。它来自授权的 Claude Code 原子能力抽取版本，包含文件、shell、search、patch、git、artifact、trajectory、budget、permission、timeout、LLM client、adapter 和 validation 相关能力。

你可以自由选择：

- 直接使用 `harness_scaffold` 的 runtime CLI；
- 复用其中的工具、schema、adapter 或 validation 逻辑；
- 参考其实现后自行写完整 `harness/`；
- 完全不用它，只要最终 harness 满足统一接口和下游 BMK 契约。

这不是 Claude Code 复刻任务，也不是固定模板填空任务。目标仍然是生成一个能在目标 domain 上真实工作的 agent harness。

## 可用资源

工作区中会包含：

```text
harness_scaffold/
CLAUDE_CODE_SCAFFOLD.md
```

如果选择直接使用 scaffold runtime，可参考：

```bash
python -m harness_scaffold.adapters.cli \
  --task-json task.json \
  --program generated_program.py \
  --out-dir output
```

也可以继续生成传统结构：

```bash
python -m harness -p "<natural language task>" --workdir <task workspace> --output-dir <artifact output dir>
```

## 下游接口必须兼容

无论是否使用 scaffold，最终产物必须能通过：

```bash
python -m harness \
  -p "<natural language task>" \
  --workdir <task workspace> \
  --output-dir <artifact output dir> \
  --max-steps <n>
```

兼容别名：

- `-p` 与 `--prompt`；
- `--workdir`、`--work-dir`、`--workspace`；
- `--max-steps`、`--max-turns`。

每次运行都要写出：

- `result.json`：状态、错误、关键产物路径、结构化指标；
- `trajectory.jsonl`：每轮 action/observation 或等价执行轨迹；
- `stdout.log` / `stderr.log` 或等价日志；
- domain-specific artifact，例如 patch、代码文件、submission.csv、REPORT.md、risk_scores.csv、图片、研究证据或浏览器结果。

## BMK dev feedback 自测标准

工作区会提供 `DEV_BMK_COMMANDS.md` 和 `run_dev_bmk.py`。你可以用公开/dev subset 自己运行少量真实 BMK 任务，并从 score、stdout/stderr、raw result、artifact 和 trajectory 中判断 harness 是否可用。

你在自测和修改时至少应该关注：

- 语法、import、CLI probe；
- `result.json`、`trajectory.jsonl`、stdout/stderr 日志；
- 至少一次真实工具调用或可审计 action trace；
- 没有 TODO/stub-only / `NotImplementedError`；
- 预算被尊重，不能无限循环；
- 失败时也要保留 best-effort artifact 和错误信息。

## Domain 后置条件

- **code**：必须真实修改工作目录文件或产出 patch，尽力运行测试/编译/verifier，记录 diff、命令和结果。
- **data_analysis**：必须真实读取数据并计算，生成结构化结果文件和报告；不能只写流程说明。
- **writing**：必须有 plan/draft/critique/revision 或等价写作过程，最终文本非空且满足任务约束。
- **research**：必须有检索或证据收集 trace，答案需要引用或记录来源；不能只凭空总结。
- **browser**：必须有动作轨迹、状态变化和最终结果；不能只写操作计划。

成功只能来自真实执行和真实产物。固定模板、文件列表、执行步骤列表不能标记为 `success`。

没有外部 public gate 或 repair controller 会替你判断并返修。你需要自己运行 dev BMK、读取反馈、修改 harness、再次测试，直到认为最终 harness 可以进入正式 eval，并输出或写下 `FINISH`。

因此，harness 需要把真实执行证据写出来，方便从 dev BMK 轨迹中分析：

- `result.json` 中写出 `status`、`artifacts`、`tool_calls`、`errors`、`commands_run` 或等价字段；
- `trajectory.jsonl` 中保留每轮 action/observation；
- 失败也要写出 best-effort artifact 和错误原因，不能静默成功；
- 不要把运行日志当成最终答案文件。

## Benchmark-aware public artifact contracts

- **code / SWE / Terminal**：必须真实 inspect repo，真实修改文件或写 patch，尽力运行测试/validator；输出 changed files、diff/patch、commands_run 和 test/verifier 结果。
- **data_analysis / MLE**：如果 workdir 中有 `sample_submission.csv`，必须生成 `submission.csv`，列名、行数、ID 顺序必须完全一致；预测列必须使用公开 sample 暗示的合法类型和值域。例如 `Transported` 是 `True/False` 标签时，不允许输出概率小数。
- **data_analysis / DAComp**：必须真实读取数据并计算；报告里需要具体数值、表格或结构化决策，不能只有流程模板。
- **writing / WritingBench / EQBench3**：最终 writing artifact 必须是用户可读正文，不是 JSON、adapter 日志或执行摘要；需要体现 plan/draft/critique/revision 或等价写作过程。
- **research / DeepResearch / BrowseComp**：必须记录搜索、阅读、证据或 citation trace；答案需要可追溯来源。
- **browser / TheAgentCompany**：必须记录 navigate/click/type/extract 等 action trace 和最终状态/结果文件。
