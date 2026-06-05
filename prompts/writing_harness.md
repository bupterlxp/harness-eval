# Agent Harness 构建任务：写作智能体（Writing Agent）

构建一个通用 writing harness，能接受创意写作、角色扮演、情感智力回应、长文续写、改写、修订和风格控制类任务，并输出可被 WritingBench / EQbench3 调用和评分的真实正文产物。

本任务的最低成功标准不是写说明文档，而是实现一个可运行的 harness program。

## Scaffold-native 最低实现要求

如果当前 creation profile 是 `claude_code_scaffold_native`，工作区已经有：

```text
generated_program.py
scaffold_manifest.json
harness_scaffold/
harness/__main__.py
```

你必须直接修改并实现 `generated_program.py` 中的 `GeneratedHarnessProgram.run(...)`。这个文件是本任务最重要的交付物。

必须满足：

- 删除或替换 `raise NotImplementedError`、`TODO`、stub fallback；
- `generated_program.py` 必须真实调用 `harness_scaffold` runtime；
- 可以新增 `planner.py`、`critic.py`、`memory.py`、`style.py`、`verifier.py` 等模块，但新增模块必须被 `generated_program.py` 实际调用；
- 不允许只写 README、架构说明、helper 模块或未接入工具；
- 不允许返回 "Task completed"、"Here is the plan"、JSON metadata、adapter 日志或短状态消息作为 writing artifact；
- 如果无法完全满足任务，也必须返回 `partial` 或 `failed`，写出 best-effort 正文、错误原因和可诊断轨迹，不能空退出。

## 统一入口

下游 BMK 会通过统一 CLI 调用：

```bash
python -m harness \
  -p "<writing task>" \
  --output-dir <output_dir> \
  --max-steps <n>
```

`-p` 中可能包含：

- 创意写作任务，例如故事、章节、场景、网文续写；
- 角色扮演或情感智力写作任务；
- 长文规划、续写、改写、润色、压缩或扩写；
- 明确的体裁、风格、语气、结构、长度、角色、禁忌和输出格式约束。

## 必须输出的产物

每次运行必须在 `--output-dir` 下写出：

- `result.json`：机器可读状态、轨迹路径、正文 artifact 路径、错误信息和关键指标；
- `trajectory.jsonl`：每轮 plan / draft / critique / revision / final 或等价执行轨迹；
- `response.md` 或 `final.md`：最终用户可读正文；
- 可选但推荐：`plan.json`、`critique.md`、`revision.md`、`style_notes.json`、`quality_scores.json`。

`result.json` 至少包含：

```json
{
  "status": "success | partial | failed",
  "trajectory": "trajectory.jsonl",
  "artifacts": {
    "final_text": "response.md"
  }
}
```

`success` 的最低条件是：

- final writing artifact 存在；
- final writing artifact 是正文，不是日志、计划、JSON 或执行摘要；
- final writing artifact 满足任务结构和长度要求；
- `trajectory.jsonl` 记录了实际写作流程；
- `result.json` 正确指向最终正文。

## 最低可用行为

`GeneratedHarnessProgram.run(ctx, tools, llm)` 至少必须执行以下流程：

1. 解析用户 prompt，提取 writing goal、受众、体裁、角色、风格、长度、结构和硬约束。
2. 生成一个短 planning brief，说明输出结构、写作视角、语气和必须满足的限制。
3. 调用 LLM 或 scaffold runtime 生成完整正文草稿。
4. 对草稿进行一次 critique / self-check，检查长度、结构、角色一致性、风格和禁忌。
5. 如果正文太短、跑题、缺少指定结构或只有状态消息，必须重写或扩写。
6. 写入最终正文 artifact，并在 `result.json` 中记录路径。
7. 写入 `trajectory.jsonl`，记录每一阶段的 action、observation、字数、修订原因和最终状态。

## Writing artifact 要求

- 如果任务没有明确长度，默认至少输出 600 英文词或 800 中文字。
- 如果任务要求三段或多段结构，例如 `[内心思考与感受] [对方心理分析] [角色内回应]`，最终正文必须保留这些结构。
- 如果任务要求创意写作，必须输出真实故事、章节、场景或片段，而不是“我会这样写”的计划。
- 如果任务要求修订，必须输出修订后的正文，并保留简短 revision log。
- 如果任务要求特定风格，必须在正文中体现风格控制，而不是只声明风格。
- 如果任务要求角色扮演，必须区分角色内回应和元分析，不能混成普通建议。

## 高层 harness 策略

写作 harness 应该实现可复用的高层策略，而不是硬编码某个样例：

- **Planning**：提取目标、读者、体裁、风格、结构和硬约束。
- **Context routing**：把任务约束压缩成可执行 writing brief，避免把无关说明塞进正文。
- **Drafting**：生成完整正文，不输出短状态文本。
- **Critique**：检查长度、结构、风格、角色、禁忌、是否过度模板化。
- **Revision**：根据 critique 重写或扩写，正文短于要求时必须补足。
- **Artifact writer**：保存最终正文和中间过程。
- **Failure recovery**：LLM 调用失败时写出 partial result 和失败原因，不能没有产物。

## 质量检查规则

实现中必须包含 `verify_artifacts` 或等价检查：

- 检查 final writing artifact 是否存在；
- 检查 final writing artifact 是否达到最低长度；
- 检查 final writing artifact 是否不是 JSON、日志、计划、adapter 输出或短状态消息；
- 检查指定结构是否出现；
- 检查 `result.json` 是否包含 final text 路径；
- 检查 `trajectory.jsonl` 是否至少记录 plan、draft、critique、final 四类事件或等价阶段。

检查失败时不能返回 `success`。

## 禁止事项

- 禁止保留 scaffold seed stub。
- 禁止在 `generated_program.py` 中保留 `raise NotImplementedError`。
- 禁止只写 README、说明文档或未接入 helper。
- 禁止把 `response.md` 写成“任务已完成”“请查看日志”之类短消息。
- 禁止把 JSON metadata、trajectory、stdout、stderr 当作最终正文。
- 禁止 hard-code benchmark answer、固定 prompt 或固定输出。
- 禁止依赖某一个测试任务；必须能处理未见 writing prompt。

## Creation 阶段自测

工作区会提供 `DEV_BMK_COMMANDS.md` 和 `run_dev_bmk.py`。你应该用公开/dev writing BMK 任务自测：

- `generated_program.py` 是否不再是 stub；
- CLI / scaffold adapter 是否可运行；
- 是否生成 `response.md` 或等价正文 artifact；
- 正文是否达到最低长度；
- `trajectory.jsonl` 是否记录写作流程；
- `result.json` 是否指向最终 artifact；
- WritingBench / EQbench3 dev task 的日志、分数和失败原因是否说明 harness 需要调整。

没有外部 public validator / repair controller 会替你修改。你需要自己查看 dev BMK 的 score、stdout/stderr、trajectory 和 artifact，修改 harness，再自测，直到最终输出或写下 `FINISH`。

## 技术约束

- Python 3.11+，type hints；
- LLM 调用使用 `harness_scaffold` runtime 或 OpenAI-compatible SDK；
- 环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`；
- 禁止 LangChain / LlamaIndex / AutoGen / anthropic SDK；
- 必须提供可运行 `python -m harness -p "..." --output-dir /output/` 的入口。
