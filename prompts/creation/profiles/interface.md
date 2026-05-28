# Creation Profile: Interface Scaffold

本实验固定最外层接口，但不提供工具实现或 agent loop。你要在固定接口下合成可执行 harness。

固定部分：

- CLI 入口：`python -m harness -p "<task>" --output-dir <dir>`；
- 工作目录参数：`--workdir`、`--work-dir`、`--workspace`；
- 预算参数：`--max-steps`、`--max-turns`；
- 输出 schema：`result.json`、`trajectory.jsonl`、stdout/stderr；
- 所有最终产物必须写入 `--output-dir` 或工作目录中的题目指定路径，并在 `result.json` 中记录。

由你生成的部分：

- execution/control loop；
- context packing 策略；
- tool-use policy；
- verifier/self-check；
- retry/recovery；
- artifact construction。

不要把接口 scaffold 误用成模板答案。成功必须来自真实工具执行和真实产物。
