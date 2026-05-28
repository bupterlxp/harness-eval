# Agent Harness 构建任务：创意写作智能体（Creative Writing Agent）

构建一个创意写作 harness，接收写作任务描述（体裁、风格、字数等），通过 LLM 驱动的 agent 循环自主完成规划、起草、评估、修订的全流程创作。

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
"""Creative Writing Agent Harness - 自主创意写作智能体"""
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

SYSTEM_PROMPT = """You are a creative writing agent. You plan outlines, write sections, evaluate drafts, revise based on feedback, and produce polished final text.
Workflow: plan_outline -> write_section (repeat for each section) -> evaluate_draft -> revise_section (if needed) -> write_file (save final) -> finish.
Always follow this workflow. Write high-quality, engaging content that matches the requested style and constraints."""

# ── 全局草稿缓冲区 ──────────────────────────────────
draft_buffer: list[str] = []  # 按 section 顺序存储各段文本

# ── 工具定义（OpenAI function calling 格式）────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "plan_outline",
            "description": "Create a structured outline for the writing task. Returns the outline text for reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Working title"},
                    "outline": {"type": "string", "description": "Full outline with sections, key points, and structure"},
                },
                "required": ["title", "outline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_section",
            "description": "Write a section of the draft. The text is appended to the draft buffer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_name": {"type": "string", "description": "Name of this section (e.g. 'Introduction', 'Chapter 1')"},
                    "content": {"type": "string", "description": "The full text content of this section"},
                },
                "required": ["section_name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_draft",
            "description": "Critique the current draft. Provide scores and specific feedback for revision.",
            "parameters": {
                "type": "object",
                "properties": {
                    "criteria": {"type": "string", "description": "Evaluation criteria (e.g. 'coherence, style, engagement, structure')"},
                    "feedback": {"type": "string", "description": "Detailed critique with specific issues and suggestions"},
                    "score": {"type": "number", "description": "Overall quality score 1-10"},
                },
                "required": ["criteria", "feedback", "score"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_section",
            "description": "Revise a specific section based on evaluation feedback. Replaces that section in the draft buffer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_index": {"type": "integer", "description": "Index of the section to revise (0-based)"},
                    "revised_content": {"type": "string", "description": "The revised text for this section"},
                    "changes_made": {"type": "string", "description": "Summary of what was changed and why"},
                },
                "required": ["section_index", "revised_content", "changes_made"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Save content to a file in the output directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Output filename (e.g. 'story.md', 'essay.txt')"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal that the writing task is complete",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["success", "partial", "failed"]},
                    "summary": {"type": "string", "description": "Brief summary of the completed work"},
                },
                "required": ["status"],
            },
        },
    },
]


# ── 工具执行 ──────────────────────────────────────────
def execute_tool(name: str, args: dict, output_dir: str) -> str:
    """执行工具调用，返回结果字符串。"""
    global draft_buffer
    try:
        if name == "plan_outline":
            title = args.get("title", "Untitled")
            outline = args.get("outline", "")
            return f"Outline created: '{title}'\n{outline}"

        elif name == "write_section":
            section_name = args.get("section_name", "Section")
            content = args.get("content", "")
            draft_buffer.append(content)
            idx = len(draft_buffer) - 1
            word_count = len(content.split())
            total_words = sum(len(s.split()) for s in draft_buffer)
            return f"Section '{section_name}' written (index={idx}, {word_count} words). Total draft: {len(draft_buffer)} sections, {total_words} words."

        elif name == "evaluate_draft":
            full_draft = "\n\n".join(draft_buffer)
            word_count = len(full_draft.split())
            score = args.get("score", 0)
            feedback = args.get("feedback", "")
            return f"Draft evaluated ({word_count} words, {len(draft_buffer)} sections). Score: {score}/10.\nFeedback: {feedback}"

        elif name == "revise_section":
            idx = args.get("section_index", 0)
            revised = args.get("revised_content", "")
            changes = args.get("changes_made", "")
            if 0 <= idx < len(draft_buffer):
                old_words = len(draft_buffer[idx].split())
                draft_buffer[idx] = revised
                new_words = len(revised.split())
                return f"Section {idx} revised ({old_words} -> {new_words} words). Changes: {changes}"
            else:
                return f"Error: section index {idx} out of range (0-{len(draft_buffer)-1})"

        elif name == "write_file":
            filename = args.get("filename", "output.md")
            content = args.get("content", "")
            filepath = os.path.join(output_dir, filename)
            os.makedirs(output_dir, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return f"File written: {filepath} ({len(content)} chars, {len(content.split())} words)"

        elif name == "finish":
            return f"FINISH: {args.get('status', 'success')}"

        else:
            return f"Error: Unknown tool '{name}'"

    except Exception as e:
        return f"Error executing {name}: {str(e)}"


# ── Agent 主循环 ──────────────────────────────────────
def run_agent(task: str, output_dir: str, max_steps: int = 30):
    """运行 agent 主循环。"""
    global draft_buffer
    draft_buffer = []
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

            # 执行工具
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
    parser = argparse.ArgumentParser(description="Creative Writing Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Writing task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps")
    args = parser.parse_args()

    print(f"Running writing agent: {args.prompt[:100]}...")
    status = run_agent(args.prompt, args.output_dir, args.max_steps)
    print(f"Done. Status: {status}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
```

---

## 核心能力要求

基于上面的骨架，你需要确保 harness 具备以下能力：

- **规划能力**：根据写作任务自动生成结构化大纲（章节、要点、逻辑线）
- **分段写作**：按大纲逐段生成内容，每段积累到草稿缓冲区
- **自我评估**：完成初稿后对整体质量打分，给出具体修改建议
- **定向修订**：根据评估反馈修改特定段落，而非重写全文
- **风格控制**：遵循任务中指定的体裁、语调、字数等约束
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

**7. 多层级规划**
- 接收写作任务后先生成结构化大纲（outline），再按节/段生成内容
- 大纲包含每节的要点、预估字数、风格指引
- 后续写作步骤按大纲顺序推进

**8. 批评-修订循环**
- evaluate_draft 后如果质量不达标（按 LLM 自评分），自动触发 revise
- 支持多维度评审：结构、逻辑、语言、风格、是否满足约束
- 修订后再次评估，循环直到达标或达到最大迭代次数（如 3 次）
- 修订版有长度保护：修改后字数不应低于原文 80%

**9. 字数追踪与控制**
- 每次 write_section 后自动统计当前总字数
- 将字数信息反馈给 LLM（如 "当前已写 650 字 / 目标 800 字"）
- 接近目标字数时提醒 LLM 准备收尾

**10. 风格一致性控制**
- SYSTEM_PROMPT 中定义目标风格参数（叙事视角、语调、词汇偏好）
- evaluate_draft 时检查风格一致性（是否符合指定的人称、语调等约束）
- 标记风格偏离并在修订指令中具体指出

---

## 调用示例

### Case 1：短篇故事创作

```bash
python -m harness -p "写一篇500字的科幻短篇故事。要求：以火星殖民地为背景，主角是一名植物学家，发现了一种能在火星土壤中存活的地球植物变异体。包含悬念和情感转折。语调：冷静克制但有温度。" --output-dir ./output/
```

**预期行为：**
1. `plan_outline(title="火星花园", outline="引入：植物学家日常...转折：发现变异体...高潮：变异体的真正含义...结尾：希望与代价")` → 建立故事结构
2. `write_section("开篇", "第37个火星日，陈岚...")` → 写开篇段落
3. `write_section("发展", "变异体的根系...")` → 写发展段落
4. `write_section("高潮与结尾", "当她把样本...")` → 写结尾段落
5. `evaluate_draft(criteria="叙事节奏、情感深度、科幻细节、字数控制", feedback="...", score=7)` → 评估初稿
6. `revise_section(section_index=1, revised_content="...", changes_made="加强悬念感")` → 修订薄弱段落
7. `write_file("story.md", 完整终稿)` → 保存最终版本
8. `finish(status="success")`

### Case 2：结构化议论文

```bash
python -m harness -p "写一篇800字的议论文，主题：'远程办公是否应成为知识工作者的默认模式'。要求：包含引言、正方论点（2个）、反方论点（1个）、反驳、结论。引用具体数据或案例支撑论点。语调：理性客观。" --output-dir ./output/
```

**预期行为：**
1. `plan_outline(title="远程办公的未来", outline="引言：后疫情时代的工作方式变革...正方1：生产力数据...正方2：人才获取...反方：协作与文化挑战...反驳...结论")` → 建立论证结构
2. `write_section("引言", "2020年以来...")` → 写引言
3. `write_section("正方论点", "斯坦福大学研究显示...")` → 写正方论据
4. `write_section("反方与反驳", "然而批评者指出...")` → 写反方和反驳
5. `write_section("结论", "综合以上分析...")` → 写结论
6. `evaluate_draft(criteria="论证逻辑、证据质量、结构完整性、字数", feedback="...", score=8)` → 评估
7. `write_file("essay.md", 完整终稿)` → 保存
8. `finish(status="success")`

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
4. ✅ 至少实现 4 个工具：plan_outline, write_section, evaluate_draft, finish
5. ✅ 产出 `result.json`（含 status 和 trajectory 字段）
6. ✅ 产出 `trajectory.jsonl`（每步记录 action 和 observation）
7. ✅ 提供 `Dockerfile` 和 `requirements.txt`
8. ✅ LLM API 调用有指数退避重试（至少 3 次）
9. ✅ 消息历史超长时自动压缩（截断旧工具输出或移除旧轮次）
10. ✅ 检测连续相同动作并注入策略切换提示
11. ✅ 达到步数上限时保存部分结果，异常时仍输出 result.json
