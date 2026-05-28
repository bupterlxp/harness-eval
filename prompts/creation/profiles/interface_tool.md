# Creation Profile: Interface + Tool Scaffold

这是主实验推荐 profile。Benchmark 固定 interface、tool API contract、logging/result schema 和预算边界；模型生成 harness 的 decision layer。

## 固定的工程基座

必须遵守以下固定基座，不要重新发明不兼容的接口：

```text
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

每次运行都要写：

- `result.json`：状态、错误、关键产物路径、结构化指标；
- `trajectory.jsonl`：每轮 action/observation，一行一个 JSON；
- `stdout.log` / `stderr.log` 或等价日志；
- domain-specific artifact，例如 patch、代码文件、submission.csv、REPORT.md、risk_scores.csv、图片或浏览器结果。

## 推荐工具接口

可以自行实现工具，但至少要有清晰的工具边界。推荐用 JSON action loop，而不是 provider-specific function calling：

```json
{"thought": "...", "action": "read_file", "args": {"path": "src/app.py"}}
{"thought": "...", "action": "write_file", "args": {"path": "src/app.py", "content": "..."}}
{"thought": "...", "action": "run_command", "args": {"cmd": "python -m pytest -q"}}
{"thought": "...", "action": "finish", "args": {"status": "success"}}
```

工具名称可以按 domain 扩展，但必须真实执行，不允许只把工具名写进 prompt：

- 文件/代码：`list_files`、`read_file`、`search_text`、`write_file`、`edit_file`、`apply_patch`、`run_command`；
- 数据：`discover_files`、`summarize_table`、`execute_python`、`write_report`、`write_csv`、`create_chart`；
- 研究：`search_web`、`read_url`、`extract_evidence`、`write_report`；
- 浏览器：`navigate`、`click`、`type_text`、`extract_table`、`screenshot`；
- 写作：`plan_outline`、`draft_section`、`critique`、`revise`、`write_final`。

## 模型必须生成的核心能力

你不能只填模板。以下部分必须由你实现为可运行逻辑：

- execution/control loop；
- context manager / context packing；
- state tracking；
- tool-use policy；
- verifier / self-check；
- retry / fallback / recovery；
- final artifact construction。

## 结束条件

`finish` 只能在后置条件满足后调用。最低后置条件：

- domain-specific artifact 存在且非空；
- 已运行可行的 validator/test/grader 或记录无法运行的具体原因；
- `result.json` 指向真实 artifact；
- `trajectory.jsonl` 至少记录一次真实工具调用。

如果模型调用失败或验证失败，写 `partial` / `failed`，保存 best-effort 产物和失败日志；禁止把固定模板、文件列表、执行步骤列表当作成功答案。
