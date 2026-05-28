# 构建数据分析智能体 Harness

构建一个 Python 数据分析智能体：接收自然语言分析需求，通过 LLM 驱动的循环自主完成数据加载、统计分析、可视化和报告生成。

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
  __main__.py        # 入口：从主模块导入 main 并执行
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
"""Data Analysis Agent Harness - 自主数据分析智能体"""
import argparse
import json
import os
import sys
import time
import traceback
from io import StringIO
from pathlib import Path
from openai import OpenAI

# ── 配置 ─────────────────────────────────────────────
client = OpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.environ.get("OPENAI_API_KEY", "sk-placeholder"),
)
MODEL = os.environ.get("MODEL_NAME", "gpt-4")

SYSTEM_PROMPT = """You are a data analysis agent. You can execute Python code, read/write files, and create charts.
You have a persistent Python namespace — variables defined in one execute_python call are available in later calls.
Given an analysis task, load data, explore it, perform statistical analysis, generate visualizations, and summarize findings.
When you are done, call the 'finish' tool with the final status."""

# ── 持久化 Python 命名空间 ────────────────────────────
# 所有 execute_python 调用共享此命名空间，变量在步骤间保持
_namespace = {}

# ── 工具定义（OpenAI function calling 格式）────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code in a persistent namespace. Variables persist across calls. Use print() to see output. Libraries like pandas, numpy, matplotlib, scipy are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a data file (CSV, JSON, text, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "max_lines": {"type": "integer", "description": "Max lines to return (default 100)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (analysis results, reports, CSV output)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chart",
            "description": "Execute Python code that uses matplotlib to create and save a chart. The code must call plt.savefig() with the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python matplotlib code. Must include plt.savefig()."},
                    "save_path": {"type": "string", "description": "File path for the chart image (e.g. output/chart.png)"},
                },
                "required": ["code", "save_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the analysis task is complete",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["success", "partial", "failed"]},
                    "summary": {"type": "string", "description": "Brief summary of analysis results"},
                },
                "required": ["status"],
            },
        },
    },
]


# ── 工具执行 ──────────────────────────────────────────
def execute_tool(name: str, args: dict, output_dir: str) -> str:
    """执行工具调用，返回结果字符串。"""
    try:
        if name == "execute_python":
            code = args["code"]
            old_stdout = sys.stdout
            sys.stdout = captured = StringIO()
            try:
                exec(code, _namespace)
            except Exception:
                captured.write(traceback.format_exc())
            finally:
                sys.stdout = old_stdout
            output = captured.getvalue()
            return output[:8000] if output else "(no output)"

        elif name == "read_file":
            path = args["path"]
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            max_lines = args.get("max_lines", 100)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
            return "".join(lines)[:10000]

        elif name == "write_file":
            path = args["path"]
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return f"File written: {path} ({len(args['content'])} chars)"

        elif name == "create_chart":
            code = args["code"]
            save_path = args["save_path"]
            os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)
            # 注入 save_path 和必要的 import 到命名空间
            _namespace["__chart_save_path__"] = save_path
            old_stdout = sys.stdout
            sys.stdout = captured = StringIO()
            try:
                exec(code, _namespace)
            except Exception:
                captured.write(traceback.format_exc())
            finally:
                sys.stdout = old_stdout
            output = captured.getvalue()
            if os.path.exists(save_path):
                return f"Chart saved: {save_path}" + (f"\n{output}" if output else "")
            return f"Warning: chart file not created at {save_path}\n{output}"

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

    # 预导入常用库到命名空间
    _namespace.clear()
    try:
        exec("import pandas as pd\nimport numpy as np\nimport matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt", _namespace)
    except ImportError:
        pass

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
            entry = {"step": step, "error": str(e), "timestamp": time.time()}
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(2)
            continue

        choice = response.choices[0]
        assistant_msg = choice.message

        # 将 assistant 回复加入对话
        messages.append(assistant_msg.model_dump())

        # 如果没有 tool calls，继续循环
        if not assistant_msg.tool_calls:
            entry = {
                "step": step,
                "action": "text_response",
                "content": assistant_msg.content or "",
                "timestamp": time.time(),
            }
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            continue

        # 执行所有 tool calls
        for tool_call in assistant_msg.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            result = execute_tool(func_name, func_args, output_dir)

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
    parser = argparse.ArgumentParser(description="Data Analysis Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Analysis task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps")
    args = parser.parse_args()

    print(f"Running data analysis agent: {args.prompt[:100]}...")
    status = run_agent(args.prompt, args.output_dir, args.max_steps)
    print(f"Done. Status: {status}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
```

---

## 核心能力要求

基于上面的骨架，你需要确保 harness 具备以下能力：

- **数据加载**：自动发现并加载工作目录中的 CSV/Excel/JSON/Parquet 文件
- **统计分析**：描述性统计、分组聚合、相关性分析、假设检验
- **可视化生成**：使用 matplotlib 生成折线图、柱状图、散点图、热力图等，保存为图片
- **持久化命名空间**：`execute_python` 中定义的变量在后续调用中仍然可用
- **报告生成**：将分析结论写入 Markdown 或文本文件
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

**7. 有状态执行环境**
- 维护共享 Python 命名空间，所有变量、DataFrame 在步骤间持久化
- 后续代码可直接引用前序步骤的变量，无需重复加载

**8. 执行沙箱**
- `execute_python` 设置超时（默认 30 秒）和异常捕获
- 执行前做语法检查（`compile()`），语法错误不执行直接反馈
- 捕获执行中的 warning（如 SettingWithCopyWarning）并反馈

**9. 自动数据发现与预处理**
- 自动发现工作目录中的数据文件（CSV/Excel/JSON/Parquet）
- 加载后自动返回 shape、dtypes、head(5)、缺失值统计的摘要
- 处理编码问题（UTF-8/GBK 自动检测）

**10. 产物注册与追踪**
- 维护产物表：记录生成的 DataFrame（名称、shape、列摘要）、图表（路径、类型）、文件
- 以压缩摘要形式注入上下文，让 LLM 知道已有哪些中间结果
- 避免重复加载或重复计算

---

## 调用示例

### Case 1：部门薪资分析

```bash
python -m harness -p "分析 employees.csv 中各部门的薪资分布，计算均值、中位数、标准差，找出薪资最高和最低的部门，生成对比柱状图" --output-dir ./output/
```

数据：`employees.csv`（列：`employee_id, name, department, salary, hire_date, position`）

**预期行为：**
1. `execute_python("df = pd.read_csv('employees.csv'); print(df.shape); print(df.head())")` → 了解数据结构
2. `execute_python("stats = df.groupby('department')['salary'].agg(['mean','median','std','count']); print(stats.round(2))")` → 计算各部门统计量
3. `execute_python("top = stats['mean'].idxmax(); bottom = stats['mean'].idxmin(); print(f'最高: {top}, 最低: {bottom}')")` → 找出极值部门
4. `create_chart(code="fig, ax = plt.subplots(figsize=(10,6)); stats['mean'].sort_values().plot(kind='barh', ax=ax); ax.set_xlabel('平均薪资'); ax.set_title('各部门平均薪资对比'); plt.tight_layout(); plt.savefig('output/salary_comparison.png')", save_path="output/salary_comparison.png")` → 生成柱状图
5. `write_file(path="output/report.md", content="# 薪资分析报告\n...")` → 写入报告
6. `finish(status="success", summary="完成各部门薪资分布分析，生成对比图表和报告")`

### Case 2：多文件合并与相关性分析

```bash
python -m harness -p "合并 students.csv 和 scores.csv，分析学习时长与考试成绩的相关性，按学科分组计算皮尔逊相关系数，绘制散点图" --output-dir ./output/
```

数据：`students.csv`（列：`student_id, name, grade, study_hours_per_week`）+ `scores.csv`（列：`student_id, subject, score, exam_date`）

**预期行为：**
1. `execute_python("students = pd.read_csv('students.csv'); scores = pd.read_csv('scores.csv'); print(students.shape, scores.shape)")` → 加载两个文件
2. `execute_python("merged = scores.merge(students, on='student_id'); print(merged.head()); print(merged['subject'].unique())")` → 合并数据
3. `execute_python("from scipy import stats as sp_stats\nfor subj in merged['subject'].unique():\n    sub = merged[merged['subject']==subj]\n    r, p = sp_stats.pearsonr(sub['study_hours_per_week'], sub['score'])\n    print(f'{subj}: r={r:.3f}, p={p:.4f}')")` → 分组计算相关系数
4. `create_chart(code="subjects = merged['subject'].unique()\nfig, axes = plt.subplots(1, len(subjects), figsize=(5*len(subjects), 5))\nfor i, subj in enumerate(subjects):\n    sub = merged[merged['subject']==subj]\n    axes[i].scatter(sub['study_hours_per_week'], sub['score'], alpha=0.5)\n    axes[i].set_title(subj)\n    axes[i].set_xlabel('学习时长')\n    axes[i].set_ylabel('成绩')\nplt.tight_layout()\nplt.savefig('output/correlation_scatter.png')", save_path="output/correlation_scatter.png")` → 绘制散点图
5. `finish(status="success")`

---

## 技术要求

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，通过环境变量配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用库：pandas、matplotlib、numpy、scipy、seaborn、scikit-learn
- 禁止使用：LangChain / LlamaIndex / AutoGen / anthropic SDK
- 必须提供 `Dockerfile`（基于 `python:3.11-slim`）和 `requirements.txt`
- Dockerfile 中 LLM 配置通过环境变量注入，不硬编码

---

## 最低要求清单

你的 harness **必须**满足以下所有条件：

1. `python -m harness -p "..." --output-dir ./output/` 可运行
2. 使用 `openai` SDK 调用 LLM（至少每个任务调用 1 次）
3. 使用 function calling / tool calling 模式驱动工具执行
4. 至少实现 5 个工具：execute_python, read_file, write_file, create_chart, finish
5. `execute_python` 使用共享命名空间（`exec(code, namespace)`），变量跨步骤持久化
6. 产出 `result.json`（含 status 和 trajectory 字段）
7. 产出 `trajectory.jsonl`（每步记录 action 和 observation）
8. 提供 `Dockerfile` 和 `requirements.txt`
9. LLM API 调用有指数退避重试（至少 3 次）
10. 消息历史超长时自动压缩（截断旧工具输出或移除旧轮次）
11. 检测连续相同动作并注入策略切换提示
12. 达到步数上限时保存部分结果，异常时仍输出 result.json
