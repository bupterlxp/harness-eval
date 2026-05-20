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

## 二、架构约束 H = (E, T, C, S, L, V)

实现必须包含以下六个**可独立识别**的组件，对应模块名为 `execution`, `tools`, `context`, `state`, `lifecycle`, `evaluation`：

| 组件 | 职责 | 硬性要求 |
|------|------|----------|
| **E** Execution Loop | 驱动任务推进 | 显式状态机（禁止 `while True` + if 链）。必须支持嵌套子循环（如"编辑→测试→失败→重新编辑"） |
| **T** Tool Registry | 注册和调用工具 | 每个工具有明确的输入输出 schema。至少覆盖文件读写、代码搜索、命令执行能力，可自行扩展 |
| **C** Context Manager | 管理 LLM 的上下文窗口 | 禁止将整个文件内容拼入 prompt。必须实现摘要/压缩策略 |
| **S** State Store | 持久化运行状态 | 支持 snapshot 和 rollback。文件修改可撤回。崩溃可从最后 snapshot 恢复 |
| **L** Lifecycle Hooks | 边界事件处理 | 至少覆盖：操作前备份、失败时回滚、超时中断保存 |
| **V** Evaluation | 记录结构化轨迹 | 输出 JSONL，每步记录：状态、操作、结果、耗时 |

---

## 三、功能性质

一个成熟的代码智能体 harness 是一个自主执行循环：接收自然语言任务描述后，将其分解为工具调用步骤，迭代执行直到验证完成或预算耗尽。它通过分层发现导航代码库——glob/find 扫描文件树结构，正则 grep 搜索内容，定向行范围读取避免上下文溢出。编辑通过精确匹配字符串替换（old_string → new_string）实现，带有唯一性和先读后写守卫以保证原子性、防止过时覆写。验证是测试驱动的：执行 shell 命令，捕获 stdout/stderr/exit-code，将失败信息反馈给模型，模型重新编辑并重跑，形成紧密的 edit→test→fix 循环。当工具返回错误（语法失败、匹配冲突、超时），harness 将原始诊断信息暴露给模型而非崩溃，让 LLM 自主修正策略。上下文管理至关重要：工具输出按 token 预算截断，对话历史满窗时通过摘要压缩，持久化指令（项目惯例、架构说明）每轮重新注入以在压缩中存活。循环在收到明确成功信号（测试全过、干净 diff）、达到步数/成本上限、或遇到不可恢复错误时终止，并输出结构化轨迹记录每个 action-observation 对及时间戳和 token 消耗。

---

## 四、调用示例

### Case 1：修复失败的单元测试

```bash
python -m harness -p "tests/test_utils.py 中的 test_parse_date 报错 ValueError: time data '2024-13-01' does not match format '%Y-%m-%d'，修复底层 bug" --output-dir ./output/
```

**行为轨迹：**
- 执行 `python -m pytest tests/test_utils.py::test_parse_date -x` 复现，捕获 traceback 指向 `src/utils.py:47` 的 `parse_date()`
- 读取 `src/utils.py` 第 40-60 行，识别函数直接将原始输入传给 `strptime` 无月份范围校验
- 编辑 `src/utils.py`：替换裸 `datetime.strptime(date_str, fmt)` 为带 ValueError 捕获和月/日边界检查的版本
- 重跑测试，通过（exit code 0）；再跑全量测试确认无回归

**产物：** `src/utils.py`（修改），`trajectory.jsonl`（5 步），git diff patch

---

### Case 2：添加新 API 端点

```bash
python -m harness -p "为 FastAPI 应用添加 GET /api/v1/health 端点，返回 {status: ok, version: <from pyproject.toml>}，附带测试" --output-dir ./output/
```

**行为轨迹：**
- Grep 搜索 `FastAPI` 定位入口 `src/server/app.py`，读取 `pyproject.toml` 提取版本号 `2.3.1`
- 读取 `src/server/app.py` 前 30 行理解路由结构和 import 风格
- 编辑插入 `get_health()` 路由函数，version 通过 `importlib.metadata` 读取
- 写入 `tests/test_health.py`：TestClient fixture + 断言 200 状态和 JSON body
- 执行 `python -m pytest tests/test_health.py -v`，通过

**产物：** `src/server/app.py`（修改），`tests/test_health.py`（新建），`trajectory.jsonl`

---

### Case 3：跨文件类型错误修复

```bash
python -m harness -p "mypy 报错 'Argument 1 to process_order has incompatible type Optional[Order]; expected Order' in src/checkout/handler.py:92，修复且不改公共 API" --output-dir ./output/
```

**行为轨迹：**
- 读取 `src/checkout/handler.py` 第 85-100 行，发现 `get_order(order_id)` 返回 `Optional[Order]` 直接传给 `process_order`
- Grep 找到 `get_order` 签名确认返回类型
- 编辑：在调用前加 None-guard `if order is None: raise OrderNotFoundError(order_id)`
- 运行 `mypy src/checkout/handler.py`，无报错；运行测试，14 passed

**产物：** `src/checkout/handler.py`（修改），`trajectory.jsonl`（5 步）

---

### Case 4：带重试循环的重构

```bash
python -m harness -p "将 src/notifications/service.py 中的邮件发送逻辑抽取为 src/notifications/email_gateway.py 中的 EmailGateway 类，所有现有测试必须继续通过" --output-dir ./output/
```

**行为轨迹：**
- 读取 `service.py`（148 行），识别 `send_email()`、`_build_mime_message()`、`_smtp_connect()` 为提取目标
- 写入 `email_gateway.py` 包含 EmailGateway 类
- 编辑 `service.py`：删除方法，加 import，替换调用
- 跑测试，失败：`AttributeError: 'NotificationService' has no attribute 'email_gateway'`——编辑 `__init__` 添加实例化
- 再跑，失败：`ImportError` 在测试文件——编辑测试 import 路径。再跑，23 tests passed

**产物：** `email_gateway.py`（新建），`service.py`（修改），测试文件（修改），`trajectory.jsonl`（7 步含 2 次重试）

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。配置从环境变量读取：
  - `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：ast、subprocess、gitpython、tree-sitter
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`）
- 安装系统级依赖（如需要）
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`
