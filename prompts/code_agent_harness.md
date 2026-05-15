# Agent Harness 构建任务：代码智能体（Code Agent）

你将为**代码智能体**领域构建一个完整的 agent harness。本提示词是你的工作 spec，定义了方法论、形式化约束、交互规范和交付标准。

---

## 一、用户输入

### 1. 功能样例（FEATURE_EXAMPLE）

样例包含三块内容，作为 harness 的**事实基准（ground truth）**。

#### 1.1 理想输入（IDEAL_INPUT）

用户在调用 harness 时提交的任务规格，形如：

```
任务类型：Bug 修复
目标仓库：当前工作目录下的 Python HTTP 服务项目
问题描述：
  该任务管理服务存在多个 bug，导致部分 API 行为不正确。
  已知问题包括：
  - 部分接口无法正确处理非 ASCII 字符
  - 筛选逻辑在多条件组合时返回错误结果
  - 存在 SQL 注入风险
  - 某些数据库操作的时序有误
  - 删除操作对不存在资源的处理不规范
  - 更新操作未维护时间戳
约束：
  - 必须通过所有已有测试用例（test_server.py）
  - 修复不能改变 API 接口契约（请求/响应格式不变）
  - 每个 bug 单独一个 commit，commit message 需说明修了什么以及为什么
  - 优先修复安全类 bug（SQL 注入）
```

#### 1.2 理想产出（IDEAL_OUTPUT）

- 修复后的 `buggy_server.py`（所有 8 个 bug 均已修复）
- 所有测试通过（`python -m pytest test_server.py` 全绿）
- 8 个独立的 git commit，每个对应一个 bug
- 修复优先级：安全 > 正确性 > 规范性

bug 清单存放在源码注释中（标记为 `# BUG 1` ~ `# BUG 8`）：
1. `_send_json` 未将 JSON 编码为 bytes，非 ASCII 字符崩溃
2. `_handle_list_tasks` 多条件筛选用了 OR 而非 AND
3. `_handle_list_tasks` 缺少 ORDER BY，结果不确定
4. `_handle_get_task` 存在 SQL 注入（字符串拼接而非参数化查询）
5. `_handle_create_task` 对无效 status 静默纠正而非返回错误
6. `_handle_create_task` 在关闭连接后仍尝试查询
7. `_handle_update_task` 未更新 `updated_at` 字段
8. `_handle_delete_task` 删除不存在的任务返回 200 而非 404

#### 1.3 中间过程预期（EXPECTED_TRAJECTORY）

harness 在修复这些 bug 时，应当大体经历如下步骤：

```
1. 代码索引 → 扫描项目结构，识别主要源文件和测试文件
2. 测试运行 → 运行现有测试，收集失败用例及错误信息
3. 失败分类 → 将失败按根因分类（安全/逻辑/规范/时序）
4. 优先排序 → 安全类 > 正确性 > 规范性
5. 逐 bug 修复循环：
   a. 定位 → 根据失败信息定位到具体代码行
   b. 分析 → 理解 bug 根因和影响范围
   c. 修复 → 编写最小化修复代码
   d. 验证 → 运行相关测试确认修复有效且无回归
   e. 提交 → 生成结构化 commit message
6. 全量回归 → 运行全部测试确保无交叉影响
7. 修复报告 → 生成修复摘要（bug 列表 × 修复方案 × 验证状态）
```

### 2. 交互形式（INTERACTION_SPEC）

与 Claude Code 一致：
- 命令行交互（CLI），支持单次任务和多轮对话
- 流式输出
- 工具调用前展示意图、调用后展示结果摘要
- 危险操作（修改文件、执行命令、git commit）需审批
- 支持 `/` 命令（`/clear`、`/compact`、`/resume`、`/test`、`/status`）
- 中断信号（Ctrl+C）优雅终止并保存当前进度
- `/test [pattern]` 运行测试并展示结果
- `/status` 展示当前修复进度（已修/未修/阻塞）

---

## 二、形式化基础（不可妥协）

你构建的 harness 必须严格对应六元组：

**H = (E, T, C, S, L, V)**

| 符号 | 组件 | 代码层面的硬性要求 |
|------|------|---------------------|
| **E** Execution Loop | 显式状态机（enum 定义状态：INDEX → TEST → CLASSIFY → PRIORITIZE → FIX_LOOP(LOCATE→ANALYZE→FIX→VERIFY→COMMIT) → REGRESSION → REPORT），δ 函数覆盖所有事件含异常 |
| **T** Tool Registry | Pydantic schema 声明 IO：代码搜索器、文件编辑器、测试运行器、git 操作器、静态分析器。注册时校验，失败有结构化异常 |
| **C** Context Manager | 独立模块：管理源码上下文（当前文件±N行）、测试输出上下文、修复历史上下文。实现压缩/检索/优先级三接口 |
| **S** State Store | 维护 bug 列表及每个 bug 的状态（pending/fixing/fixed/blocked）、当前修复进度、已提交 commit 列表。支持 commit/recover/snapshot |
| **L** Lifecycle Hooks | pre/post hook：文件修改前备份、测试前记录快照、commit 前校验、修复失败时回滚 |
| **V** Evaluation Interface | 结构化 JSONL trajectory，每步记录：当前状态、操作、代码 diff、测试结果、耗时 |

**关键判别准则**：
- E 的 `step()` 必须显式 `match` 当前 state，**禁止 `while True` + if 链**
- 修复循环中 LOCATE→ANALYZE→FIX→VERIFY→COMMIT 是嵌套状态机，VERIFY 失败回到 ANALYZE 而非从头开始
- T 的测试运行器必须支持选择性运行（只跑相关测试）和全量运行
- S 在每次文件修改前必须做 snapshot，支持单 bug 级别的回滚

---

## 三、样例驱动的差异比对准则

`./samples/buggy_server.py` 和 `./samples/test_server.py` 是你工作的事实基准。

| 阶段 | 比对动作 |
|------|---------|
| **设计期** | 确认 E 的状态机能覆盖 EXPECTED_TRAJECTORY 的每一步；T 的工具集能支持代码定位、编辑、测试、提交全流程 |
| **实现期** | 每实现一个组件，确认它在样例修复场景中的具体作用 |
| **验证期** | 以 IDEAL_INPUT 为输入运行 harness，比对：(1) 是否发现所有 8 个 bug (2) 修复顺序是否合理 (3) 每个 commit 是否原子化 (4) 全部测试是否通过 |

---

## 四、工作流程

### 阶段 1：理解与规划

1. **读取样例**：用 Read 工具完整读取 `./samples/buggy_server.py` 和 `./samples/test_server.py`
2. **解析样例**：列出所有 bug 及其类型、严重等级、修复难度
3. **从样例反推架构**：推导 E/T/C/S/L/V 各组件的具体设计
4. **领域故障分析**：列出代码修复场景下各组件缺失的后果
5. **工具清单**：列出必需工具及其 IO schema
6. **TodoWrite**：拆分为原子实现任务

阶段 1 完成后，把上述六项以摘要形式输出，然后**直接进入阶段 2**，不要等待用户确认。

### 阶段 2：实现

```
harness/
├── __init__.py
├── schemas.py        # Pydantic 模型：BugReport, FixAttempt, TestResult, CommitRecord
├── state.py          # S: BugTracker + 修复进度 + snapshot
├── tools.py          # T: ToolRegistry + Tool 基类
├── context.py        # C: 源码上下文 + 测试输出上下文 + 修复历史
├── lifecycle.py      # L: 文件备份 / 测试快照 / commit 校验 / 回滚
├── evaluation.py     # V: JSONL trajectory recorder
├── execution.py      # E: 修复状态机
├── core.py           # H: 六组件聚合
├── cli.py            # 交互层
└── domain/
    ├── tools.py      # 代码搜索器 / 文件编辑器 / 测试运行器 / git 操作器 / 静态分析器
    └── prompts.py    # bug 分析 prompt / 修复建议 prompt / commit message prompt
samples/
├── buggy_server.py   # 含 8 个 bug 的服务端代码
└── test_server.py    # 测试套件（全部通过 = 修复完成）
tests/
├── test_state_machine.py
├── test_fix_rollback.py
├── test_commit_atomicity.py
└── test_e2e.py
```

### 阶段 3：验证与比对

1. 运行 `pytest`
2. 以 IDEAL_INPUT 运行 harness，验证：
   - 发现的 bug 数 = 8
   - 修复的 bug 数 = 8
   - 测试通过率 = 100%
   - commit 数 = 8（每个 bug 一个）
   - 安全类 bug（#4 SQL 注入）优先于其他
3. 生成完整性自检表和比对报告

---

## 五、技术栈

- Python 3.11+，full type hints
- **LLM 调用必须使用 OpenAI 兼容接口**（`openai` Python SDK），**禁止使用 `anthropic` SDK**。配置从环境变量读取：
  - `OPENAI_BASE_URL`：API 端点地址（如 `http://127.0.0.1:3457/v1`）
  - `OPENAI_API_KEY`：API 密钥
  - `MODEL_NAME`：模型标识符
  - 调用方式：`client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])`，然后使用 `client.chat.completions.create(model=os.environ["MODEL_NAME"], ...)`
- 禁止 LangChain / LlamaIndex / AutoGen
- 可使用 ast 模块做静态分析，subprocess 运行测试，gitpython 做 git 操作

---

## 六、交付清单

1. 完整性自检表（六组件 × 实现等级）
2. 样例比对报告（8 个 bug × 发现/修复/验证状态）
3. 快速开始命令
4. 关键设计决策摘要
5. 下一步建议

---

## 七、禁止事项

- ❌ 不要省略代码
- ❌ 不要把六组件糅合
- ❌ 不要用 `print` 替代 V 层
- ❌ 不要硬编码路径
- ❌ 不要跳过阶段 1
- ❌ 不要一次性修复所有 bug 再提交（每个 bug 必须独立 commit）

---

现在，请确认你已读取 `./samples/buggy_server.py` 和 `./samples/test_server.py`，然后从**阶段 1**开始。
