# 构建浏览器自动化智能体 Harness

构建一个浏览器自动化智能体：接收 Web 任务描述，通过 LLM 驱动的感知-决策-执行循环，使用 Playwright 自主完成网页导航、交互和数据提取。

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

以下是**完整可运行的骨架代码**。你必须基于它构建 harness，保留核心结构（页面状态获取 + LLM 决策 + Playwright 执行循环），按需扩展工具实现和错误处理。

**⚠️ 关键约束：骨架中的以下全局变量必须保留，禁止删除、重命名或移到函数内部：**
- `client = OpenAI(...)` — LLM 客户端实例
- `MODEL = os.environ.get("MODEL_NAME", "gpt-4")` — 模型名称
- `SYSTEM_PROMPT = """..."""` — 系统提示词
- `TOOLS = [...]` — 工具定义列表
你可以修改它们的内容，但变量名和初始化位置必须保持在模块顶层。

```python
#!/usr/bin/env python3
"""Browser Agent Harness - 浏览器自动化智能体"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from openai import OpenAI
from playwright.sync_api import sync_playwright

# ── 配置 ─────────────────────────────────────────────
client = OpenAI(
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    api_key=os.environ.get("OPENAI_API_KEY", "sk-placeholder"),
)
MODEL = os.environ.get("MODEL_NAME", "gpt-4")

SYSTEM_PROMPT = """You are a browser automation agent. You can navigate web pages, click elements, fill forms, and extract data.
Each step you receive the current page state (title, URL, simplified content). Decide your next action by calling a tool.
When the task is complete, call 'finish' with the result."""

# ── 工具定义（OpenAI function calling 格式）────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate to a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an element on the page by CSS selector",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to click"},
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Fill a form input with text",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element"},
                    "value": {"type": "string", "description": "Text value to fill in"},
                },
                "required": ["selector", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_text",
            "description": "Extract text content from an element, or the entire page if no selector given",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector (optional, defaults to body)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": "Get a simplified representation of the current page (title, text, links, form inputs) that fits in LLM context",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Take a screenshot of the current page",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename for the screenshot (default: screenshot.png)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
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
                    "summary": {"type": "string", "description": "Brief summary of the result"},
                },
                "required": ["status"],
            },
        },
    },
]


# ── 页面状态获取 ────────────────────────────────────────
def get_page_state(page) -> str:
    """获取当前页面的简化表示，包含标题、文本、链接和表单输入。"""
    try:
        title = page.title()
        url = page.url

        # 提取页面文本内容（截断）
        text_content = page.evaluate("() => document.body?.innerText || ''")
        text_content = text_content[:3000]

        # 提取所有链接
        links = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).slice(0, 50).map(a => ({
                text: (a.innerText || '').trim().substring(0, 80),
                href: a.href
            })).filter(l => l.text.length > 0);
        }""")

        # 提取所有表单输入
        inputs = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input, textarea, select, button')).slice(0, 30).map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.type || '',
                name: el.name || '',
                id: el.id || '',
                placeholder: el.placeholder || '',
                value: el.value || '',
                text: (el.innerText || '').trim().substring(0, 50),
                selector: el.id ? '#' + el.id : (el.name ? el.tagName.toLowerCase() + '[name=\"' + el.name + '\"]' : '')
            }));
        }""")

        state = f"=== Page State ===\nTitle: {title}\nURL: {url}\n\n"
        state += f"--- Text Content (truncated) ---\n{text_content}\n\n"

        if links:
            state += "--- Links ---\n"
            for link in links[:30]:
                state += f"  [{link['text']}] -> {link['href']}\n"
            state += "\n"

        if inputs:
            state += "--- Form Elements ---\n"
            for inp in inputs:
                selector_hint = inp['selector'] or f"{inp['tag']}.{inp['type']}"
                state += f"  <{inp['tag']} type='{inp['type']}' name='{inp['name']}' id='{inp['id']}' placeholder='{inp['placeholder']}'> selector: {selector_hint}\n"

        return state[:6000]
    except Exception as e:
        return f"Error getting page state: {e}"


# ── 工具执行 ──────────────────────────────────────────
def execute_tool(name: str, args: dict, page, output_dir: str) -> str:
    """执行工具调用，返回结果字符串。"""
    try:
        if name == "navigate":
            page.goto(args["url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            return f"Navigated to {page.url}\n\n{get_page_state(page)}"

        elif name == "click":
            selector = args["selector"]
            page.click(selector, timeout=5000)
            page.wait_for_timeout(1000)
            return f"Clicked: {selector}\n\n{get_page_state(page)}"

        elif name == "fill":
            selector = args["selector"]
            value = args["value"]
            page.fill(selector, value, timeout=5000)
            return f"Filled '{selector}' with '{value}'"

        elif name == "extract_text":
            selector = args.get("selector", "body")
            text = page.text_content(selector, timeout=5000) or ""
            return text[:5000]

        elif name == "get_page_content":
            return get_page_state(page)

        elif name == "screenshot":
            filename = args.get("filename", "screenshot.png")
            filepath = os.path.join(output_dir, filename)
            page.screenshot(path=filepath, full_page=False)
            return f"Screenshot saved: {filepath}"

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

    final_status = "failed"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        # 初始页面状态
        initial_state = f"Browser ready. Awaiting your first action.\nTask: {task}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": initial_state},
        ]

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
                result = execute_tool(func_name, func_args, page, output_dir)

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
                    browser.close()
                    with open(result_path, "w") as f:
                        json.dump({"status": final_status, "trajectory": trajectory_path}, f, indent=2)
                    return final_status

        # 达到步数上限
        trajectory_file.close()
        browser.close()

    with open(result_path, "w") as f:
        json.dump({"status": final_status, "trajectory": trajectory_path}, f, indent=2)
    return final_status


# ── CLI 入口 ──────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Browser Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps")
    args = parser.parse_args()

    print(f"Running browser agent: {args.prompt[:100]}...")
    status = run_agent(args.prompt, args.output_dir, args.max_steps)
    print(f"Done. Status: {status}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
```

---

## 核心能力要求

基于上面的骨架，你需要确保 harness 具备以下能力：

- **页面导航**：打开 URL、等待加载完成、处理重定向
- **表单填写**：定位输入框、选择器、复选框，填写并提交表单
- **数据提取**：获取页面文本、表格数据、链接列表，返回结构化结果
- **多页面工作流**：跨页面操作（登录 -> 导航 -> 操作 -> 提取结果）
- **截图捕获**：在关键步骤保存页面截图用于审计
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

**7. 智能等待策略**
- 操作后等待页面稳定（网络空闲 / 特定元素出现 / DOM 变化停止），而非固定 sleep
- 支持可配置的等待超时
- 等待超时后返回当前页面状态（而非 crash）

**8. 页面停滞检测**
- 连续 N 步页面内容指纹无变化时警告 LLM
- 与重复动作检测配合：重复操作 + 页面无变化 = 强制换策略

**9. 失败截图与诊断**
- 工具执行失败时自动截图保存（用于事后调试）
- 截图文件名包含步数和错误类型（如 `step_5_click_failed.png`）

**10. 选择器容错**
- CSS 选择器定位失败时尝试备选策略：
  - 通过文本内容匹配（`text=...`）
  - 通过可访问性属性（`role=...`, `aria-label=...`）
  - 获取页面当前所有可交互元素列表供 LLM 重新选择

---

## 调用示例

### Case 1：导航到页面，填写表单并提交

```bash
python -m harness -p "打开 http://example.com/register，在表单中填写用户名 testuser、邮箱 test@example.com、密码 Pass123，点击注册按钮，确认注册成功" --output-dir ./output/
```

**预期行为：**
1. `navigate("http://example.com/register")` -> 页面加载，获取页面状态
2. `get_page_content()` -> 识别表单元素：`input#username`, `input#email`, `input#password`, `button[type=submit]`
3. `fill("#username", "testuser")` -> 填写用户名
4. `fill("#email", "test@example.com")` -> 填写邮箱
5. `fill("#password", "Pass123")` -> 填写密码
6. `click("button[type=submit]")` -> 提交表单，页面跳转到成功页
7. `extract_text(".success-message")` -> 提取确认文本 "注册成功"
8. `finish(status="success", summary="注册完成，确认页显示注册成功")`

### Case 2：跨分页提取表格数据

```bash
python -m harness -p "打开 http://example.com/products，提取所有产品的名称和价格，翻页直到最后一页，结果写入 products.csv" --output-dir ./output/
```

**预期行为：**
1. `navigate("http://example.com/products")` -> 打开产品列表页
2. `get_page_content()` -> 识别表格结构和分页控件
3. `extract_text("table")` -> 提取第 1 页表格数据（25 行）
4. `click("a.next-page")` -> 翻到第 2 页
5. `extract_text("table")` -> 提取第 2 页数据
6. （重复翻页+提取，直到下一页按钮不存在）
7. `write_file("products.csv", "name,price\n...")` -> 汇总写入 CSV
8. `finish(status="success", summary="共提取 3 页 75 条产品数据")`

---

## 技术要求

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，通过环境变量配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 浏览器自动化：`playwright`（使用 `playwright.sync_api`）
- 禁止使用：LangChain / LlamaIndex / AutoGen / anthropic SDK
- 必须提供 `Dockerfile`（基于 `python:3.11-slim`）和 `requirements.txt`
- Dockerfile 中 LLM 配置通过环境变量注入，不硬编码
- **Dockerfile 必须包含 Playwright 及浏览器的安装**：
  ```dockerfile
  RUN pip install playwright && playwright install --with-deps chromium
  ```

---

## 最低要求清单

你的 harness **必须**满足以下所有条件：

1. `python -m harness -p "..." --output-dir ./output/` 可运行
2. 使用 `openai` SDK 调用 LLM（至少每个任务调用 1 次）
3. 使用 function calling / tool calling 模式驱动工具执行
4. 使用 `playwright` 进行浏览器自动化（启动浏览器、导航、交互）
5. 至少实现 6 个工具：navigate, click, fill, extract_text, get_page_content, finish
6. `get_page_content` 返回简化页面表示（标题 + 文本 + 链接列表 + 表单元素），而非原始 DOM
7. 产出 `result.json`（含 status 和 trajectory 字段）
8. 产出 `trajectory.jsonl`（每步记录 action 和 observation）
9. 提供 `Dockerfile` 和 `requirements.txt`
10. Dockerfile 中安装 `playwright` 及 Chromium：`pip install playwright && playwright install --with-deps chromium`
11. LLM API 调用有指数退避重试（至少 3 次）
12. 消息历史超长时自动压缩（截断旧工具输出或移除旧轮次）
13. 检测连续相同动作并注入策略切换提示
14. 达到步数上限时保存部分结果，异常时仍输出 result.json
