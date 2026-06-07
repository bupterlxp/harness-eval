# Harness Eval

用 LLM 驱动 coding agent 自动生成 agent harness，并把生成结果接到 downstream BMK 上评估。

核心假设：**如果一段 prompt 足够好，强模型应该能从中生成结构完整、可运行的 agent 系统**。本项目用这种方式同时评估 prompt 质量和模型能力。

当前执行链路：

1. 从 `tasks.jsonl` 读取任务——每个任务包含一段描述需要构建什么 harness 的 prompt
2. 根据 `--meta-harness` 选择生成器：
   - `claude-code`：启动 Docker 容器，内置 Claude Code + [claude-code-router](https://github.com/musistudio/claude-code-router)
   - `codex`：调用本机 Codex CLI，在临时 workspace 里生成 harness
3. Claude Code 路径会经过 model-proxy 透明代理 LLM 请求，记录 token 用量和交互轮次
4. 按 `--creation-profile` 注入 scaffold 设定，让模型在固定 interface/tool contract 下生成 harness
5. Agent 在临时 workspace 中工作；如果开启 dev BMK feedback，会看到 `DEV_BMK_COMMANDS.md` 和 `run_dev_bmk.py`，可自行跑公开/dev BMK subset、看日志/分数/轨迹并修改 harness
6. 任务完成后，收集最终输出产物、dev BMK 轨迹和 metrics
7. 如果指定 `--eval-after`，直接通过 adapter 接入下游 BMK scoring；正式 score 只来自 downstream BMK，不使用 public gate 伪造分数

---

## 整体流程

```
研究 → 提示词 → 生成 + dev BMK 自测 → 正式 eval
```

1. **调研**（`research/`）：分析各领域生产级 agent 的实现模式，提炼共性架构
2. **提示词设计**（`prompts/`）：将调研结论转化为结构化 prompt，定义功能要求和调用示例
3. **生成**（`run.py`）：将 `system prompt + creation profile + task prompt` 喂给 meta harness（Claude Code Docker 或本机 Codex CLI），生成完整 harness
4. **Creation dev BMK feedback**：在生成 workspace 内提供 `run_dev_bmk.py`，让 meta harness + LLM 自己跑公开/dev BMK subset、读分数/日志/轨迹并决定是否继续修改
5. **正式评测**（`run_creation_eval.py`）：做最小 adapter/runnable 检查，并把最终 generated harness 接到 downstream BMK；正式分数不反馈给 creation agent

```
┌─────────────────────────────────────────────────┐
│  claude-code meta harness                        │
│                                                  │
│  Claude Code ──► model-proxy(:3457)              │
│                      │  记录 metrics.json        │
│                      ▼                           │
│               claude-code-router(:3456)          │
│                      │                           │
│                      ▼                           │
│               外部 LLM API (OpenRouter/内部平台) │
└─────────────────────────────────────────────────┘

codex meta harness 会直接调用本机 `codex exec`，模型名通过 `-m` 传入。它依赖本机 Codex CLI 的登录和 provider 配置；如果要用 OpenRouter/内部非 OpenAI 模型，默认更稳的是 `claude-code + model-proxy` 路径。
```

---

## 架构约束 H = (E, T, C, S, L, V)

所有生成的 harness 必须遵循统一的六组件架构，定义在 `prompts/system_prompt.md` 中：

| 组件 | 模块 | 职责 |
|------|------|------|
| **E** | `execution.py` | 显式 FSM 状态机驱动的执行循环（状态枚举 + 转移表） |
| **T** | `tools.py` | 工具注册与调度，每个工具有 JSON schema |
| **C** | `context.py` | 上下文管理、token 预算、自动摘要/截断 |
| **S** | `state.py` | 状态持久化、snapshot/rollback、断点恢复 |
| **L** | `lifecycle.py` | 生命周期钩子（操作前/后、失败、超时） |
| **V** | `evaluation.py` | JSONL 轨迹记录，每步记录状态/操作/结果/耗时 |

硬性要求：`from harness import execution, tools, context, state, lifecycle, evaluation` 必须可执行。

---

## 提示词设计

### 主实验方案：main runtime/eval + scaffold substrate + BMK dev feedback

当前主实验采用 hybrid 方案：

- **main runtime/eval**：保留 `run.py -> run_creation_eval.py -> eval_matrix.yaml -> creation_eval/benchmarks.py` 的完整生成和下游 BMK 评测主链路；
- **Claude Code scaffold/native substrate**：在 generation workspace 中提供不同强度的 `creation_profile`，其中 `claude_code_scaffold_native` 是 RQ1 主 setting；
- **BMK dev feedback**：creation agent 可运行 `run_dev_bmk.py` 在公开/dev subset 上自测，读取真实 score、stdout/stderr、trajectory、artifact，再自行修改 harness；
- **main BMK scoring contract**：正式分数仍由 SWE-bench、TerminalBench、MLE-bench、EQbench3、BrowseComp、TheAgentCompany 等 active adapter 产生，不使用 public gate 或 toy task 伪造分数。DAComp、WritingBench、DeepResearch bench 当前已从 active downstream eval registry 移除。

推荐主 profile 是 `claude_code_scaffold_native`。它固定 Claude Code atomic scaffold/runtime，让模型主要生成 harness 的 decision layer：control loop、context packing、state tracking、tool policy、verifier、retry/recovery 和 final artifact construction。`interface_tool` 和 `freeform` 仍作为 scaffold ablation。

可选 profile：

| Profile | 用途 |
|---|---|
| `freeform` | 最弱 scaffold，用于 ablation；只给目标和输出契约。 |
| `interface` | 固定 CLI/schema，但不提供工具 contract。 |
| `interface_tool` | 主实验默认；固定 interface + tool contract。 |
| `full_loop` | 强 scaffold / upper bound；给完整 loop 结构但仍要求真实策略。 |
| `claude_code_scaffold` | 可选注入 CC_4 atomic scaffold；模型可以复用文件、shell、patch、trajectory、artifact、task graph、checkpoint、context compaction、cost tracker 等原子能力，也可以自行实现。 |
| `claude_code_scaffold_native` | 最高 scaffold 档；直接把 Claude Code 原子能力作为固定 runtime/substrate，模型可以扩展工具，但不能完全绕开 scaffold 重新写独立 harness。 |

建议把 scaffold 强度作为实验 setting，而不是隐藏实现细节：

| Setting | 对应 profile | 含义 |
|---|---|---|
| 从 0 写 | `freeform` | 只给目标和输出契约，测试模型原始 creation 能力。 |
| 基础 interface/tool | `interface_tool` | 给统一 CLI、schema 和工具 contract，测试模型能否自己实现可运行 harness。 |
| Claude Code 原子能力 substrate | `claude_code_scaffold_native` | 给抽取好的 Claude Code 原子能力和 scaffold runtime，测试模型能否做高层编排、验证和恢复设计。 |

### Creation dev BMK feedback loop

当前 RQ1 creation 阶段不再由外部 public validator/repair controller 指导模型。runner 只把公开/dev BMK feedback 命令放进 workspace，模型自己决定是否测试和如何修改：

```bash
python run.py config.yaml \
  --task-id code-agent-harness \
  --creation-profile claude_code_scaffold_native \
  --dev-bmk-task-limit 3 \
  --run-id code-rq1-opus
```

生成 workspace 中会有：

- `DEV_BMK_COMMANDS.md`：说明该 domain 推荐自测哪些 BMK；
- `run_dev_bmk.py`：调用 `run_creation_eval.py --max-tasks-per-bmk N`，在公开/dev subset 上运行当前 harness；
- `dev_bmk_runs/`：保存每次自测的 `summary.csv`、`summary.jsonl`、stdout/stderr、raw result 和 index。

模型可以在 Claude Code 会话里反复执行：

```bash
python3 run_dev_bmk.py --bench auto --max-tasks 3
```

然后根据 score、trajectory、artifact 和日志自行修改 harness，直到输出或写下 `FINISH`。正式 eval 只使用最终冻结的 harness，不能再把正式分数反馈给模型。

这会更直接地测 LLM 写 harness 的能力：模型不是满足我们写的 toy gate，而是用真实 BMK dev feedback 自己调试。

质量分析脚本：

```bash
python tools/analyze_creation_quality.py \
  --run prompt_only=outputs/old_prompt_run \
  --run scaffold=outputs/claude_scaffold_run \
  --run scaffold_native_dev_feedback=outputs/claude_scaffold_native_run \
  --output-dir analysis_outputs/creation_quality
```

输出：

- `creation_quality_comparison.csv`
- `creation_quality_report.md`

### RQ2：Harness Self-Evolve

`run_self_evolve.py` 是第二阶段 Harness-Evolve runner。它不重新 creation，而是从已经生成好的 base artifact 出发，让 meta harness 修改现有 harness，然后继续调用 `run_creation_eval.py` 做 downstream BMK eval。

当前以 `codebyt/self-evolve` 为主干，`codex/rq1-readiness@9be977b` 只作为 RQ1 token usage 参考 commit；不要普通 merge 该分支，避免把无关历史或 `outputs/` 差异带入。当前主线已经具备等价的 downstream token usage 能力，并在 self-evolve summary 中区分：

| 字段 | 含义 |
|---|---|
| `creation_or_evolve_tokens` | creation 或每轮 evolve 的 meta harness token 消耗 |
| `eval_harness_run_tokens` | generated/evolved harness 配合 eval LLM 跑 downstream BMK 的 token 消耗 |
| `eval_judge_tokens` | downstream judge / grader 的 token 消耗 |
| `eval_total_tokens` | harness run token 与 judge token 的合计 |

RQ2-A commit-guided evolution：

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

`--max-tasks-per-harness` 只作用于 JSONL/结构化任务输入，字段来源依次为 `harness`、`repo`、`source_harness`，缺失时归入 `unknown` 并在 summary 里记录 warning。当前人类可读任务清单可用下面命令校验每个 harness 是否在 10 个 fused updates 以内：

```bash
tools/validate_fused_update_counts.py \
  "/Users/bytedance/Downloads/harness evolve project/outputs/pr_fused_harness_updates/five_domain_pr_fused_updates.md" \
  --max-per-harness 10
```

RQ2-B target-driven self-evolve：

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

内置 `--goal-preset` 包括 `terminal_2_bench`、`mle_bench`、`browsecomp`。如果显式传入 `--goal`，会完全覆盖 preset。goal prompt 只写高层目标和合法边界，不写 hidden score、hidden answer 或总轮数；`--rounds` 只在实验层截断。

每轮输出位于 `self_evolve_outputs/<run_id>/`：

| 文件 | 含义 |
|---|---|
| `rounds.csv` / `rounds.jsonl` / `rounds.json` | 每轮 score、token、gate、best、regression、plateau 字段 |
| `summary.json` | self-evolve run 摘要 |
| `experiment_summary.json` | 与 `summary.json` 等价，供后续实验脚本稳定读取 |
| `artifacts/round_*` | 每轮 harness snapshot |
| `eval_results/` | 每轮 downstream BMK eval 原始 summary |

curve 字段口径：

| 字段 | 含义 |
|---|---|
| `score_delta_from_base` | 当前轮 score 减 base 轮 score |
| `score_delta_from_previous` | 当前轮 score 减上一轮有分数的 score |
| `best_score_so_far` / `best_round` | 截至当前轮的 best checkpoint |
| `regression_from_previous` | 当前分数低于上一轮超过 `--plateau-min-delta` |
| `round_to_plateau` | 默认连续 `--plateau-patience 3` 个完成 eval 的 evolution round 没有提升 best score 时的停滞起点 |
| `cost_adjusted_gain` | 相对 base 的 score gain 除以本轮 evolve+eval total tokens |

### Platform-native BMK shards（无 Docker-in-Docker）

如果 Seed/Arnold 任务平台不能在任务容器里启动 Docker daemon，旧的
`swebench_pro` / `terminal_2_bench` Docker runner 会失败。当前新增 no-DinD
路径：每个 instance 或 repo-family 对应一个预构建镜像，平台直接起这个镜像，
容器里只运行 generated harness + eval LLM，并输出 patch、verifier 结果和
`shard_result.jsonl`。

生成一行一个 JSON object 的任务 JSONL：

```bash
python tools/generate_platform_bmk_jobs.py \
  --template outputs/platform_jobs/template.seed_job.json \
  --instances configs/platform_bmk_instances.swepro.jsonl \
  --output outputs/platform_jobs/swepro_glm51_jobs.jsonl \
  --benchmark swebench_pro \
  --run-id swepro-glm51-platform-$(date +%Y%m%d-%H%M%S) \
  --harness-path /opt/tiger/Harness_evolve/outputs/creation-code-glm51-high-nomax-20260605-181801/code-agent-harness
```

提交 JSONL：

```bash
export SEC_TOKEN_PATH=/path/to/sec_token
python tools/submit_seed_job_jsonl.py \
  --tasks outputs/platform_jobs/swepro_glm51_jobs.jsonl \
  --watch outputs/platform_jobs/watch_tasks.jsonl \
  --events outputs/platform_jobs/events.jsonl
```

合并 shard 结果：

```bash
python tools/merge_platform_bmk_shards.py \
  --root platform_eval_results/<run_id> \
  --out-jsonl platform_eval_results/<run_id>/summary.jsonl \
  --out-csv platform_eval_results/<run_id>/summary.csv
```

完整说明见 [docs/platform_native_bmk_eval.md](/Users/bytedance/Downloads/harness-eval/docs/platform_native_bmk_eval.md)。

### 两层结构

```
prompts/
├── system_prompt.md          # 通用架构约束（ETCSLV），所有 harness 共享
├── creation/profiles/        # freeform/interface/interface_tool/full_loop/claude_code_* profile
├── code_agent_harness.md     # 代码智能体：bug 修复、功能开发、重构
├── data_analysis_harness.md  # 数据分析：统计分析、可视化、数据工程 pipeline
├── writing_harness.md        # 创意写作：长篇小说、情感角色扮演、批评-修改循环
├── research_agent_harness.md # 深度研究：多跳检索、矛盾处理、精确问答
└── browser_agent_harness.md  # 浏览器自动化：DOM 压缩、多标签页、表单填写
```

### Prompt 内容结构（每个领域 prompt）

每份 prompt 包含 5 个章节：

| 章节 | 内容 | 作用 |
|------|------|------|
| **一、入口与输出** | CLI 接口、`result.json` 格式 | 定义统一的调用和输出规范 |
| **二、功能性质** | 7-8 个子系统的详细描述 | 告诉模型需要实现什么能力 |
| **三、调用示例** | 5 个完整 case，含逐步行为轨迹 | 通过具体例子展示期望行为 |
| **四、技术栈** | 允许和禁止的依赖 | 约束实现方式 |
| **五、环境打包** | Dockerfile 要求 | 确保可复现 |

### 功能性质详解（第二章节）

每份 prompt 的第二章节用粗体分节描述 7-8 个子系统，用叙事而非列表的方式定义行为。这些描述来自对生产级 agent 的调研总结（`research/` 目录）：

| 领域 | 关键子系统 |
|------|-----------|
| **Code Agent** | 执行循环/代码导航/编辑策略(精确替换+模糊回退)/上下文压缩(4层)/错误恢复/版本管理/规划与子任务/验证 |
| **Data Analysis** | Plan-Code-Observe循环/有状态Python命名空间/数据库Schema提取/数据导入/可视化(8+图表)/结果验证/上下文管理/数据工程Pipeline(staging→core→mart) |
| **Writing** | 三级规划(总纲→卷纲→章纲)/三层记忆(Working/Episodic/Semantic)/正典层一致性/风格控制+Anti-AI/批评-修改循环(收敛检测)/长上下文管理/多Rollout质量保证 |
| **Research** | 多跳迭代检索(广度×深度递归)/证据管理(分块+嵌入+质量评分)/矛盾处理/任务分解DAG/引用系统/报告+精确问答双模式/上下文预算/多Agent协作 |
| **Browser** | DOM压缩(可访问性树)/动作执行(索引+坐标点击)/多标签页/子目标分解/任务记忆/循环检测(5→8→12次阈值)/上下文压缩/错误恢复+弹窗处理/数据提取 |

### 调用示例（第三章节）

每个领域 5 个 case，从简单到复杂，覆盖核心功能和边界场景。每个 case 包含：
- 完整的命令行调用
- 逐 Round/Step 的行为轨迹（Thought → Action → Observation）
- 期望的产物列表

示例 case 设计也考虑了目标 benchmark 的覆盖：

| 领域 | 目标 Benchmark | 对应 Case |
|------|---------------|-----------|
| Code Agent | SWE-bench | Case 1-4: 修复测试/新增端点/类型错误/大规模重构 |
| Data Analysis | DAComp | Case 1-4: 留存分析/异常检测/AB测试/预测; Case 5: 数据工程 Pipeline |
| Writing | EQ-Bench 3 | Case 5: 情感智力角色扮演（心智理论+多方共情） |
| Research | HLE (text) | Case 5: 高难度专业问答（精确答案模式+证据链） |
| Browser | MiniWoB | Case 1-5: 比价/表单/分页提取/条件分支/SPA交互 |

---

## 调研文档

`research/` 目录包含各领域生产级 agent 实现的调研总结，是 prompt 设计的依据：

| 文件 | 内容 |
|------|------|
| `01_code_agent.md` | Aider, SWE-agent, OpenHands, Claude Code 等代码 agent 的架构分析 |
| `02_data_analysis.md` | Julius AI, Data-Copilot, TableGPT 等数据分析 agent 的实现模式 |
| `03_writing_agent.md` | Dramatron, CALYPSO, Agents of Fiction 等写作 agent 的记忆/规划/审查机制 |
| `04_research_agent.md` | STORM, Tavily, Perplexity 等研究 agent 的检索/综合/引用系统 |
| `05_browser_agent.md` | WebVoyager, Agent-E, Browser-Use 等浏览器 agent 的 DOM/动作/恢复策略 |

---

## Showcase：Claude Opus 4 生成的 5 个 Harness

使用 Claude Opus 4（非 Docker 模式，直接通过 Claude Code CLI）基于上述 prompt 并行生成了 5 个完整 harness，存放在 `outputs/opus4_showcase/`。

### 生成结果概览

| Harness | 代码行数 | FSM 状态数 | 转移数 | 导入验证 |
|---------|---------|-----------|--------|---------|
| Code Agent | 2,128 | 5 | 显式表 | ✅ |
| Data Analysis | 2,017 | 7 | 14 | ✅ |
| Writing | 2,746 | 15 | 15 | ✅ |
| Research | 2,272 | 9 | 17 | ✅ |
| Browser | 2,997 | 11 | 26 | ✅ (需 playwright) |
| **合计** | **12,160** | | | |

### 各 Harness 文件结构

每个 harness 均包含 10 个文件，严格遵循 ETCSLV 架构：

```
outputs/opus4_showcase/<harness>/
├── __init__.py        # 包入口
├── __main__.py        # CLI 入口 (python -m harness -p "..." --output-dir ./output/)
├── execution.py       # E — FSM 执行循环
├── tools.py           # T — 工具注册
├── context.py         # C — 上下文管理
├── state.py           # S — 状态持久化
├── lifecycle.py       # L — 生命周期钩子
├── evaluation.py      # V — 轨迹记录
├── requirements.txt   # Python 依赖
└── Dockerfile         # 容器化打包
```

### 各 Harness 关键实现特征

**Code Agent**（`outputs/opus4_showcase/code-agent-harness/`）
- 9 个工具：`find_files`, `grep`, `read_file`, `write_file`, `str_replace`, `bash`, `list_dir`, `run_tests`, `done`
- `str_replace` 编辑后用 `ast.parse()` 验证 Python 语法，失败自动回滚
- `bash` 执行前用 `bash -n` 做语法预检
- Doom loop 检测：3 次相同操作触发策略切换，持续则进入 STUCK 状态

**Data Analysis**（`outputs/opus4_showcase/data-analysis-harness/`）
- 持久化 Python 命名空间（SandboxNamespace），变量在步骤间共享
- 预导入 pandas/numpy/matplotlib/seaborn
- 四层上下文压缩（70%/80%/90%/95% 阈值触发）
- `signal.SIGALRM` 超时保护

**Writing**（`outputs/opus4_showcase/writing-harness/`）
- 15 状态 FSM（task_analysis → style_setup → planning → drafting → critique → revision → ...）
- 三层记忆：Working（当前场景）+ Episodic（近期事件，去重）+ Semantic（角色/世界规则/时间线/伏笔）
- 正典层：角色认知状态追踪 + 世界规则验证
- 声音指纹 + AI 模式检测（正则 + LLM）
- 批评-修改循环含平台检测（分数变化 < 阈值时终止）

**Research**（`outputs/opus4_showcase/research-agent-harness/`）
- 9 状态 FSM（init → decompose → search → fetch → analyze → synthesize → generate → complete）
- 双输出模式：LLM 自动判断 report vs QA，QA 模式输出精确答案 + 证据链
- 多跳检索：广度逐层减半，ANALYZE 阶段检测知识缺口后回环至 SEARCH
- 证据管道：内容提取 → 1000 字分块 → 关键词相关性过滤 → 结构化 EvidenceCard
- 矛盾处理：EvidenceCard 追踪 `contradicts` 列表

**Browser**（`outputs/opus4_showcase/browser-agent-harness/`）
- 11 状态 FSM，26 条转移规则
- 14 个工具：click, fill, scroll, navigate, switch_tab, close_tab, extract_content, search_page, screenshot, wait, done 等
- 停滞检测：5/8/12 次阈值递进警告
- 页面指纹变化检测（连续 5 步无变化触发警告）
- 子目标规划：3-10 个子目标，支持 pending/current/done/skipped/failed 状态

---

## 早期评测对比（Opus 4.5 vs Doubao）

以 Code Agent 同一份 prompt 对比两个模型（Docker 模式生成）：

| 维度 | Claude Opus 4.5 | Doubao-Seed-2.0-Mini |
|------|-----------------|---------------------|
| 文件数 | 8 个模块文件 | 1 个单文件 |
| 状态机 | 显式 FSM（enum + 转移表） | 无，线性执行 |
| LLM 调用 | OpenAI chat completions + tool_choice | 无，if-else 硬编码 |
| 工具注册 | 7 工具 + JSON schema | 方法内联，无 schema |
| 上下文管理 | token budget + 压缩 | 无 |
| 有效请求 | 13 次，121K input | 22 次，465K input |

**结论**：该任务要求跨文件架构一致性理解 + LLM 工具调用范式知识 + 状态机设计能力。弱模型即使能理解接口规范，也无法实现 LLM 驱动的执行循环。

更多对比详见 `REPORT.md` 和 `outputs/` 下各模型的输出。

---

## 快速开始

### 生成模式

```bash
# 1. 安装依赖
pip install pyyaml

# 2. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入 API 地址、密钥和模型名称

# 3. 运行默认 claude-code 生成模式
python3 run.py
```

`config.yaml` 会被 `.gitignore` 忽略，因为里面通常包含 API key。本仓库只提交 `config.yaml.example`。
如果不想创建本地配置文件，也可以直接用命令行指定生成模型和任务。

### 一条命令生成并评测

命令行里可以同时指定：

- `--meta-harness`：用什么 meta harness 生成 harness；当前支持 `claude-code` 和 `codex`
- `--model-name`：meta harness 背后的 LLM，也就是“写 harness”的模型；可以填真实 model id，也可以填别名如 `GPT5.5`、`Seed2.0`、`Claude4.7`
- `--eval-model-name`：生成出来的 harness 在下游 BMK 里调用的 LLM，也就是“被测 harness 使用”的模型；同样支持别名，不填则默认复用 `--model-name`
- `--task-id`：生成哪个方向的 harness
- `--eval-bench`：生成后接哪些下游 BMK
- `--run-id`：本次 generation/eval 的目录名，便于复现和对比

例如，用 Claude Code 作为 meta harness、用指定 LLM 生成 code harness，然后直接跑 SWE-bench Pro 和 Terminal 2.0：

```bash
python3 run.py \
  --run-id code-claude-opus-example \
  --meta-harness claude-code \
  --creation-profile interface_tool \
  --pre-bmk-gate soft \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --model-name "$MODEL_NAME" \
  --claude-model-name claude-sonnet-4-6 \
  --reasoning-effort max \
  --eval-model-name "$MODEL_NAME" \
  --eval-reasoning-effort max \
  --task-id code-agent-harness \
  --eval-after \
  --eval-domain code \
  --eval-bench swebench_pro,terminal_2_bench
```

用 OpenRouter 时，`BASE_URL` 通常应是完整 chat completions 地址：

```bash
export BASE_URL="https://openrouter.ai/api/v1/chat/completions"
export API_KEY="$OPENROUTER_API_KEY"
export MODEL_NAME="anthropic/claude-opus-4.7"
```

如果使用内部 Anthropic-native endpoint，而不是 OpenAI-compatible chat completions endpoint，则走 Claude Code 原生 Anthropic 配置：

```bash
export CLAUDE_NATIVE_ANTHROPIC=1
export ANTHROPIC_BASE_URL="https://your-anthropic-endpoint"
export ANTHROPIC_AUTH_TOKEN="$YOUR_TOKEN"
export ANTHROPIC_MODEL="your-opus-model-id"
export CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1
export CLAUDE_CODE_THINKING=adaptive
export CLAUDE_CODE_THINKING_EFFORT=max

.venv/bin/python run.py \
  --run-id code-opus47-max \
  --meta-harness claude-code \
  --base-url "$ANTHROPIC_BASE_URL" \
  --api-key "$ANTHROPIC_AUTH_TOKEN" \
  --model-name "$ANTHROPIC_MODEL" \
  --claude-model-name "$ANTHROPIC_MODEL" \
  --reasoning-effort max \
  --task-id code-agent-harness
```

`max` 档会直接传给 Claude Code `--effort max`。如果上游网关因为超时或并发限流失败，可以把 `CLAUDE_CODE_THINKING_EFFORT` 和 `--reasoning-effort` 临时降到 `high`，但要在 run id 或实验记录里标明。

如果想把写 harness 的模型和被测 harness 的模型分开，例如用 Claude Code 这个 meta harness 调两个不同后端模型：

```bash
python3 run.py \
  --run-id code-gpt55-create-opus-eval \
  --meta-harness claude-code \
  --creation-profile interface_tool \
  --pre-bmk-gate soft \
  --base-url "https://openrouter.ai/api/v1/chat/completions" \
  --api-key "$OPENROUTER_API_KEY" \
  --model-name "openai/gpt-5.5" \
  --claude-model-name claude-sonnet-4-6 \
  --reasoning-effort max \
  --task-id code-agent-harness \
  --eval-after \
  --eval-domain code \
  --eval-bench swebench_pro,terminal_2_bench \
  --eval-base-url "https://openrouter.ai/api/v1/chat/completions" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max
```

这里 `--claude-model-name` 只是传给 Claude Code CLI 的壳模型名；真实请求会被本仓库的 proxy 改写到 `--model-name`。所以只要 OpenRouter 支持对应 model id，就可以把 `--model-name` 或 `--eval-model-name` 换成 GPT 系列、Claude 系列或其他模型。`--eval-after` 会自动启动一个本地 provider proxy，把 eval 模型配置注入到 Docker 里的 generated harness。

如果要用 Codex 作为 meta harness：

```bash
python3 run.py \
  --run-id code-codex-gpt55-example \
  --meta-harness codex \
  --creation-profile interface_tool \
  --model-name GPT5.5 \
  --reasoning-effort xhigh \
  --task-id code-agent-harness
```

Codex 路径不会强制要求 `--base-url/--api-key`，因为它默认使用本机 Codex 登录态。`GPT5.5` 在 Codex 路径会解析成 `gpt-5.5`，而不是 OpenRouter 的 `openai/gpt-5.5`。需要非默认 provider 时，可以通过 `--codex-extra-args` 传 Codex CLI 的本地 profile/config override，或在 `codex_model_aliases` 里覆盖。

内置模型别名可以这样查看：

```bash
python3 run.py --list-model-aliases
```

生成完成后直接接 downstream BMK，也可以继续使用配置文件：

```bash
# 只生成/评测代码 harness，并跑 SWE-bench Pro + Terminal 2.0
python3 run.py config.yaml \
  --task-id code-agent-harness \
  --creation-profile claude_code_scaffold_native \
  --dev-bmk-task-limit 3 \
  --eval-after \
  --eval-domain code \
  --eval-bench swebench_pro,terminal_2_bench

# 只生成/评测写作 harness，并跑 EQbench3
python3 run.py config.yaml \
  --task-id writing-harness \
  --creation-profile claude_code_scaffold_native \
  --dev-bmk-task-limit 3 \
  --eval-after \
  --eval-domain writing \
  --eval-bench eqbench3
```

### 生成后接下游 BMK 评测

`run_creation_eval.py` 会把已经生成的 harness 目录接到下游 benchmark registry 上，输出统一的
`eval_results/<run_id>/summary.jsonl` 和 `summary.csv`。

正式实验默认使用 `--adapter-mode strict`。这个模式只允许固定协议桥：

- scaffold-native artifact：通过 `scaffold_manifest.json + generated_program.py` 调用 `harness_scaffold.adapters.cli`；
- legacy artifact：只调用标准 `python -m harness --task-json ... --workdir ... --output-dir ... --model-config ...`；
- 必须由 generated harness 产出 `result.json`、`trajectory.jsonl` 和对应 domain artifact；
- 不再猜测多种 CLI 入口、不自动找最新文件当答案、不注入 search patch、不自动安装 generated harness 的 requirements。

`--adapter-mode permissive` 仅用于 bring-up/debug，会保留历史的多入口探测、fallback 和运行时补丁；正式 RQ1/RQ2 分数不要用 permissive。

summary 中的 token 字段口径如下：

- `generation_tokens`：meta harness 在 creation 阶段生成和自测修改 harness 的 token 消耗。
- `repair_tokens`：保留的兼容字段；RQ1 当前不启用外部 public-contract repair loop，通常为空。
- `harness_run_tokens`：生成或 evolve 出来的 harness 配上 eval LLM，在 downstream BMK 解题时的 token 消耗。它从 adapter 输出的 `metadata.json`、`trajectory.jsonl`、`result.json` 或 stdout usage marker 中提取；如果 harness 没有记录 LLM usage，这一列会留空而不是伪造。
- `harness_run_token_breakdown`：`harness_run_tokens` 的明细，包括 input/output/reasoning token、来源文件和多 task BMK 的 per-task token。
- 评分 judge 的 token 不计入 `harness_run_tokens`，会写进 `score_breakdown.judge_tokens`，避免把“被测 harness 成本”和“评分成本”混在一起。

```bash
python3.12 run_creation_eval.py \
  --generation-output outputs/opus45 \
  --run-id opus45-dryrun \
  --dry-run
```

如果系统 Python 由系统包管理器保护、不能直接安装依赖，推荐使用本仓库虚拟环境：

```bash
uv venv .venv --python /opt/homebrew/bin/python3.12
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/opus45 \
  --python-bin "$PWD/.venv/bin/python" \
  --adapter-mode strict
```

常用筛选：

```bash
# 只跑 writing 相关 benchmark
python3.12 run_creation_eval.py --generation-output outputs/opus45 --domain writing

# 只跑写作类最终保留的 downstream BMK
python3.12 run_creation_eval.py \
  --generation-output outputs/opus45/writing-harness \
  --bench eqbench3

# 只跑代码类两个 downstream BMK
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/opus45/code-agent-harness \
  --bench swebench_pro,terminal_2_bench \
  --python-bin "$PWD/.venv/bin/python" \
  --adapter-mode strict

# 对尚未接入真实运行器的 benchmark 跑 generated-harness 代理冒烟验证，
# 结果会标记为 proxy_smoke_*，不会伪装成真实 BMK 分数。
python3.12 run_creation_eval.py \
  --generation-output outputs/opus45 \
  --proxy-smoke-for-unsupported
```

当前 registry 在 `eval_matrix.yaml`，包含截图中的全部 BMK 名称。V1 对真实 runner 做依赖门控：
可直接接入的 runner 会运行；缺数据、缺服务、缺 API key 或还没有 generated-harness agent adapter 的项会在
`missing_dependencies` 中明确记录为 `skipped/*`。

### Creation 侧 BMK 可评分契约

2026-05-28 起，creation prompt 不再只要求“结构完整”，还显式要求“可被下游 BMK 评分”。核心约束写在 `prompts/system_prompt.md`、`prompts/code_agent_harness.md`、`prompts/data_analysis_harness.md`：

- 统一 CLI 必须兼容 `-p/--prompt`、`--output-dir`、`--workdir/--work-dir/--workspace`、`--max-steps/--max-turns`；
- 每次运行必须写出 `result.json`、`trajectory.jsonl`、stdout/stderr 日志和任务真实产物；
- 禁止只输出固定模板、文件列表、步骤列表或 `response.md` 后声明成功；
- Code harness 遇到明确目标路径时，必须尽早创建 best-effort 文件，例如 TerminalBench 里的 `/app/gpt2.c`；
- Data harness 遇到 MLE-Bench 必须产出同 schema 的 `submission.csv`，不能 no submission；
- Data harness 遇到 tabular / notebook 类任务时必须包含真实计算结果、结构化表格、可复现脚本和机器可读汇总。DAComp 当前不再作为 active downstream BMK。

这部分是为了区分两类失败：

- **eval runner 问题**：依赖缺失、服务未启动、adapter 不兼容、官方 evaluator 报错；
- **creation 质量问题**：generated harness 能启动，但没有做出可评分产物，或产物只是模板/兜底内容。

如果是后者，应该优先改 `prompts/` 或提供更强 scaffold，而不是改 downstream BMK 分数逻辑。

代码类 BMK 目前已经接入 generated harness：

- `swebench_pro`: 通过 `harness_house/benchmarks` 的 SWE-bench/OpenHands workspace 启动实例，把 generated code harness 上传进 repo workspace，运行后抽取 `git diff`，再调用 `swebench-eval` 得到真实 resolved/pass rate。
- `terminal_2_bench`: 通过 Harbor `--agent-import-path` 注册 `GeneratedHarnessAgent`，在 TerminalBench task container 内上传并运行 generated code harness，再用现有 `terminalbench-eval` 汇总 verifier 结果。

这两个 runner 不伪造分数；Docker/Harbor 启动超时、generated harness adapter 失败、官方 evaluator 缺镜像等都会写成 `failed/*` 或明确的依赖缺失。

2026-05-28 小样本验证记录：

| BMK | Run ID | 结果 | 结论 |
|---|---|---:|---|
| Terminal 2.0 | `regen-code-opus47-max-promptfix-terminal2-20260528` | unresolved，`0/1` | Harbor 和 verifier 已真实启动；generated code harness 30 步耗尽，未完成 `/app/gpt2.c`，属于 creation 质量问题。 |
| MLE-bench | `regen-data-opus47-high-promptfix-dataeval-20260528` | `score=0.82299` | generated data harness 产出有效 `submission.csv`，可以 pilot。 |
| DAComp | `regen-data-opus47-high-promptfix-dataeval-20260528` | `score=0.0` | 历史验证记录；DAComp 当前已从 active downstream eval registry 移除。 |

上述结果的统一输出在 `eval_results/<run_id>/summary.csv`。`eval_results/` 默认被 `.gitignore` 忽略，不会提交到仓库。

截图中的非代码类 BMK 也已 registry 化并接到 generated harness：

| BMK | 运行器 | 当前接入方式 |
|---|---|---|
| `mle_bench` | `mlebench_generated` | 接官方 `openai/mle-bench`，generated data harness 生成 submission CSV 后调用官方 `grade_csv`；需要 Kaggle credential 和 prepared competition data。 |
| `eqbench3` | `eqbench3` | 复用现有 EQ-Bench3/Kimi-writer wrapper，并将 `KIMI_WRITER_PATH` 指向 generated harness adapter。 |
| `browsecomp` | `browsecomp_generated` | 下载 OpenAI simple-evals BrowseComp encrypted CSV，全量解密题目，generated research harness 回答，再用 judge 算 accuracy；优先使用 `SERPER_KEY_ID`、`TAVILY_API_KEY` 或 `SEARCH_API_KEY`，缺 key 时用 Bing/DuckDuckGo HTML fallback。 |
| `the_agent_company` | `the_agent_company_generated` | 将 generated browser harness 接到 TheAgentCompany 官方全量 task image 列表；需要官方服务栈先在本机或远端启动，包括 RocketChat、ownCloud、GitLab、Plane 等服务。 |

Research 类 BMK 不接受 generated harness 自带的 mock/LLM-simulated search 作为正式分数。adapter 会在临时运行目录中给 generated research harness 注入真实联网搜索工具：有 Serper/Tavily/API key 时走 API provider，没有 key 时走 Bing/DuckDuckGo HTML fallback。论文级稳定复现实验建议配置正式 search API key；本地一两条任务验证可以先用 fallback。

当前默认 registry 已切到 full run：所有支持全量数据的 active BMK 默认不再限制为 1 条。写作类评测只保留 `eqbench3`；Data 只保留 `mle_bench`；Research 只保留 `browsecomp`。`dacomp`、`writing_bench`、`deepresearch_bench` 当前不会在 downstream eval 中运行。`mle_bench` 的代码路径已接通，但全量跑分前必须先配置 Kaggle credential 并 prepare 对应 competition data；未 prepare 的 competition 会被标成明确依赖缺失，不伪造分数。

### 非代码四类 harness 的全量验证命令

生成端和评测端都已经参数化。下面示例用 `claude-code` 作为 meta harness，后端 generation LLM 和 eval LLM 都走 OpenRouter 的 Opus 4.7 最强推理档。把 `--model-name`、`--eval-model-name` 或 `--meta-harness` 替换即可切换到 GPT5.5、Seed2.0、Qwen3.7、Gemini3.1、K2.6、GLM5.1、Claude4.7 或 Codex 路径。

```bash
# 生成四类非代码 harness
python3 run.py \
  --run-id noncode-opus47-max \
  --meta-harness claude-code \
  --base-url "https://openrouter.ai/api/v1/chat/completions" \
  --api-key "$OPENROUTER_API_KEY" \
  --model-name "anthropic/claude-opus-4.7" \
  --claude-model-name claude-sonnet-4-6 \
  --reasoning-effort max \
  --task-id data-analysis-harness,writing-harness,research-agent-harness,browser-agent-harness
```

也可以直接对已经生成好的目录跑 downstream BMK。建议用环境变量传 key，避免把 key 留在 shell history 或进程列表里：

```bash
export EVAL_API_KEY="$OPENROUTER_API_KEY"
```

然后执行：

```bash
# Writing：EQbench3，全量任务
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-opus47-max-final-20260523 \
  --domain writing \
  --bench eqbench3 \
  --run-id noncode-writing-opus47-eval \
  --eval-base-url "https://openrouter.ai/api/v1/chat/completions" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max

# Data：MLE-bench；需要 Kaggle credential 和 prepared data
HARNESS_EVAL_DATA_MAX_TURNS=8 .venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-opus47-max-final-20260523 \
  --domain data_analysis \
  --bench mle_bench \
  --run-id noncode-data-opus47-eval \
  --eval-base-url "https://openrouter.ai/api/v1/chat/completions" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max

# Research：BrowseComp，全量任务
HARNESS_EVAL_RESEARCH_MAX_STEPS=8 \
HARNESS_EVAL_RESEARCH_BREADTH=2 \
HARNESS_EVAL_RESEARCH_DEPTH=1 \
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-opus47-max-final-20260523 \
  --domain research \
  --bench browsecomp \
  --run-id noncode-research-opus47-eval \
  --eval-base-url "https://openrouter.ai/api/v1/chat/completions" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max

# Browser / Digital Employee：TheAgentCompany
# 需要先启动官方服务栈。服务健康检查地址：
#   http://localhost:2999/api/healthcheck/rocketchat
.venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-opus47-max-final-20260523 \
  --domain browser \
  --bench the_agent_company \
  --run-id noncode-browser-opus47-eval \
  --eval-base-url "https://openrouter.ai/api/v1/chat/completions" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max
```

当前本机验证记录：

| Run ID | 结果 |
|---|---|
| `noncode-writing-opus47-eval-20260523` | 历史记录；当前 active writing downstream BMK 只保留 `eqbench3`。 |
| `noncode-data-opus47-eval-20260523` | 历史记录；当前 active data downstream BMK 只保留 `mle_bench`。 |
| `noncode-research-opus47-eval-20260523` | 历史记录；当前 active research downstream BMK 只保留 `browsecomp`。 |
| `noncode-browser-opus47-eval-20260523` | 代码链路已接到 TheAgentCompany runner；本机服务栈未启动，因此结构化标记为 `skipped/missing_dependency`。 |

TheAgentCompany 官方服务栈启动命令：

```bash
curl -fsSL https://github.com/TheAgentCompany/the-agent-company-backup-data/releases/download/setup-script-20241208/setup.sh | sh
```

注意：该脚本会拉取多个大型 Docker 镜像，并使用 `--network host` 启动 `api-server`。在 macOS Docker Desktop 上，`servers-gitlab` 镜像压缩层约 11.9GB，本机实测在 GitLab 镜像大层下载阶段可能长时间无进度输出。论文级或连续实验建议放到 Linux 开发机执行 TheAgentCompany。

### 任务格式（tasks.jsonl）

支持三种任务定义方式：

```jsonl
{"id": "code-agent", "prompt_file": "./prompts/code_agent_harness.md"}
{"id": "data-analysis", "prompt_file": "./prompts/data_analysis_harness.md"}
{"id": "writing", "prompt_file": "./prompts/writing_harness.md"}
{"id": "research", "prompt_file": "./prompts/research_agent_harness.md"}
{"id": "browser", "prompt_file": "./prompts/browser_agent_harness.md"}
```

### 配置说明（config.yaml）

```yaml
base_url: "https://your-api-endpoint/v1/chat/completions"
api_key: "your-api-key"
model_name: "GPT5.5"                   # 可填别名或真实 provider model id
meta_harness: "claude-code"            # 可选 claude-code / codex
claude_model_name: "claude-sonnet-4-6"  # 只用于 Claude Code CLI；后端真实模型仍用 model_name
reasoning_effort: "max"                 # Opus 4.7 最强推理档；映射到 Claude Code --effort 和 OpenRouter verbosity

# Codex meta harness 可选配置。
codex_bin: "codex"
codex_sandbox: "workspace-write"
codex_enable_search: false
codex_model_aliases:
  GPT5.5: "gpt-5.5"

# 模型别名可按本地 provider 实际 ID 覆盖。
model_aliases:
  GPT5.5: "openai/gpt-5.5"
  Seed2.0: "ep-20260214145701-frz7j"
  Qwen3.7: "qwen/qwen3.7"
  Gemini3.1: "google/gemini-3.1"
  K2.6: "moonshotai/kimi-k2.6"
  GLM5.1: "z-ai/glm-5.1"
  Claude4.7: "anthropic/claude-opus-4.7"

# 可选：下游 BMK 里 generated harness 调用的 LLM。
# 不填时 run.py --eval-after 默认复用 generation 的 base_url/api_key/model_name/reasoning_effort。
eval_base_url: "https://openrouter.ai/api/v1/chat/completions"
eval_model_name: "Claude4.7"
eval_reasoning_effort: "max"

system_prompt_file: "./prompts/system_prompt.md"
include_system_prompt: true

max_concurrent: 4        # 并行容器数
timeout_minutes: 30      # 单任务超时
output_dir: "./outputs"
tasks_file: "./tasks.jsonl"
```

常用查看命令：

```bash
# 查看当前可生成的 harness 类型
python3 run.py --list-tasks

# 查看模型别名会解析到哪个 provider id
python3 run.py --list-model-aliases

# 只做 generation，不跑 BMK
python3 run.py \
  --run-id code-only-debug \
  --meta-harness claude-code \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --model-name "$MODEL_NAME" \
  --reasoning-effort max \
  --task-id code-agent-harness
```

## 输出结构

```
outputs/
├── summary.json             # 汇总统计
└── <task-id>/
    ├── meta.json            # 任务状态 + metrics 摘要
    ├── metrics.json         # 完整请求级用量记录
    ├── claude_output.log    # Claude Code 路径的完整输出日志（如有）
    ├── codex_last_message.txt / codex_command.json  # Codex 路径的输出记录（如有）
    ├── CLAUDE.md            # 使用的 prompt
    └── harness/             # 生成的 harness 代码
        ├── __main__.py
        ├── execution.py
        ├── tools.py
        ├── context.py
        ├── state.py
        ├── lifecycle.py
        └── evaluation.py
```

## Metrics 统计

每个任务运行时，`model-proxy.js` 作为透明代理拦截所有 LLM 请求，自动生成 `metrics.json`：

```json
{
  "total_requests": 56,
  "total_input_tokens": 781927,
  "total_output_tokens": 5186,
  "effective_requests": 22,
  "effective_input_tokens": 465460,
  "effective_output_tokens": 5186,
  "retry_requests": 34,
  "requests": [...]
}
```

| 字段 | 含义 |
|------|------|
| `total_*` | 包含所有请求（含重试）的原始计数 |
| `effective_*` | 排除重试后的有效计数（用于评估真实效率） |
| `retry_requests` | 被识别为重试的请求数 |

**重试识别规则**：HTTP 状态码 >= 400（如 429 限流），或响应中无 API 报告的 usage 且 output_tokens=0。这避免了因 API 不稳定（如豆包频繁 429）导致的 token 统计膨胀。

`requests` 数组记录每次请求的详细信息：时间戳、HTTP 状态码、input/output tokens、模型名称、是否为重试。可用于分析请求分布、识别限流模式、计算有效利用率。

---

## 数据分析 / 浏览器链路

这两类任务也走同一条流水线：

```text
harness creation -> generated harness adapter -> downstream BMK -> summary.csv / summary.jsonl
```

### 生成 data / browser harness

```bash
export API_KEY="你的 OpenRouter 或其他 provider key"
export BASE_URL="https://openrouter.ai/api/v1/chat/completions"
export MODEL_NAME="anthropic/claude-opus-4.7"
export CLAUDE_MODEL_NAME="$MODEL_NAME"

.venv/bin/python run.py \
  --run-id noncode-data-browser-opus47-max \
  --meta-harness claude-code \
  --reasoning-effort max \
  --task-id data-analysis-harness,browser-agent-harness \
  --max-concurrent 1 \
  --timeout-minutes 90
```

替换 meta harness 或模型时，只改参数即可：

```bash
.venv/bin/python run.py \
  --run-id data-qwen-codex \
  --meta-harness codex \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --model-name "qwen/qwen3.7" \
  --reasoning-effort max \
  --task-id data-analysis-harness
```

### 跑数据分析 BMK

MLE-bench 需要先准备 Kaggle 数据。`~/.kaggle/kaggle.json` 需要存在，且对应 Kaggle competition rules 已接受。下面只展示单个 competition 的 prepare 方式；当前 `eval_matrix.yaml` 默认会尝试全量 registered competitions，未 prepare 的 competition 会在结果里标明 missing dependency。

```bash
.venv/bin/python -m mlebench.cli prepare \
  -c spaceship-titanic \
  --data-dir ~/.cache/mle-bench/data

export EVAL_API_KEY="$API_KEY"
export HARNESS_EVAL_DATA_MAX_TURNS=8

.venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-data-browser-opus47-max \
  --domain data_analysis \
  --bench mle_bench \
  --run-id data-eval-opus47-max \
  --eval-base-url "$BASE_URL" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max
```

如果 generated harness 没有生成 MLE submission CSV，runner 会把这次真实失败记为 `score=0.0`，并在 `score_breakdown.failure_mode=no_submission` 里说明原因。

### 跑 TheAgentCompany 浏览器 BMK

官方 TheAgentCompany setup 在 Linux 上依赖 host networking。Mac Docker 本地运行时，先启动真实服务栈，再用本仓库的本地 shim 提供 task image 初始化时需要的 reset/health API。

```bash
# 1. 启动真实服务栈
curl -fsSL https://github.com/TheAgentCompany/the-agent-company-backup-data/releases/download/setup-script-20241208/setup.sh -o /tmp/tac-setup.sh
sh /tmp/tac-setup.sh

# 2. Mac Docker 下如果官方 api-server 端口不可用，启动 shim
.venv/bin/python tools/tac_api_shim.py --host 0.0.0.0 --port 2999
```

另开一个终端跑 eval：

```bash
export EVAL_API_KEY="$API_KEY"
export TAC_SERVICE_HEALTH_URL="http://localhost:2999/api/healthcheck/rocketchat"

.venv/bin/python run_creation_eval.py \
  --generation-output outputs/noncode-data-browser-opus47-max \
  --domain browser \
  --bench the_agent_company \
  --run-id browser-eval-opus47-max \
  --eval-base-url "$BASE_URL" \
  --eval-model-name "anthropic/claude-opus-4.7" \
  --eval-reasoning-effort max
```

当前 TheAgentCompany 默认从官方 `tasks.md` 拉取全量 task image 列表逐个运行。分数来自每个 task image 自带的 `/utils/eval.py`，不是手写规则。

---

## Self-Evolve + Eval

> 当前状态：这一块已可用于 pilot 级 self-evolve 实验。`goal` 和 `commit` 两种模式都复用 main eval spine，并会记录每轮 harness 修改成本、downstream 解题成本和 judge 成本。正式大规模实验前仍需要继续完善 human-reference artifact 自动打包、任务抽样策略和学习曲线分析脚本。

`run_self_evolve.py` 用于 Harness-Evolve 的第二阶段：从一个已经生成出来的 harness 出发，让 meta harness 继续修改它，并在每轮修改后直接接入现有 downstream BMK eval。

它支持两个 RQ：

| Mode | 对应研究问题 | 输入 | 输出 |
|---|---|---|---|
| `commit` | agent 能否实现 human commit 里同等的 harness 功能改进 | human commit 转写出来的任务指令 JSONL | 每轮 agent-evolved harness + 下游 BMK 分数，可选 human reference 同跑 |
| `goal` | 给一个目标，比如“在对应 BMK 上高分”，harness 能否根据 eval signal 自己迭代 | base generated harness + goal + eval summary | 每轮 self-evolved harness + learning curve |

这条线复用 main eval spine，不单独造评测器：

```text
base generated harness
-> self-evolve edit round by Claude Code / Codex
-> snapshot as standard generation artifact
-> run_creation_eval.py
-> summary.csv / summary.jsonl
```

后续修改位置：

```text
self_evolve/
├── README.md                 # 当前 self-evolve 设计和待办
├── tasks/                    # 预留：human commit / goal evolution task 数据
├── runners/                  # 预留：不同 evolution mode 的 runner 实现
└── analysis/                 # 预留：learning curve / human gap / regression 分析
```

### 目标驱动自我迭代

下面例子从一个 code harness creation 产物开始，让 Claude Code + Opus 4.7 max 改 harness，并用同一个 Opus 4.7 max 作为被测 harness 的 eval LLM，跑 SWE/Terminal 的小集：

```bash
export BASE_URL="https://openrouter.ai/api/v1/chat/completions"
export API_KEY="$OPENROUTER_API_KEY"

.venv/bin/python run_self_evolve.py config.yaml \
  --mode goal \
  --run-id code-self-evolve-opus47-goal \
  --base-generation-output outputs/code-interface-tool-pilot/code-agent-harness \
  --meta-harness claude-code \
  --model-name Claude4.7 \
  --reasoning-effort max \
  --eval-model-name Claude4.7 \
  --eval-reasoning-effort max \
  --eval-domain code \
  --eval-bench swebench_pro,terminal_2_bench \
  --rounds 3 \
  --goal "Improve this code harness so it achieves higher downstream BMK score by making real edits, running validators, and recovering from failed commands."
```

输出在：

```text
self_evolve_outputs/<run-id>/
├── artifacts/round_000_base/<task-id>/
├── artifacts/round_001_.../<task-id>/
├── eval_results/
├── prompts/
├── logs/
├── rounds.csv
└── summary.json
```

`rounds.csv` 和 `summary.json` 会记录每轮 token / cost 口径：

- `creation_or_evolve_tokens`：本轮 meta harness 修改 harness 的 token 消耗；第 0 轮是 base creation artifact 已记录的 generation token。
- `eval_harness_run_tokens`：本轮 evolved/generated harness 配上 eval LLM，在 downstream BMK 解题时的 token 消耗。这个字段用于比较不同 harness 的执行成本。
- `eval_judge_tokens`：BMK judge / grader 产生的 token 消耗。它和被测 harness 的解题 token 分开记录，避免把评分成本混进 harness 成本。
- `eval_total_tokens`：`eval_harness_run_tokens + eval_judge_tokens`，用于每轮 downstream eval 总成本统计。
- `eval_harness_run_interactions`：本轮 downstream eval 中被测 harness 的交互 / tool-action 轮次。
- `cost_adjusted_gain`：相对 base harness 的 `avg_score` 提升除以本轮 `creation_or_evolve_tokens + eval_total_tokens`，用于粗略衡量单位 token 改进收益。
- `summary.json.token_totals`：把上述 token 字段按所有轮次汇总。

### Human-commit comparable evolution

`commit` 模式用于“跟人比较”的 RQ。输入文件只放任务指令，不放 human diff。human reference 如果已经打包成标准 generation artifact，可以用 `--human-generation-output` 同配置跑一遍下游 BMK。

```bash
.venv/bin/python run_self_evolve.py config.yaml \
  --mode commit \
  --run-id code-self-evolve-human-commit \
  --base-generation-output outputs/code-interface-tool-pilot/code-agent-harness \
  --evolution-tasks-file self_evolve_tasks.example.jsonl \
  --max-tasks 2 \
  --meta-harness codex \
  --model-name GPT5.5 \
  --reasoning-effort xhigh \
  --eval-model-name GPT5.5 \
  --eval-domain code \
  --eval-bench terminal_2_bench
```

参数化关系：

- `--meta-harness claude-code|codex`：谁来驱动 harness 修改。
- `--model-name` / `--reasoning-effort`：self-evolve 阶段的 meta LLM，例如 `Claude4.7`、`GPT5.5`、`Seed2.0`。
- `--eval-model-name` / `--eval-reasoning-effort`：evolved harness 在 downstream BMK 解题时调用的 LLM。
- `--pre-bmk-gate soft|hard|off`：兼容旧命令的隐藏参数；RQ1 正式链路不再使用 public gate。

---

## 项目结构

```
harness-eval/
├── README.md                 # 本文件
├── REPORT.md                 # 详细评测报告
├── run.py                    # harness generation 入口，支持 claude-code / codex
├── run_creation_eval.py      # generated harness -> downstream BMK eval 入口
├── run_self_evolve.py        # self-evolve 实验性入口，后续会迁入 self_evolve/
├── self_evolve/              # 预留：self-evolve task/schema/runner/analysis
├── eval_matrix.yaml          # downstream BMK registry
├── generated_harness_adapter.py
├── harbor_generated_harness_agent.py
├── creation_eval/            # adapter、validator、benchmark dispatcher、summary schema
├── Dockerfile                # 评测容器镜像
├── entrypoint.sh             # 容器入口脚本
├── model-proxy.js            # LLM 请求代理（记录 metrics）
├── tools/tac_api_shim.py     # Mac Docker 本地 TheAgentCompany reset/health shim
├── config.yaml.example       # 配置模板
├── tasks.jsonl               # 任务定义
├── self_evolve_tasks.example.jsonl
├── prompts/                  # 提示词
│   ├── system_prompt.md      # 通用架构约束
│   ├── code_agent_harness.md
│   ├── data_analysis_harness.md
│   ├── writing_harness.md
│   ├── research_agent_harness.md
│   └── browser_agent_harness.md
├── research/                 # 调研文档
│   ├── 01_code_agent.md
│   ├── 02_data_analysis.md
│   ├── 03_writing_agent.md
│   ├── 04_research_agent.md
│   └── 05_browser_agent.md
└── outputs/                  # 本地生成产物，默认不提交
```
