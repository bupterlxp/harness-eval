# Agent Harness 构建任务：数据分析智能体（Notebook / Data Analysis）

你将为**数据分析**领域构建一个完整的 agent harness。本提示词是你的工作 spec，定义了方法论、形式化约束、交互规范和交付标准。

---

## 一、用户输入

### 1. 功能样例（FEATURE_EXAMPLE）

#### 1.1 理想输入（IDEAL_INPUT）

```
分析目标：基于 sales_data.csv 完成某电商平台 2024年1月销售数据的全面分析
数据文件：./samples/sales_data.csv
分析要求：
  1. 数据概览：行列数、缺失值、数据类型
  2. 销售趋势：按日汇总销售额时间序列，识别峰值/谷值
  3. 区域对比：各区域销售额排名与占比
  4. 品类分析：各品类销售额、平均折扣率、区域分布热力图
  5. 渠道分析：线上 vs 线下销售对比
  6. 关键发现：至少 3 条数据驱动的洞察 + 2 条可执行建议
金额计算公式：实际销售额 = quantity * unit_price * (1 - discount)
输出格式：Python 分析脚本 + 可视化图表 + 文字报告
```

#### 1.2 理想产出（IDEAL_OUTPUT）

完整分析规格存放在：**`./samples/analysis_spec.md`**

> 在阶段 1 开始之前，你必须先读取 `./samples/sales_data.csv` 和 `./samples/analysis_spec.md`。
> 理想产出的关键属性：
> - 一份可执行的 Python 分析脚本（含 pandas + matplotlib/seaborn）
> - 至少 5 张可视化图表（折线图、柱状图、饼图、热力图、对比图）
> - 所有数值计算准确，可通过手动抽查验证
> - 文字报告包含定量结论（具体数字），而非模糊描述
> - 代码中每一步的输出都经过验证（shape check, 空值 check, 数值合理性 check）

#### 1.3 中间过程预期（EXPECTED_TRAJECTORY）

```
1. 数据加载 → 读取 CSV，确认 schema 和行数
2. 数据质量检查 → 缺失值、异常值、类型校验
3. 数据预处理 → 类型转换、计算派生列（实际销售额）
4. 探索性分析 → 基本统计量、分布概览
5. 趋势分析 → 时间序列聚合、绘图、标注峰谷
6. 区域分析 → 分组聚合、排序、绘图
7. 品类分析 → 多维交叉、热力图
8. 渠道分析 → 分组对比
9. 验证 → 抽查计算结果的准确性
10. 报告生成 → 整合文字洞察 + 图表 + 建议
```

### 2. 交互形式（INTERACTION_SPEC）

- 命令行交互，支持 Notebook 式的逐步执行
- 每个分析步骤独立执行，展示中间结果（表格预览、图表预览）
- 数据变量在步骤间持久化（类似 Jupyter 的 kernel state）
- 支持回溯：用户可要求"重跑步骤 5 但改用周聚合"
- `/preview [var]` 展示变量的 head/shape/dtypes
- `/plot [last]` 重新展示最近生成的图表
- `/check [expr]` 执行一个验证表达式并返回结果
- `/export` 导出当前分析为独立 Python 脚本

---

## 二、形式化基础（不可妥协）

**H = (E, T, C, S, L, V)**

| 符号 | 组件 | 代码层面的硬性要求 |
|------|------|---------------------|
| **E** Execution Loop | 状态机：LOAD → QUALITY_CHECK → PREPROCESS → EXPLORE → TREND → REGION → CATEGORY → CHANNEL → VALIDATE → REPORT。支持步骤回溯（任意步骤可重新进入） |
| **T** Tool Registry | 数据加载器、统计计算器、可视化生成器、数据验证器、报告生成器。每个工具声明输入 DataFrame schema 和输出类型 |
| **C** Context Manager | 管理三类上下文：(1) 数据上下文（当前 DataFrame 的 schema + 统计摘要）(2) 分析历史（已完成步骤的结论）(3) 用户意图（分析目标和约束）。压缩策略：DataFrame 只保留 schema + 统计量，不保留原始数据 |
| **S** State Store | 核心：execution state（变量快照）。每步执行后自动 snapshot DataFrame 和中间变量。支持 rollback 到任意步骤 |
| **V** Evaluation Interface | JSONL trajectory：每步记录输入数据 shape、执行代码、输出 shape、验证结果、生成的图表路径 |
| **L** Lifecycle Hooks | pre_execute（检查输入 DataFrame 非空）、post_execute（验证输出合理性）、on_error（保存当前状态并提示）、pre_plot（检查数据量）、post_report（校验数字一致性） |

**关键判别准则**：
- E 的每个状态必须显式声明：输入变量、输出变量、验证条件
- S 必须支持步骤级回滚——用户说"重跑步骤 5"时，恢复到步骤 4 完成后的快照
- C 的 DataFrame 上下文**禁止**把整个 DataFrame 转成字符串塞进 prompt，必须用 schema + 统计摘要
- T 的可视化生成器必须返回图表文件路径（而非 plt.show()），以便 V 层追踪

---

## 三、样例驱动的差异比对准则

`./samples/sales_data.csv` 和 `./samples/analysis_spec.md` 是事实基准。

| 阶段 | 比对动作 |
|------|---------|
| **设计期** | E 的状态机是否覆盖 analysis_spec.md 的所有分析模块？T 的工具是否能生成所有要求的图表类型？ |
| **实现期** | 每个分析步骤的输出是否可以用 sales_data.csv 手动验证？ |
| **验证期** | 实跑后比对：(1) 是否覆盖全部 6 个分析模块 (2) 图表数量 ≥ 5 (3) 数值是否与手算一致 (4) 洞察是否有数据支撑 |

**核心数值验证点**（用 sales_data.csv 手算）：
- 总记录数 = 32 行
- 销售额计算示例：第 1 行 = 12 × 1299.00 × (1 - 0.05) = 14,808.60
- 总销售额 = 所有行销售额之和（harness 必须计算正确）

---

## 四、工作流程

### 阶段 1：理解与规划

1. **读取样例**：读取 `./samples/sales_data.csv` 和 `./samples/analysis_spec.md`
2. **数据理解**：描述数据结构（列含义、数据类型、值域）
3. **从样例反推架构**：推导 E/T/C/S/L/V 的设计
4. **领域故障分析**：
   - E 缺失 → 分析步骤无序，后续步骤依赖的变量未就绪
   - T 缺失 → 缺少验证器，数值错误无法发现
   - C 缺失 → DataFrame 全文塞进 prompt 导致 context 爆炸
   - S 缺失 → 无法回溯，修改分析参数要从头开始
   - L 缺失 → 空 DataFrame 进入可视化导致崩溃
   - V 缺失 → 无法追溯哪步分析产出了哪个结论
5. **工具清单**
6. **TodoWrite**

### 阶段 2：实现

```
harness/
├── __init__.py
├── schemas.py        # DataProfile, AnalysisStep, ChartRecord, Insight, ValidationResult
├── state.py          # S: ExecutionState + DataFrame 快照 + 变量注册表
├── tools.py          # T: ToolRegistry
├── context.py        # C: DataContext + AnalysisHistory + IntentContext
├── lifecycle.py      # L: pre/post execute hooks + validation hooks
├── evaluation.py     # V: JSONL trajectory
├── execution.py      # E: 分析状态机（支持回溯）
├── core.py           # H: 六组件聚合
├── cli.py            # 交互层（含 /preview /plot /check /export）
└── domain/
    ├── tools.py      # 数据加载器 / 统计计算器 / 可视化生成器 / 验证器 / 报告生成器
    └── prompts.py    # 分析 prompt 模板
samples/
├── sales_data.csv
└── analysis_spec.md
tests/
├── test_state_rollback.py    # 验证步骤回溯
├── test_data_validation.py   # 验证数值计算准确性
├── test_chart_generation.py  # 验证图表生成
└── test_e2e.py
```

### 阶段 3：验证与比对

1. 运行 pytest
2. 以 IDEAL_INPUT 运行 harness
3. 比对：
   - 分析模块覆盖度（6/6）
   - 图表数量（≥5）
   - 数值准确性（与手算比对）
   - 洞察质量（是否有数据支撑）
   - 步骤回溯是否正常（回到步骤 5 改用周聚合）

---

## 五、技术栈

- Python 3.11+，full type hints
- **LLM 调用必须使用 OpenAI 兼容接口**（`openai` Python SDK），**禁止使用 `anthropic` SDK**。配置从环境变量读取：
  - `OPENAI_BASE_URL`：API 端点地址（如 `http://127.0.0.1:3457/v1`）
  - `OPENAI_API_KEY`：API 密钥
  - `MODEL_NAME`：模型标识符
  - 调用方式：`client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])`，然后使用 `client.chat.completions.create(model=os.environ["MODEL_NAME"], ...)`
- pandas + matplotlib + seaborn（数据分析与可视化）
- 禁止 LangChain / LlamaIndex / AutoGen

---

## 六、交付清单

1. 完整性自检表
2. 样例比对报告（6 个分析模块 × 完成度 × 数值准确性）
3. 快速开始命令
4. 关键设计决策摘要
5. 下一步建议

---

## 七、禁止事项

- ❌ 不要省略代码
- ❌ 不要把六组件糅合
- ❌ 不要把 DataFrame 全文塞进 prompt
- ❌ 不要硬编码文件路径或数据值
- ❌ 不要跳过数据验证步骤
- ❌ 不要生成没有数据支撑的"洞察"

---

现在，请确认你已读取 `./samples/sales_data.csv` 和 `./samples/analysis_spec.md`，然后从**阶段 1**开始。
