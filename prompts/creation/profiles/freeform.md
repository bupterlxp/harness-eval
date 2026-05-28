# Creation Profile: Freeform

这是最低 scaffold 档。你只获得任务目标、工具边界和输出契约；你需要自己决定 harness 的代码结构、执行循环、上下文管理、工具策略、验证逻辑和失败恢复。

即使是 freeform，也必须满足统一接口：

- `python -m harness -p "<task>" --output-dir <dir>` 可运行；
- 兼容 `--workdir`、`--work-dir`、`--workspace`；
- 兼容 `--max-steps`、`--max-turns`；
- 写出 `result.json`、`trajectory.jsonl`、stdout/stderr 日志和任务真实产物；
- 不能只生成说明文档或模板报告后标记成功。

这个 profile 用于 ablation，不是推荐主实验设定。
