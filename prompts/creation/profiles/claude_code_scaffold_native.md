# Creation Profile: Claude Code Scaffold Native

这是最高 scaffold 档。工作区已经提供 `harness_scaffold/`，它是从授权 Claude Code 原子能力抽取出的固定 runtime。你要在这个 runtime 上设计 harness，而不是绕开它从零重写一套独立 agent。

这个 profile 的实验目的：

- 测试 LLM 是否能在强原子能力 substrate 上做高层 harness 设计；
- 让模型专注于规划、工具选择、上下文组织、验证、恢复和产物组织；
- 避免大量样本死在文件读写、日志、stdout contract、CLI、trajectory、budget 等底层工程问题上。

## 固定 runtime

工作区包含：

```text
harness_scaffold/
generated_program.py
scaffold_manifest.json
harness/__main__.py
CLAUDE_CODE_SCAFFOLD.md
```

`harness_scaffold/` 提供现成原子能力，包括：

- 文件读取、写入、编辑；
- glob / grep / tree；
- bash / python 执行；
- patch / git diff / git status；
- json_io、artifact 写入、trajectory logging；
- budget、timeout、permission、retry；
- LLM client；
- web_search / web_fetch；
- browser、notebook、LSP；
- task graph、checkpoint / rollback；
- context compaction；
- domain artifact validator；
- dev feedback / failure report parsing；
- cost tracking。

你可以新增自己的工具、模块、策略文件和 verifier，但新增能力应当注册或接入这个 scaffold runtime。不要完全不用 `harness_scaffold` 后另写一套独立工具系统。

## 必须保留的 scaffold-native contract

最终产物必须至少满足：

```text
scaffold_manifest.json 指向一个 program 文件；
program 文件暴露 PROGRAM 或 get_program()；
program.run(ctx, tools, llm) 使用 RuntimeContext / ToolRegistry / HarnessResult contract；
python -m harness ... 只是兼容 wrapper，底层仍调用 harness_scaffold runtime。
```

推荐直接修改：

```text
generated_program.py
```

也可以增加：

```text
policy.py
planner.py
context_manager.py
verifier.py
recovery.py
custom_tools.py
```

但 `scaffold_manifest.json` 仍应指向最终 program。

## 允许扩展，但不能绕开

允许：

- 在 `generated_program.py` 中实现 domain-specific control loop；
- 使用 `tools.dispatch(...)` 或 registry 中的工具执行真实动作；
- 添加新的 custom tool，然后在 program 中调用；
- 添加 domain verifier、artifact writer、context packing、memory/state 模块；
- 修改 `harness/__main__.py` 的 wrapper 以增强兼容性。

不允许：

- 完全忽略 `harness_scaffold/`，重新写一个独立 `harness/tools.py` 和独立 agent loop；
- 只输出普通 `harness/` 包但不提供 scaffold program；
- 把固定模板、文件列表、执行计划当作 success；
- 绕过 trajectory/result/artifact contract。

## 下游兼容接口

外部 BMK 仍然会通过统一接口运行：

```bash
python -m harness \
  -p "<natural language task>" \
  --workdir <task workspace> \
  --output-dir <artifact output dir> \
  --max-steps <n>
```

这个入口必须可用，但它应该调用 scaffold runtime。也就是说，`python -m harness` 是兼容层，不是另一个独立实现。

## 输出契约

每次运行都要写出：

- `result.json`：状态、错误、关键产物路径、结构化指标；
- `trajectory.jsonl`：每轮 action / observation 或等价执行轨迹；
- `stdout.log` / `stderr.log` 或等价日志；
- domain-specific artifact，例如 patch、代码文件、submission.csv、REPORT.md、risk_scores.csv、图片、研究证据或浏览器结果。

## Domain 后置条件

- **code**：必须真实 inspect repo，真实修改文件或写 patch，尽力运行测试/validator；输出 changed files、diff/patch、commands_run 和 test/verifier 结果。
- **data_analysis / MLE**：必须真实读取 train/test/sample submission；如果有 `sample_submission.csv`，生成的 `submission.csv` 列名、行数、ID 顺序和值域必须与 sample contract 兼容；不能输出无依据全常数 fallback 后标记完全成功。
- **data_analysis / DAComp**：必须真实读取数据并计算；报告里需要具体数值、表格或结构化决策，不能只有流程模板。
- **writing**：最终 writing artifact 必须是用户可读正文，不是 JSON、adapter 日志或执行摘要；需要体现 plan/draft/critique/revision 或等价过程。
- **research**：必须记录搜索、阅读、证据或 citation trace；答案需要可追溯来源。
- **browser**：必须记录 navigate/click/type/extract 等 action trace 和最终状态/结果文件。

## Downstream BMK dev feedback loop

工作区会提供 `DEV_BMK_COMMANDS.md` 和 `run_dev_bmk.py`。它们允许你在 creation 阶段用公开/dev subset 跑少量真实 BMK 任务，查看分数、stdout/stderr、trajectory、artifact 和 raw result。

这不是 public validation gate，也没有外部 repair controller。你需要自己决定：

- 何时运行 `python3 run_dev_bmk.py --bench auto --max-tasks 3` 或指定某个 BMK；
- 如何根据 dev BMK score、日志、失败 artifact 和 trajectory 判断 harness 问题；
- 如何修改 `generated_program.py`、policy/verifier/context/recovery/custom tools；
- 何时再次运行 dev BMK；
- 何时认为 harness 已可进入正式 eval，并输出或写下 `FINISH`。

不要把 dev subset 当正式分数，也不要 hard-code dev task、instance id、答案或固定输出。正式 eval 会在隔离的 BMK subset 上只运行最终 harness，不再给你修改机会。
