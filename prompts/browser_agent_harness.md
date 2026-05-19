# Agent Harness 构建任务：浏览器智能体（Browser Agent）

构建一个通用的浏览器自动化 harness，能接受 Web 任务描述（导航、表单填写、数据提取、文件下载等），自主在浏览器中完成多步骤操作。

---

## 一、入口与输出

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`

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
- DOM 是否被摘要压缩而非全文注入 prompt

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 浏览器自动化：Playwright（推荐 async API）
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`）
- 安装 Playwright 及其浏览器依赖（`playwright install --with-deps chromium`）
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`

---

## 七、禁止事项

- ❌ 六组件糅合
- ❌ 完整 DOM/HTML 塞进 prompt
- ❌ 未等待加载就操作元素
- ❌ 弹窗阻塞整个流程
- ❌ 硬编码特定网站的 DOM 结构
- ❌ 省略代码
- ❌ 无重试上限导致无限循环
