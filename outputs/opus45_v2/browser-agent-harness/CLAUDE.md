# Agent Harness 构建任务：浏览器智能体（Browser Agent）

构建一个通用的浏览器自动化 harness，能接受 Web 任务描述（导航、表单填写、数据提取、文件下载等），自主在浏览器中完成多步骤操作。

---

## 一、接口契约

### 输入（TaskSpec）

```python
{
    "target_url": str,          # 起始 URL
    "task_description": str,    # 自然语言任务描述
    "credentials": dict | None, # 登录凭据（如有）
    "output_dir": str,          # 截图和下载文件存放目录
    "max_steps": int,           # 最大操作步数（默认 50）
}
```

### 输出（Result）

```python
{
    "status": str,              # "success" | "partial" | "failed"
    "extracted_data": dict,     # 从页面提取的结构化数据
    "screenshots": list[str],   # 关键步骤截图路径列表
    "downloads": list[str],     # 下载的文件路径列表
    "errors": list[{            # 遇到的错误及处理方式
        "step": int,
        "error": str,
        "recovery": str         # "retried" | "skipped" | "failed"
    }],
    "trajectory": str,          # JSONL trajectory 文件路径
}
```

### 入口

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`（符合上述 Result schema）

---

## 二、架构约束 H = (E, T, C, S, L, V)

实现必须包含以下六个**可独立识别**的组件，对应模块名为 `execution`, `tools`, `context`, `state`, `lifecycle`, `evaluation`：

| 组件 | 职责 | 硬性要求 |
|------|------|----------|
| **E** Execution Loop | 驱动浏览器操作 | 显式状态机。必须分离任务级流程（任务分解和推进）和单次页面操作的逻辑。支持单步 retry 和 skip |
| **T** Tool Registry | 浏览器操作工具 | 至少覆盖导航、元素交互、数据提取、截图、等待能力，可自行扩展。所有操作前必须先等待元素就绪 |
| **C** Context Manager | 管理页面上下文 | **禁止**将完整 DOM/HTML 塞进 prompt。必须用可访问性树摘要或关键元素列表代替 |
| **S** State Store | 任务状态持久化 | 维护步骤依赖关系和状态。支持断点续跑：中途失败后从最后成功步骤恢复 |
| **L** Lifecycle Hooks | 页面事件处理 | 至少覆盖：导航后自动等待加载、弹窗自动检测并处理（非阻塞）、超时时截图并重试 |
| **V** Evaluation | 操作轨迹记录 | JSONL，每步记录：URL、操作类型、目标元素、操作结果、截图路径 |

---

## 三、领域能力

- **导航**：URL 访问、前进/后退/刷新、跨页面跳转
- **交互**：点击、文本输入、下拉选择、日期选择、复选框、文件上传、键盘操作
- **等待**：元素出现/可见/可点击、页面加载完成、网络空闲
- **弹窗处理**：Cookie 横幅、alert/confirm/prompt、模态框——必须非阻塞（处理后继续原任务）
- **数据提取**：从页面提取结构化数据（文本、表格、列表）
- **元素定位**：优先用语义化方式（aria-label、文本内容、placeholder），CSS/XPath 作为回退
- **错误恢复**：元素未找到重试、页面超时重新加载、最大重试次数限制
- **证据保留**：关键操作前后截图

---

## 四、验证标准

### 结构验证

```bash
python -c "import harness"
python -c "from harness import execution, tools, context, state, lifecycle, evaluation"
python -m harness --help
python -m pytest tests/ --co -q
```

### 功能验证（下游任务）

harness 将被用于在实际 Web 应用上执行多步骤任务，评测时关注：

- 任务级流程与页面操作逻辑是否正确分离（外层推进时内层重置）
- 弹窗出现时是否非阻塞处理后继续原任务
- 跨页面是否正确累积已提取的数据
- 操作失败时是否截图、重试、最终 graceful 退出
- 断点续跑是否从正确的步骤恢复
- DOM 是否被摘要压缩而非全文注入 prompt

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 浏览器自动化：Playwright（推荐 async API）
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、禁止事项

- ❌ 六组件糅合
- ❌ 完整 DOM/HTML 塞进 prompt
- ❌ 未等待加载就操作元素
- ❌ 弹窗阻塞整个流程
- ❌ 硬编码特定网站的 DOM 结构
- ❌ 省略代码
- ❌ 无重试上限导致无限循环
