# Agent Harness 构建任务：数字员工/浏览器工具智能体（Browser Agent）

你将为**浏览器自动化与多步骤 Web 任务执行**领域构建一个完整的 agent harness。本提示词是你的工作 spec，定义了方法论、形式化约束、交互规范和交付标准。

---

## 一、用户输入

### 1. 功能样例（FEATURE_EXAMPLE）

#### 1.1 理想输入（IDEAL_INPUT）

```
任务类型：企业HR系统多步骤操作自动化
目标：以管理员身份在内部HR管理系统中完成日常人事管理操作流程
系统地址：http://localhost:5000（本地Mock服务）
登录账号：admin / admin123
执行要求：
  1. 启动Mock服务（python mock_server.py）
  2. 打开登录页，处理Cookie弹窗，完成登录
  3. 在仪表盘提取待办事项和统计数据
  4. 在员工列表搜索"张"姓员工，查看某员工详情
  5. 审批请假申请（通过一条、拒绝一条并填写理由）
  6. 提交一份新的请假申请（年假，填写完整表单）
  7. 查看考勤报表，导出CSV
  8. 生成操作报告（含所有提取数据和截图）
约束：
  - 每个页面操作需等待加载完成后再执行
  - 遇到弹窗（Cookie consent、模态框）需正确处理
  - 页面加载失败需有重试机制（最多 3 次）
  - 需保留每步操作的截图作为执行证据
  - 跨页面时需正确维护登录session和已收集的信息
```

#### 1.2 理想产出（IDEAL_OUTPUT）

任务场景规格和Mock系统存放在 `./samples/` 目录：
- **`./samples/task_scenarios.json`** — 12步任务场景定义与评测标准
- **`./samples/mock_server.py`** — Flask 后端（含 SQLite 数据库、50名员工、15条请假记录、考勤数据）
- **`./samples/templates/`** — 8 个 HTML 页面（登录、仪表盘、员工列表、员工详情、请假审批、请假表单、报表中心、基础模板）

> 在阶段 1 开始之前，你必须先用 Read 工具读取 `./samples/task_scenarios.json` 和 `./samples/mock_server.py`，作为后续设计、实现、比对的事实基准。
> 理想产出的关键属性：
> - 12 个步骤全部完成，每步有状态记录
> - 表单交互正确：登录表单、请假表单（select/date/textarea）、搜索框
> - 弹窗处理正确：Cookie consent 横幅、拒绝理由模态框、提交成功模态框
> - 数据提取完整：仪表盘4项统计、员工6项信息、考勤率数据
> - 每步操作有对应截图
> - 遇到异常时有自动重试记录
> - 最终报告结构化输出（JSON + 可读文本）

#### 1.3 中间过程预期（EXPECTED_TRAJECTORY）

```
1. 环境初始化 → 启动 mock_server.py，启动浏览器实例，配置视口/超时
2. 打开登录页并处理弹窗 → 导航到 http://localhost:5000/login，检测底部 Cookie consent 横幅，点击"接受所有 Cookie"关闭横幅
3. 登录系统 → 填写用户名 admin + 密码 admin123，点击登录按钮，验证跳转到仪表盘
4. 查看仪表盘待办 → 提取四项统计（在职员工/待审批请假/新入职/合同到期），记录待办事项
5. 搜索员工 → 导航到 /employees，搜索"张"，记录结果数（约5条）和第一个员工姓名
6. 查看员工详情 → 点击第一个员工的"查看详情"，提取6项信息（姓名/部门/职位/入职日期/年假余额/绩效评分）
7. 审批请假-通过 → 导航到 /leave-requests，点击第一条待审批请假的"通过"按钮
8. 审批请假-拒绝 → 点击下一条待审批请假的"拒绝"按钮，在模态框中填写理由，确认
9. 提交请假申请 → 点击"提交请假申请"进入 /leave/new，填写完整表单（类型/日期/原因/联系人），提交，验证成功模态框
10. 查看考勤报表 → 导航到 /reports，提取技术部2024年1月出勤率
11. 导出CSV报表 → 点击"导出CSV"按钮，验证文件下载
12. 生成操作报告 → 汇总所有数据 + 截图 + 异常记录，输出结构化报告
```

### 2. 交互形式（INTERACTION_SPEC）

- 命令行交互，实时展示浏览器操作进度
- 每个页面操作展示简要描述（"正在访问 /employees..."）
- 关键操作（审批请假、提交表单）需用户确认
- 支持暂停和恢复执行
- `/screenshot` 立即截取当前页面
- `/state` 展示已收集的所有数据
- `/retry [step_id]` 重试指定步骤
- `/skip [step_id]` 跳过指定步骤并继续
- `/report` 基于已有数据生成部分报告

---

## 二、形式化基础（不可妥协）

**H = (E, T, C, S, L, V)**

| 符号 | 组件 | 代码层面的硬性要求 |
|------|------|---------------------|
| **E** Execution Loop | 两层状态机。外层：INIT → LOGIN → DASHBOARD → EMPLOYEES → LEAVE_MGMT → REPORTS → REPORT_GEN。内层（每个页面操作）：NAVIGATE → WAIT_LOAD → POPUP_CHECK → INTERACT → EXTRACT → SCREENSHOT → RECORD。支持 step-level retry 和 skip |
| **T** Tool Registry | 浏览器导航器（navigate/back/reload）、元素交互器（click/fill/select）、DOM 提取器（CSS selector/XPath）、截图器、弹窗处理器、等待器（wait_for_element/wait_for_load）、文件下载器。每个工具有超时和重试参数 |
| **C** Context Manager | 三层上下文：(1) 页面上下文（当前 URL + DOM 摘要 + 可交互元素列表）(2) 任务上下文（已完成步骤 + 已提取数据 + 待执行步骤）(3) 导航历史（支持回退决策）。压缩策略：DOM 摘要只保留关键元素，不保留完整 HTML |
| **S** State Store | 核心：task graph（有向图，节点=子任务，边=依赖）。每个节点有状态（pending/running/completed/failed/skipped）。维护跨页面数据（登录session + 提取的各项数据）。支持断点续跑 |
| **V** Evaluation Interface | JSONL trajectory：每步记录 URL、操作类型、操作目标元素、操作结果、截图路径、耗时、是否重试 |
| **L** Lifecycle Hooks | pre_navigate（记录来源 URL）、post_navigate（等待加载+弹窗检测）、pre_click（确认元素可见可点击）、on_timeout（截图+记录+重试决策）、on_popup（自动关闭策略）、pre_submit（需用户确认） |

**关键判别准则**：
- E 的外层和内层状态机**必须分离**——外层管理整体任务流程，内层管理单页面的操作流程
- S 的 task graph 必须支持**部分完成后恢复**——如果完成了登录和仪表盘但在员工搜索失败，恢复时从员工搜索开始
- C 的页面上下文**禁止**把完整 DOM 塞进 prompt，必须提取摘要（可交互元素列表 + 关键文本内容）
- T 的所有浏览器操作工具必须有**显式等待**——`click` 前必须 `wait_for_element`，`extract` 前必须 `wait_for_load`
- L 的弹窗处理必须是**非阻塞**的——检测到弹窗后关闭并继续原任务，而非中断整个流程

---

## 三、样例驱动的差异比对准则

`./samples/task_scenarios.json` 和 `./samples/mock_server.py` 是事实基准。

| 阶段 | 比对动作 |
|------|---------|
| **设计期** | E 的双层状态机能否覆盖 12 步流程？T 的工具是否覆盖所有交互类型（导航/点击/填写表单/选择下拉框/日期选择/处理弹窗/文件下载）？C 能否维护跨页面的登录session和已提取数据？ |
| **实现期** | 每个工具是否有超时和重试策略？弹窗处理是否覆盖三种类型（Cookie consent横幅/拒绝理由模态框/成功提示模态框）？表单填写是否覆盖所有元素类型（input/select/date/textarea）？ |
| **验证期** | (1) 12个步骤完成度 (2) 表单交互正确性（登录/审批/请假/搜索） (3) 数据提取完整性（仪表盘4项/员工6项/考勤率） (4) 弹窗处理覆盖度 (5) 跨页面数据一致性 (6) 异常恢复是否生效 (7) CSV导出是否成功 |

---

## 四、工作流程

### 阶段 1：理解与规划

1. **读取样例**：读取 `./samples/task_scenarios.json` 和 `./samples/mock_server.py`
2. **解析场景**：描述 12 步流程的依赖关系和关键风险点（弹窗、表单、模态框、文件下载）
3. **从样例反推架构**：推导 E/T/C/S/L/V 的设计
4. **领域故障分析**：
   - E 缺失 → 跨页面操作顺序混乱，登录后直接跳到报表忘记提取仪表盘数据
   - T 缺失 → 缺少等待机制，在mock server模拟延迟时操作失败
   - C 缺失 → 导航到新页面后丢失之前页面收集的数据，session丢失
   - S 缺失 → 中途失败后无法断点续跑，已审批的操作无法回滚
   - L 缺失 → Cookie弹窗阻塞整个流程，模态框无法处理
   - V 缺失 → 无法复现某个操作是在哪个页面上执行的
5. **工具清单**：
   - `navigate(url)` → safe
   - `click(selector)` → safe / needs_approval（审批/提交类按钮）
   - `fill(selector, text)` → safe
   - `select(selector, value)` → safe
   - `extract(selector)` → safe
   - `screenshot(path)` → safe
   - `wait_for(selector, timeout)` → safe
   - `close_popup(strategy)` → safe
   - `download_file(url, path)` → safe
   - `get_page_info()` → safe（返回 URL + title + 可交互元素摘要）
6. **TodoWrite**

阶段 1 完成后，把上述六项以摘要形式输出，然后**直接进入阶段 2**，不要等待用户确认。

### 阶段 2：实现

```
harness/
├── __init__.py
├── schemas.py        # TaskStep, PageState, EmployeeInfo, LeaveRequest, AttendanceReport, Screenshot
├── state.py          # S: TaskGraph + CrossPageDataStore + 断点快照
├── tools.py          # T: ToolRegistry
├── context.py        # C: PageContext + TaskContext + NavigationHistory
├── lifecycle.py      # L: 导航钩子 / 弹窗检测 / 元素可见性检查 / 超时处理 / 提交审批
├── evaluation.py     # V: JSONL trajectory
├── execution.py      # E: 双层状态机（外层任务流 + 内层页面操作流）
├── core.py           # H: 六组件聚合
├── cli.py            # 交互层（含 /screenshot /state /retry /skip /report）
└── domain/
    ├── tools.py      # 浏览器操作工具集
    ├── popup.py      # 弹窗识别与处理策略（Cookie consent / 模态框 / 提示框）
    └── prompts.py    # 元素定位 prompt / 数据提取 prompt / 报告生成 prompt
samples/
├── mock_server.py          # Flask后端 + SQLite + 50名员工预置数据
├── task_scenarios.json     # 12步任务场景
└── templates/              # 8个HTML页面
    ├── base.html           # 基础模板（导航栏 + Cookie弹窗 + Session过期弹窗）
    ├── login.html          # 登录页
    ├── dashboard.html      # 仪表盘
    ├── employees.html      # 员工列表（搜索/筛选/分页）
    ├── employee_detail.html # 员工详情
    ├── leave_requests.html # 请假审批
    ├── leave_form.html     # 请假表单
    └── reports.html        # 报表中心（表格 + Canvas图表 + CSV导出）
tests/
├── test_dual_state_machine.py    # 验证双层状态机切换
├── test_retry_mechanism.py       # 验证超时重试
├── test_cross_page_state.py      # 验证跨页面数据持久化
├── test_popup_handling.py        # 验证弹窗处理（3种类型）
├── test_form_interaction.py      # 验证表单填写（login/leave/search）
└── test_e2e.py                   # 端到端：启动mock server + 跑完12步
```

### 阶段 3：验证与比对

1. pytest 全绿
2. 启动 mock_server.py，以 IDEAL_INPUT 运行 harness
3. 比对：
   - 步骤完成度（12/12 或说明为何跳过）
   - 表单交互正确性（登录/审批/请假/搜索共4种表单）
   - 弹窗处理覆盖度（Cookie consent / 拒绝模态框 / 成功模态框）
   - 数据提取完整度（仪表盘4项 + 员工6项 + 考勤率）
   - 截图覆盖度
   - 重试机制是否在超时时触发
   - 断点续跑是否正常
   - CSV导出是否成功

---

## 五、技术栈

- Python 3.11+，full type hints
- **LLM 调用必须使用 OpenAI 兼容接口**（`openai` Python SDK），**禁止使用 `anthropic` SDK**。配置从环境变量读取：
  - `OPENAI_BASE_URL`：API 端点地址（如 `http://127.0.0.1:3457/v1`）
  - `OPENAI_API_KEY`：API 密钥
  - `MODEL_NAME`：模型标识符
  - 调用方式：`client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])`，然后使用 `client.chat.completions.create(model=os.environ["MODEL_NAME"], ...)`
- Playwright / Selenium（浏览器自动化）
- Flask（已在 mock_server.py 中使用，运行目标系统）
- 禁止 LangChain / LlamaIndex / AutoGen

---

## 六、交付清单

1. 完整性自检表
2. 样例比对报告（12 步骤 × 完成度 × 表单交互 × 弹窗处理 × 数据提取）
3. 快速开始命令
4. 关键设计决策（双层状态机划分 / 弹窗策略 / DOM 摘要粒度 / 重试策略 / 表单填写策略）
5. 下一步建议

---

## 七、禁止事项

- ❌ 不要省略代码
- ❌ 不要把六组件糅合
- ❌ 不要把完整 DOM 塞进 prompt
- ❌ 不要在未等待加载的情况下操作元素
- ❌ 不要让弹窗阻塞整个流程
- ❌ 不要跳过截图步骤（这是执行证据）
- ❌ 不要在未经用户确认的情况下执行审批/提交操作
- ❌ 不要硬编码Mock系统的DOM结构——使用语义化选择器（aria-label、placeholder、文本内容）

---

现在，请确认你已读取 `./samples/task_scenarios.json` 和 `./samples/mock_server.py`，然后从**阶段 1**开始。
