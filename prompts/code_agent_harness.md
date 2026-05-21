# Agent Harness 构建任务：代码智能体（Code Agent）

构建一个通用的代码智能体 harness，能接受软件工程任务描述（bug 修复、功能开发、重构等），自主完成代码修改并验证结果。

---

## 一、入口与输出

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`
- 工作目录中可能包含任务所需的代码仓库、数据文件等，harness 应自动发现并使用

`result.json` 必须包含以下字段，其余字段可自行扩展：

```python
{
    "status": str,       # "success" | "partial" | "failed"
    "trajectory": str,   # JSONL trajectory 文件路径
}
```

---

## 二、功能性质

一个成熟的代码智能体 harness 是一个状态机驱动的自主执行循环，运行 Thought→Action→Observation 三段式 ReAct 模式直到任务完成或预算耗尽。

**执行循环与终止控制。** 主循环维护显式状态（IDLE→RUNNING→FINISHED/STUCK/ERROR），每轮：构建 prompt → 调用 LLM → 解析工具调用 → 执行 → 检查终止条件。步数预算硬限（maxSteps），达到 75% 时注入预算警告要求优先保存已有成果。Doom Loop 检测：连续 3+ 次相同 tool+params 触发策略切换提示；连续 4 次相同 action+error 判定为 stuck 并强制终止。循环在明确成功信号（测试全过、显式 finish 调用）、步数/成本上限、或不可恢复错误时终止。

**代码导航与理解。** 分层发现机制：glob/find 扫描文件树结构获得布局感知，正则 grep 搜索符号和内容定位目标，定向行范围读取避免上下文溢出。高级模式包括：AST 解析生成仓库级结构概览（函数签名+类定义的 PageRank 排序摘要），LSP 集成提供 go-to-definition、find-references、hover 类型信息和诊断错误，语义搜索通过向量索引定位功能相关但命名无关的代码。

**代码编辑策略。** 编辑通过精确字符串替换实现（old_string → new_string），要求匹配唯一且先读后写。当 LLM 输出与实际文件存在轻微差异时，系统尝试多级模糊匹配回退（行首尾空白忽略 → 块锚点匹配 → 空白归一化 → 缩进灵活匹配），在保证安全性的前提下提高编辑成功率。支持多文件 patch 格式（Add/Update/Delete/Move）以单次操作修改多个文件。每次编辑后自动运行 linter/formatter/LSP 诊断，若引入语法错误则回滚编辑并将诊断信息暴露给模型重试。

**上下文管理与压缩。** 工具输出按字符/行数阈值截断（超长输出保存至文件并提供路径）。对话历史通过可组合处理器管道管理：旧步骤的 observation 替换为省略标记，已关闭的文件视图打标移除，最近 N 步保留完整原文。token 接近窗口上限时触发 LLM 驱动的摘要压缩（生成 Goal/Progress/Key Decisions/Next Steps 结构化摘要替换旧历史），保护最近 2 轮对话原文不被压缩。持久化指令（项目惯例、架构说明）每轮重新注入以在压缩中存活。仓库级概览（repo-map）按 token 预算动态生成，让模型始终了解项目全局结构。

**错误恢复。** API 调用失败时指数退避重试（初始 2s, 因子 2x, 尊重 retry-after 头, 上限 30s）。模型输出无法解析时自动添加格式错误消息重新 query（最多 3 次）。Bash 命令执行前做语法预检（bash -n），语法错误不执行而是直接反馈。工具名大小写错误自动修正。上下文溢出不重试，直接触发紧急压缩。致命错误退出时自动提取当前 git diff 作为兜底提交。

**版本管理与回滚。** 每次 LLM 编辑后可自动提交快照，支持回退到任意消息点。独立快照存储支持精确的多步回滚而不影响工作分支。worktree 隔离允许多个子任务在独立分支工作区并行执行。编辑前对脏文件先提交，确保 LLM 修改和用户修改可分别回滚。

**规划与子任务分解。** 支持独立的 Plan 模式（禁止代码编辑，只分析和规划），产出结构化计划文件后切换到 Build 模式执行。复杂任务可委派给子 agent：主 agent 通过 task 工具启动子 agent，每个子 agent 有独立权限范围和工作空间，支持前台阻塞或后台异步执行+轮询。多个无依赖子任务可并行启动。

**验证与质量保证。** 验证是测试驱动的：执行测试命令，捕获完整输出，将失败信息反馈给模型形成 edit→test→fix 紧密循环。Critic 评估系统在 agent 声称完成后评估质量，低于阈值自动触发修正轮次。提交前可展示 diff 要求自审（第一次 submit 展示 diff 确认，第二次才真正提交）。完整的 action-observation 对及时间戳、token 消耗写入 JSONL 轨迹文件。

---

## 三、调用示例

### Case 1：修复失败的单元测试（edit→test→fix 循环）

```bash
python -m harness -p "tests/test_utils.py 中的 test_parse_date 报错 ValueError: time data '2024-13-01' does not match format '%Y-%m-%d'，修复底层 bug" --output-dir ./output/
```

**行为轨迹：**
- Step 1：执行 `python -m pytest tests/test_utils.py::test_parse_date -x` 复现，捕获完整 traceback → observation 指向 `src/utils.py:47` 的 `parse_date()` 函数
- Step 2：读取 `src/utils.py` 第 40-60 行（定向行范围读取），识别函数直接将原始输入传给 `strptime` 无月份范围校验
- Step 3：grep 搜索 `parse_date` 在全项目中的调用点，确认公共 API 不变（3 个调用点，均传入字符串）
- Step 4：编辑 `src/utils.py`——精确替换裸 `datetime.strptime(date_str, fmt)` 为带 ValueError 捕获和月/日边界检查的版本。编辑后自动 linter 检查通过
- Step 5：执行 `python -m pytest tests/test_utils.py::test_parse_date -x`，通过（exit code 0）
- Step 6：执行 `python -m pytest tests/ -x --timeout=60` 全量测试确认无回归，38 passed
- 终止条件：测试全通过 + 显式调用 finish

**产物：** `src/utils.py`（修改），`trajectory.jsonl`（6 步，含每步时间戳和 token 消耗），git diff patch

---

### Case 2：添加新 API 端点（多文件协调 + 新建文件）

```bash
python -m harness -p "为 FastAPI 应用添加 GET /api/v1/health 端点，返回 {status: ok, version: <from pyproject.toml>}，附带测试" --output-dir ./output/
```

**行为轨迹：**
- Step 1：仓库结构发现——glob `**/*.py` 获得文件布局，grep `FastAPI` 定位入口 `src/server/app.py`
- Step 2：读取 `pyproject.toml` 提取版本号 `2.3.1`；读取 `src/server/app.py` 前 30 行理解路由注册模式和 import 风格
- Step 3：读取 `tests/` 目录结构，发现已有 `test_users.py` 使用 `TestClient` fixture 模式
- Step 4：编辑 `src/server/app.py` 插入 `get_health()` 路由函数——version 通过 `importlib.metadata.version()` 读取，保持既有 import 风格一致
- Step 5：新建 `tests/test_health.py`，复用已有 fixture 模式：TestClient + 断言 200 状态码 + JSON body 包含 status 和 version 字段
- Step 6：执行 `python -m pytest tests/test_health.py -v`，通过
- Step 7：执行 `mypy src/server/app.py` 类型检查通过（如项目有 mypy 配置）

**产物：** `src/server/app.py`（修改），`tests/test_health.py`（新建），`trajectory.jsonl`（7 步）

---

### Case 3：跨文件类型错误修复（LSP 诊断 + 上下游追踪）

```bash
python -m harness -p "mypy 报错 'Argument 1 to process_order has incompatible type Optional[Order]; expected Order' in src/checkout/handler.py:92，修复且不改公共 API" --output-dir ./output/
```

**行为轨迹：**
- Step 1：读取 `src/checkout/handler.py` 第 85-100 行，定位报错位置——`get_order(order_id)` 返回值直接传给 `process_order()`
- Step 2：grep `def get_order` 找到定义在 `src/orders/repository.py:28`，确认签名 `-> Optional[Order]`
- Step 3：grep `def process_order` 确认签名 `(order: Order)` 且被多处调用——不能修改为接受 Optional
- Step 4：分析约束：不能改 `get_order` 的返回类型（公共 API），不能改 `process_order` 的参数类型，只能在调用点加 guard
- Step 5：编辑 `src/checkout/handler.py` 第 91-92 行：在调用前加 `if order is None: raise OrderNotFoundError(order_id)`，import `OrderNotFoundError`
- Step 6：执行 `mypy src/checkout/handler.py --strict`，无报错
- Step 7：执行 `python -m pytest tests/test_checkout/ -v`，14 passed（含已有的 None case 测试）

**产物：** `src/checkout/handler.py`（修改），`trajectory.jsonl`（7 步）

---

### Case 4：大规模重构（规划模式 + 子任务 + 多次重试）

```bash
python -m harness -p "将 src/notifications/service.py 中的邮件发送逻辑抽取为 src/notifications/email_gateway.py 中的 EmailGateway 类，所有现有测试必须继续通过" --output-dir ./output/
```

**行为轨迹：**
- Step 1（分析阶段）：读取 `service.py`（148 行），识别提取目标——`send_email()`、`_build_mime_message()`、`_smtp_connect()` 三个方法及其依赖的实例变量
- Step 2：grep 搜索所有 import 和调用这些方法的位置，发现 `tests/test_notifications.py` 中 3 个测试直接 mock 了 `_smtp_connect`
- Step 3：制定重构计划（内部 think 步骤）：(a) 创建 EmailGateway 类封装三个方法 (b) 修改 service.py 依赖注入 (c) 更新测试 import
- Step 4：新建 `email_gateway.py`，包含 EmailGateway 类（封装 SMTP 配置和三个方法）
- Step 5：编辑 `service.py`——删除迁移的方法，添加 `from .email_gateway import EmailGateway`，在 `__init__` 中实例化
- Step 6：执行测试 → **失败**：`AttributeError: 'NotificationService' has no attribute '_smtp_connect'`——测试直接 mock 了旧路径
- Step 7（错误恢复）：读取失败测试，编辑 `tests/test_notifications.py` 更新 mock 路径为 `EmailGateway._smtp_connect`
- Step 8：执行测试 → **失败**：`ImportError: cannot import name 'EmailGateway'`——缺少 `__init__.py` 导出
- Step 9（第二次恢复）：编辑 `src/notifications/__init__.py` 添加 EmailGateway 导出
- Step 10：执行全量测试，23 tests passed，无 warning
- 预算消耗：10/30 步（33%），未触发预算警告

**产物：** `email_gateway.py`（新建），`service.py`（修改），`tests/test_notifications.py`（修改），`__init__.py`（修改），`trajectory.jsonl`（10 步，含 2 次 test-fix 重试循环）

---

### Case 5：大仓库中的 bug 定位（上下文压缩 + 语义搜索）

```bash
python -m harness -p "生产环境报错 'ConnectionPool exhausted after 30s timeout'，日志显示发生在用户并发登录高峰期。定位根因并修复" --output-dir ./output/
```

**行为轨迹：**
- Step 1：grep `ConnectionPool` 在全项目搜索，找到 5 个匹配——`src/db/pool.py`, `src/db/session.py`, `src/auth/login.py`, `src/config/database.py`, `tests/test_pool.py`
- Step 2：读取 `src/db/pool.py`，理解连接池初始化参数（max_size=10, timeout=30）
- Step 3：读取 `src/auth/login.py`，发现 `authenticate()` 函数获取连接但在异常路径未释放（try 块中 acquire，但 except 分支 return 前未 release）
- Step 4：grep `authenticate` 的调用频率相关信息，在 `src/auth/middleware.py` 发现每个请求都调用
- Step 5（think）：根因确认——并发登录时，认证失败的请求走异常路径泄漏连接，高峰期累积导致池耗尽
- Step 6：编辑 `src/auth/login.py`——将连接获取改为 `async with pool.acquire() as conn:` 上下文管理器模式，保证任何路径都释放
- Step 7：编辑 `tests/test_auth.py` 添加并发场景测试——模拟 20 个并发认证失败请求，断言连接池未泄漏
- Step 8：执行测试，通过
- 上下文管理：Step 1-4 的文件读取输出在 Step 6 时已触发 observation 截断（保留最近 5 步完整），前序步骤只保留 think 记录

**产物：** `src/auth/login.py`（修改），`tests/test_auth.py`（修改），`trajectory.jsonl`（8 步），`REPORT.md`（根因分析 + 修复说明）

---

## 四、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。配置从环境变量读取：
  - `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：ast、subprocess、gitpython、tree-sitter
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 五、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`）
- 安装系统级依赖（如需要）
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`
