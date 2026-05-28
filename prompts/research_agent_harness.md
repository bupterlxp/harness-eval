# 构建研究智能体 Harness

构建一个研究智能体：接收自然语言研究问题，通过 LLM 驱动的多轮检索-分析循环，自主搜索信息、评估来源、生成结构化研究报告。

---

## 接口

```bash
python -m harness -p "研究问题" --output-dir ./output/
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

**重要：harness 运行在无互联网的 Docker 容器中，无法访问真实搜索引擎。`search_web` 工具通过调用 LLM 本身来提供信息——LLM 充当知识源，根据查询返回相关事实和数据。**

```python
#!/usr/bin/env python3
"""Research Agent Harness - 自主研究智能体"""
import argparse
import json
import os
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

SYSTEM_PROMPT = """You are a research agent. You investigate questions by searching for information, analyzing sources, and writing structured reports.

Workflow:
1. Decompose the research question into sub-questions
2. Use search_web to gather information on each sub-question (multiple rounds if needed)
3. Use analyze_sources to synthesize findings and identify knowledge gaps
4. Use write_report to compose the final structured report section by section
5. Call finish when the research is complete

Always cite your sources. Track what you have learned and what gaps remain after each search round."""

# ── 工具定义（OpenAI function calling 格式）────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search for information on a topic. Returns relevant facts, data, and source descriptions. Use specific queries for best results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {"type": "integer", "description": "Number of results to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sources",
            "description": "Synthesize and analyze collected findings. Identifies patterns, contradictions, and knowledge gaps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {"type": "string", "description": "Collected findings to analyze"},
                    "question": {"type": "string", "description": "The research question being addressed"},
                },
                "required": ["findings", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": "Write a section of the research report to a file. Appends to the file if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path for the report (e.g. report.md)"},
                    "section_title": {"type": "string", "description": "Title of this report section"},
                    "content": {"type": "string", "description": "Section content in markdown"},
                },
                "required": ["path", "section_title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
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
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the research is complete",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["success", "partial", "failed"]},
                    "summary": {"type": "string", "description": "Brief summary of research findings"},
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
        if name == "search_web":
            # 无互联网环境：用 LLM 自身作为知识源
            query = args["query"]
            num_results = args.get("num_results", 5)
            search_prompt = (
                f"You are a search engine. For the query below, provide {num_results} "
                f"relevant and factual results. Each result should have a title, a brief "
                f"description of the source, and key facts/data. Be specific and cite "
                f"plausible sources (academic papers, official reports, news articles).\n\n"
                f"Query: {query}"
            )
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": search_prompt}],
            )
            return resp.choices[0].message.content or "No results found."

        elif name == "analyze_sources":
            findings = args["findings"]
            question = args["question"]
            analysis_prompt = (
                f"Analyze the following research findings for the question: {question}\n\n"
                f"Findings:\n{findings}\n\n"
                f"Provide:\n1. Key themes and patterns\n2. Contradictions between sources\n"
                f"3. Knowledge gaps that need further research\n4. Confidence assessment"
            )
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": analysis_prompt}],
            )
            return resp.choices[0].message.content or "Analysis failed."

        elif name == "write_report":
            path = args["path"]
            title = args["section_title"]
            content = args["content"]
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            mode = "a" if os.path.exists(path) else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(f"\n## {title}\n\n{content}\n")
            return f"Section '{title}' written to {path}"

        elif name == "read_file":
            path = args["path"]
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            return text[:10000]

        elif name == "write_file":
            path = args["path"]
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return f"File written: {path} ({len(args['content'])} chars)"

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
            entry = {"step": step, "error": str(e), "timestamp": time.time()}
            trajectory_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            time.sleep(2)
            continue

        choice = response.choices[0]
        assistant_msg = choice.message

        # 将 assistant 回复加入对话
        messages.append(assistant_msg.model_dump())

        # 如果没有 tool calls，记录并继续
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
    parser = argparse.ArgumentParser(description="Research Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Research question")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps")
    args = parser.parse_args()

    print(f"Running research agent: {args.prompt[:100]}...")
    status = run_agent(args.prompt, args.output_dir, args.max_steps)
    print(f"Done. Status: {status}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
```

---

## 核心能力要求

基于上面的骨架，你需要确保 harness 具备以下能力：

- **问题分解**：将复杂研究问题拆解为可独立检索的子问题
- **迭代检索**：多轮搜索，每轮根据前序结果的知识缺口生成新查询
- **来源追踪**：记录每条信息的来源，维护来源列表
- **报告生成**：将研究结果组织为结构化 markdown 报告（引言、分节、结论）
- **引用管理**：报告中的事实性主张附带编号引用 `[N]`，尾部列出参考来源
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

**7. 多跳迭代检索**
- 搜索不是一次性的：第一轮广度搜索获得初步发现，分析知识缺口后生成后续精炼查询
- 支持至少 2-3 轮迭代检索，每轮聚焦上一轮发现的缺口
- 维护 visited_urls / visited_queries 集合避免重复搜索

**8. 证据管理与引用系统**
- 每条检索结果生成结构化证据卡片（来源 URL、标题、关键内容摘要、质量评分）
- 报告中每个事实性主张映射到编号引用 `[N]`
- 尾部参考文献列表提供完整源信息
- 强制引用一致性：无孤立引用，无虚假引用

**9. 矛盾检测与多元视角**
- 当不同来源对同一事实给出矛盾信息时，保留双方主张并标注各自来源
- 不静默丢弃少数观点
- 在报告中显式呈现分歧（如 "来源 [3] 认为 X，而来源 [7] 认为 Y"）

**10. 输出模式自适应**
- 开放探索性问题 → 生成结构化报告（分节、有引用、有结论）
- 封闭事实性问题 → 精确答案 + 支撑证据（而非冗长报告）
- 根据问题类型自动判断输出模式

---

## 调用示例

### Case 1：技术对比评估

```bash
python -m harness -p "对比 React、Vue、Svelte 三个前端框架在性能（首屏加载、运行时性能）、生态系统成熟度、学习曲线方面的优劣，给出选型建议" --output-dir ./output/
```

**预期行为：**
1. 分解为 3 个子查询：各框架性能基准、生态系统对比、学习曲线评估
2. `search_web("React Vue Svelte performance benchmark 2024")` -> 获取性能数据
3. `search_web("React ecosystem npm packages community size")` -> 生态系统数据
4. `search_web("Svelte learning curve developer experience")` -> 学习曲线信息
5. `analyze_sources(findings=..., question=...)` -> 综合分析，发现性能数据的口径差异
6. `search_web("Svelte vs React bundle size real world comparison")` -> 补充搜索填补缺口
7. `write_report("report.md", "Introduction", ...)` -> 逐节撰写报告
8. `write_report("report.md", "Performance Comparison", ...)` -> 性能对比（含数据表格）
9. `write_report("report.md", "Conclusion", ...)` -> 结论与选型建议
10. `finish(status="success")`

### Case 2：复杂事实性问题

```bash
python -m harness -p "哪些因素导致了 2008 年全球金融危机？次贷危机、信用评级机构、金融衍生品各自扮演了什么角色？" --output-dir ./output/
```

**预期行为：**
1. 分解：次贷市场机制、信用评级失灵原因、CDO/CDS 衍生品传导链、监管缺失背景
2. `search_web("2008 financial crisis subprime mortgage causes")` -> 次贷背景
3. `search_web("credit rating agencies role 2008 crisis Moody's S&P")` -> 评级机构问题
4. `search_web("CDO CDS financial derivatives 2008 systemic risk")` -> 衍生品传导机制
5. `analyze_sources(...)` -> 发现关于"谁该负主要责任"的分歧
6. `search_web("2008 crisis regulatory failure Glass-Steagall repeal")` -> 追踪监管因素
7. `write_report(...)` -> 撰写报告：按因果链组织（次贷发放 -> 证券化 -> 评级失真 -> 衍生品放大 -> 系统性崩溃）
8. `write_file("sources.json", ...)` -> 保存来源列表
9. `finish(status="success")`

---

## 技术要求

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，通过环境变量配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 网络请求：可使用 `httpx`，但非必需（`search_web` 通过 LLM 实现，不需要真实网络）
- 禁止使用：LangChain / LlamaIndex / AutoGen / anthropic SDK
- 必须提供 `Dockerfile`（基于 `python:3.11-slim`）和 `requirements.txt`
- Dockerfile 中 LLM 配置通过环境变量注入，不硬编码

---

## 最低要求清单

你的 harness **必须**满足以下所有条件：

1. `python -m harness -p "..." --output-dir ./output/` 可运行
2. 使用 `openai` SDK 调用 LLM（至少每个任务调用 1 次）
3. 使用 function calling / tool calling 模式驱动工具执行
4. 至少实现 5 个工具：search_web, analyze_sources, write_report, read_file, finish
5. `search_web` 通过调用 LLM 获取信息（非真实网络请求）
6. 产出 `result.json`（含 status 和 trajectory 字段）
7. 产出 `trajectory.jsonl`（每步记录 action 和 observation）
8. 生成 markdown 格式的研究报告文件
9. 提供 `Dockerfile` 和 `requirements.txt`
10. LLM API 调用有指数退避重试（至少 3 次）
11. 消息历史超长时自动压缩（截断旧工具输出或移除旧轮次）
12. 检测连续相同动作并注入策略切换提示
13. 达到步数上限时保存部分结果，异常时仍输出 result.json
