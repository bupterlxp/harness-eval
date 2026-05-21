# Harness Eval

用 LLM 驱动 coding agent 自动生成 agent harness，并评估不同模型的构建能力。

核心假设：**如果一段 prompt 足够好，强模型应该能从中生成结构完整、可运行的 agent 系统**。本项目用这种方式同时评估 prompt 质量和模型能力。

---

## 整体流程

```
研究 → 提示词 → 生成 → 验证
```

1. **调研**（`research/`）：分析各领域生产级 agent 的实现模式，提炼共性架构
2. **提示词设计**（`prompts/`）：将调研结论转化为结构化 prompt，定义功能要求和调用示例
3. **生成**（`run.py` + Docker）：将 prompt 喂给 coding agent（Claude Code），在隔离容器中生成完整 harness
4. **验证**（`outputs/`）：检查产物是否符合架构约束、能否导入运行、代码质量如何

```
┌─────────────────────────────────────────────────┐
│  Docker Container                                │
│                                                  │
│  Claude Code ──► model-proxy(:3457)              │
│                      │  记录 metrics.json        │
│                      ▼                           │
│               claude-code-router(:3456)          │
│                      │                           │
│                      ▼                           │
│               外部 LLM API (万卿/OpenAI/...)     │
└─────────────────────────────────────────────────┘
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

### 两层结构

```
prompts/
├── system_prompt.md          # 通用架构约束（ETCSLV），所有 harness 共享
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

### Docker 模式（评测用）

```bash
# 1. 安装依赖
pip install pyyaml

# 2. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入 API 地址、密钥和模型名称

# 3. 运行
python3 run.py
```

### 任务格式（tasks.jsonl）

```jsonl
{"id": "code-agent", "prompt_file": "./prompts/code_agent_harness.md"}
{"id": "data-analysis", "prompt_file": "./prompts/data_analysis_harness.md"}
{"id": "writing", "prompt_file": "./prompts/writing_harness.md"}
{"id": "research", "prompt_file": "./prompts/research_agent_harness.md"}
{"id": "browser", "prompt_file": "./prompts/browser_agent_harness.md"}
```

### 配置说明（config.yaml）

```yaml
base_url: "https://your-api-endpoint/v1"
api_key: "your-api-key"
model_name: "your-model-name"

max_concurrent: 4        # 并行容器数
timeout_minutes: 30      # 单任务超时
output_dir: "./outputs"
tasks_file: "./tasks.jsonl"
```

### 输出结构

```
outputs/
├── summary.json             # 汇总统计
└── <task-id>/
    ├── meta.json            # 任务状态 + metrics 摘要
    ├── metrics.json         # 请求级 token 用量
    ├── claude_output.log    # Claude Code 完整日志
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

---

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

## 项目结构

```
harness-eval/
├── README.md                 # 本文件
├── REPORT.md                 # 详细评测报告
├── run.py                    # 评测运行器（Docker 模式）
├── Dockerfile                # 评测容器镜像
├── entrypoint.sh             # 容器入口脚本
├── model-proxy.js            # LLM 请求代理（记录 metrics）
├── config.yaml.example       # 配置模板
├── tasks.jsonl               # 任务定义
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
└── outputs/                  # 生成产物
    ├── opus4_showcase/       # Opus 4 showcase（5 个完整 harness）
    ├── opus45/               # Opus 4.5 Docker 模式输出
    ├── opus45_v2/            # Opus 4.5 v2 prompt 输出
    └── doubao_v2/            # Doubao Docker 模式输出
```
