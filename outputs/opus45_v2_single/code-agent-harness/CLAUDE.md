# Agent Harness 构建任务：代码智能体（Code Agent）

构建一个通用的代码智能体 harness，能接受软件工程任务描述（bug 修复、功能开发、重构等），自主完成代码修改并验证结果。

---

## 一、接口契约

### 输入（TaskSpec）

```python
{
    "task_type": str,          # "bug_fix" | "feature" | "refactor" | "test_gen"
    "description": str,        # 自然语言任务描述
    "repo_path": str,          # 目标仓库路径
    "test_command": str | None, # 验证命令（如 "pytest tests/"）
    "constraints": list[str],  # 附加约束
}
```

### 输出（Result）

```python
{
    "status": str,             # "success" | "partial" | "failed"
    "edits": list[{            # 所有文件变更
        "file": str,
        "diff": str
    }],
    "test_results": {          # 测试执行结果
        "passed": int,
        "failed": int,
        "errors": list[str]
    },
    "trajectory": str,         # JSONL trajectory 文件路径
}
```

### 入口

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`（符合上述 Result schema）
- 工作目录中可能包含任务所需的代码仓库、数据文件等，harness 应自动发现并使用

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

## 三、领域能力

harness 必须支持以下能力（实现方式自定）：

- **代码理解**：仓库结构扫描、代码搜索（关键字/模式）、函数/类级定位
- **多文件编辑**：生成 diff 补丁、跨文件原子修改、保持代码风格
- **测试驱动循环**：运行测试 → 分析失败 → 修复 → 重跑，直到通过或达到重试上限
- **版本控制**：原子化 commit、有意义的 commit message、修改可回滚
- **预算控制**：最大重试次数、最大 LLM 调用轮数，防止无限循环

---

## 四、验证标准

你的 harness 交付后，将通过以下方式验证：

### 结构验证（自动检查）

```bash
# 1. 能正常 import，无语法错误
python -c "import harness"

# 2. 六组件可独立识别（各自是独立模块）
python -c "from harness import execution, tools, context, state, lifecycle, evaluation"

# 3. CLI 入口可用
python -m harness --help

# 4. 有测试文件且能运行
python -m pytest tests/ --co -q  # 至少能 collect 到测试用例
```

### 功能验证（下游任务）

harness 将被用于处理实际的代码修复/开发任务，评测时关注：

- 状态机是否正确驱动了"理解→定位→修改→验证"的循环
- 修改失败时是否能回滚并尝试新方案
- trajectory 是否完整记录了每步决策
- 是否在预算内完成（未无限循环）

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。配置从环境变量读取：
  - `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：ast、subprocess、gitpython、tree-sitter
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、禁止事项

- ❌ 六组件糅合进一两个文件
- ❌ 用 `while True` + if 链替代显式状态机
- ❌ 把整个源文件内容拼进 LLM prompt
- ❌ 硬编码仓库路径或特定项目结构
- ❌ 省略代码（`...` 或 `TODO`）
- ❌ 无限重试无退出条件
