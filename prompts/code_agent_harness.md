# 构建代码智能体 Harness

构建一个 Python 代码智能体：接收自然语言任务描述，通过 LLM 驱动的循环自主完成代码修改并验证结果。

---

## 接口

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

执行完成后在 `--output-dir` 下生成：
- `result.json`：`{"status": "success"|"partial"|"failed", "trajectory": "trajectory.jsonl"}`
- `trajectory.jsonl`：每行一个 JSON，记录每步的 action 和 observation

---

## 文件结构

你必须创建以下文件结构：

```
harness/
  __init__.py        # 空文件或简短描述
  __main__.py        # 入口：从 agent 模块导入 main 并执行
agent.py 或其他模块   # 主要逻辑（也可以把所有代码放在 __main__.py 中）
Dockerfile
requirements.txt
```

关键：`python -m harness` 要求 `harness/` 目录下有 `__main__.py` 文件。最简单的做法是把所有代码放在 `harness/__main__.py` 中。

---

## 代码骨架

以下是**完整可运行的骨架代码**。你必须基于它构建 harness，保留核心结构（LLM 调用循环 + tool calling），按需扩展工具实现和错误处理。

**⚠️ 关键约束：骨架中的以下全局变量必须保留，禁止删除、重命名或移到函数内部：**
- `client = OpenAI(...)` — LLM 客户端实例
- `MODEL = os.environ.get("MODEL_NAME", "gpt-4")` — 模型名称
- `SYSTEM_PROMPT = """..."""` — 系统提示词
- `TOOLS = [...]` — 工具定义列表
你可以修改它们的内容，但变量名和初始化位置必须保持在模块顶层。

```python
#!/usr/bin/env python3
"""Code Agent Harness - 自主代码修改智能体"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from openai import OpenAI

# ── 配置 ─────────────────────────────────────────────
client = OpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.environ.get("OPENAI_API_KEY", "sk-placeholder"),
)
MODEL = os.environ.get("MODEL_NAME", "gpt-4")

SYSTEM_PROMPT = """You are a code agent. You can read files, write files, search code, and run shell commands.
Given a task, analyze the codebase, make necessary changes, and verify your work by running tests.
When you are done, call the 'finish' tool with the final status."""

# ── 工具定义（OpenAI function calling 格式）────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "start_line": {"type": "integer", "description": "Start line (1-based, optional)"},
                    "end_line": {"type": "integer", "description": "End line (optional)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in files using grep",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "path": {"type": "string", "description": "Directory to search in (default '.')"},
                    "file_pattern": {"type": "string", "description": "File glob pattern (e.g. '*.py')"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')"},
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the task is complete",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["success", "partial", "failed"]},
                    "summary": {"type": "string", "description": "Brief summary of what was done"},
                },
                "required": ["status"],
            },
        },
    },
]


# ── 工具执行 ──────────────────────────────────────────
def execute_tool(name: str, args: dict) -> str:
    """执行工具调用，返回结果字符串。"""
    try:
        if name == "read_file":
            path = args["path"]
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            start = args.get("start_line", 1) - 1
            end = args.get("end_line", len(lines))
            selected = lines[max(0, start):end]
            numbered = [f"{i+start+1}: {line}" for i, line in enumerate(selected)]
            return "".join(numbered)[:10000]

        elif name == "write_file":
            path = args["path"]
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return f"File written: {path} ({len(args['content'])} chars)"

        elif name == "run_command":
            timeout = args.get("timeout", 60)
            result = subprocess.run(
                args["command"], shell=True, capture_output=True, text=True, timeout=timeout
            )
            output = f"Exit code: {result.returncode}\n"
            if result.stdout:
                output += f"STDOUT:\n{result.stdout[:5000]}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr[:3000]}\n"
            return output

        elif name == "search_code":
            pattern = args["pattern"]
            path = args.get("path", ".")
            file_pattern = args.get("file_pattern", "")
            cmd = f"grep -rn '{pattern}' {path}"
            if file_pattern:
                cmd += f" --include='{file_pattern}'"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return result.stdout[:5000] if result.stdout else "No matches found."

        elif name == "list_files":
            path = args.get("path", ".")
            pattern = args.get("pattern", "*")
            from glob import glob
            files = glob(os.path.join(path, pattern), recursive=True)
            return "\n".join(sorted(files)[:100])

        elif name == "finish":
            return f"FINISH: {args.get('status', 'success')}"

        else:
            return f"Error: Unknown tool '{name}'"

    except Exception as e:
        return f"Error executing {name}: {str(e)}"


# ── Agent 主循环 ──────────────────────────────────────
def run_agent(task: str, output_dir: str, max_steps: int = 30):
    """运行 agent 主循环。"""
    os.makedirs(output_dir, exist_ok=True)
    trajectory_path = os.path.join(output_dir, "trajectory.jsonl")
    result_path = os.path.join(output_dir, "result.json")
    trajectory_file = open(trajectory_path, "w", encoding="utf-8")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    final_status = "failed"

    for step in range(max_steps):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            # 记录错误并重试
            entry = {"step": step, "error": str(e), "timestamp": time.time()}
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(2)
            continue

        choice = response.choices[0]
        assistant_msg = choice.message

        # 将 assistant 回复加入对话
        messages.append(assistant_msg.model_dump())

        # 如果没有 tool calls，检查是否结束
        if not assistant_msg.tool_calls:
            entry = {
                "step": step,
                "action": "text_response",
                "content": assistant_msg.content or "",
                "timestamp": time.time(),
            }
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # 如果模型直接回复文本（没调用工具），可能是表达想法或总结
            # 继续循环让模型调用工具
            continue

        # 执行所有 tool calls
        for tool_call in assistant_msg.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            # 执行工具
            result = execute_tool(func_name, func_args)

            # 记录 trajectory
            entry = {
                "step": step,
                "action": func_name,
                "args": func_args,
                "observation": result[:2000],
                "timestamp": time.time(),
            }
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # 将工具结果加入对话
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

            # 检查是否完成
            if func_name == "finish":
                final_status = func_args.get("status", "success")
                trajectory_file.close()
                # 写 result.json
                with open(result_path, "w") as f:
                    json.dump({"status": final_status, "trajectory": trajectory_path}, f, indent=2)
                return final_status

    # 达到步数上限
    trajectory_file.close()
    with open(result_path, "w") as f:
        json.dump({"status": final_status, "trajectory": trajectory_path}, f, indent=2)
    return final_status


# ── CLI 入口 ──────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Code Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps")
    args = parser.parse_args()

    print(f"Running code agent: {args.prompt[:100]}...")
    status = run_agent(args.prompt, args.output_dir, args.max_steps)
    print(f"Done. Status: {status}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
```

---

## 核心能力要求

基于上面的骨架，你需要确保 harness 具备以下能力：

- **文件读写**：读取源代码，写入修改后的代码
- **代码搜索**：通过 grep/glob 在项目中搜索关键词和模式
- **命令执行**：运行测试命令（pytest、npm test 等），捕获输出
- **编辑-测试循环**：修改代码 → 运行测试 → 如果失败则分析错误并重新修改
- **结构化输出**：`result.json` + `trajectory.jsonl`

---

## 必须实现的扩展

以下扩展是骨架中**未提供实现**的，你必须自己编写代码完成。

### 通用扩展（必须实现）

**1. LLM 调用错误重试**
- API 调用失败时指数退避重试（初始 2s，因子 2x，上限 30s，至少重试 3 次）
- 区分可重试错误（超时、429 rate limit、5xx）和不可重试错误（401/403）
- 尊重 API 返回的 retry-after 头
- 重试耗尽后记录错误到 trajectory 并继续（不直接 crash）

**2. 上下文窗口管理**
- 监控消息历史总长度（字符数或 token 估算）
- 超过阈值时分级压缩：Level 1 截断旧步骤的工具输出（保留前 N 字符 + "[truncated]"）→ Level 2 移除更早的完整轮次 → Level 3 用摘要替换历史
- 始终保护 system prompt 和最近 N 轮完整对话不被压缩
- 工具单次输出超过阈值时立即截断

**3. 重复动作检测与 Doom Loop 防护**
- 追踪最近 N 步的 action + 参数
- 连续 3 次相同 tool + 相同参数 → 注入提示要求换策略
- 连续 5 次仍重复 → 强制切换策略或终止
- 在 trajectory 中标记检测到的重复事件

**4. 步数预算管理与优雅结束**
- 达到 max_steps 的 75% 时注入预算警告，要求优先保存已有成果
- 达到步数上限时保存部分结果（而非空输出）
- 任何未捕获异常都写入 result.json（status="error"），不应出现无 result.json 的情况
- result.json 中明确区分 success / partial / failed / error 四种状态

**5. 工具执行鲁棒性**
- 每个工具调用设置超时（防止无限挂起）
- 工具参数校验（缺少必填参数时返回明确错误信息而非 crash）
- 工具执行异常捕获，返回结构化错误信息给 LLM（而非 traceback）
- 工具输出截断（超过阈值时截断并标注 "[output truncated, N chars total]"）

**6. 进度日志**
- 每步在 stderr 打印：步数、执行的工具名、耗时、当前消息历史长度
- 方便调试和监控 agent 运行状态

### 领域特定扩展（必须实现）

**7. 编辑-测试-修复循环**
- 修改代码后自动运行测试命令验证
- 解析 pytest/unittest 输出，提取失败的测试名称和错误信息，结构化反馈给 LLM
- 支持多次 edit→test→fix 迭代，直到测试通过或达到重试上限

**8. 增量编辑**
- 支持基于字符串匹配的局部替换（old_string → new_string），而非每次重写整个文件
- 编辑前校验 old_string 在文件中存在且唯一

**9. 分层代码导航**
- glob/find 扫描文件树获得项目结构
- grep 搜索符号和关键词定位目标
- 定向行范围读取（读取文件的指定行范围，而非整个文件），避免上下文溢出

**10. 命令预检**
- bash 命令执行前做语法预检（`bash -n`），语法错误不执行直接反馈
- 命令执行设置超时（默认 60s），防止无限挂起

---

## 调用示例

### Case 1：修复失败的测试

```bash
python -m harness -p "test_app.py 中的 test_get_by_id 和 test_list_incomplete_only 失败了，修复 app.py 中的 bug" --output-dir ./output/
```

**预期行为：**
1. `run_command("pytest test_app.py -v")` → 看到 2 个测试失败
2. `read_file("app.py")` → 阅读源码
3. 分析错误：`get()` 方法比较 `todo.title == todo_id` 应为 `todo.id == todo_id`
4. `write_file("app.py", 修复后的内容)` → 修复 bug
5. `run_command("pytest test_app.py -v")` → 可能还有失败
6. 分析 `list_todos` 的过滤逻辑反转 → 再次修复
7. `run_command("pytest test_app.py -v")` → 全部通过
8. `finish(status="success")`

### Case 2：添加新功能

```bash
python -m harness -p "在 utils.py 中添加一个 calculate_statistics(numbers) 函数，返回 {mean, median, std_dev}，并在 test_utils.py 中添加测试" --output-dir ./output/
```

**预期行为：**
1. `list_files(pattern="**/*.py")` → 了解项目结构
2. `read_file("utils.py")` → 阅读已有代码
3. `write_file("utils.py", 添加了新函数的内容)`
4. `write_file("test_utils.py", 包含测试的内容)`
5. `run_command("pytest test_utils.py -v")` → 验证通过
6. `finish(status="success")`

---

## 技术要求

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，通过环境变量配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 禁止使用：LangChain / LlamaIndex / AutoGen / anthropic SDK
- 必须提供 `Dockerfile`（基于 `python:3.11-slim`）和 `requirements.txt`
- Dockerfile 中 LLM 配置通过环境变量注入，不硬编码

---

## 最低要求清单

你的 harness **必须**满足以下所有条件：

1. ✅ `python -m harness -p "..." --output-dir ./output/` 可运行
2. ✅ 使用 `openai` SDK 调用 LLM（至少每个任务调用 1 次）
3. ✅ 使用 function calling / tool calling 模式驱动工具执行
4. ✅ 至少实现 4 个工具：read_file, write_file, run_command, finish
5. ✅ 产出 `result.json`（含 status 和 trajectory 字段）
6. ✅ 产出 `trajectory.jsonl`（每步记录 action 和 observation）
7. ✅ 提供 `Dockerfile` 和 `requirements.txt`
8. ✅ LLM API 调用有指数退避重试（至少 3 次）
9. ✅ 消息历史超长时自动压缩（截断旧工具输出或移除旧轮次）
10. ✅ 检测连续相同动作并注入策略切换提示
11. ✅ 达到步数上限时保存部分结果，异常时仍输出 result.json
