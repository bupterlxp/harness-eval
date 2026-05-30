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

## Pre-BMK gate 标准

进入真实 BMK 前会检查：

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
