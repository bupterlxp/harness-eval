# Agent Harness 构建任务：创意写作智能体（Creative Writing Agent）

构建一个通用的创意写作 harness，能接受写作任务规格（体裁、风格、约束），自主完成从规划到终稿的全流程创作。

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
| **E** Execution Loop | 驱动创作流程 | 显式状态机。必须支持多阶段创作流程（至少包含规划、生成、检查、修订阶段） |
| **T** Tool Registry | 写作工具集 | 至少覆盖情节规划、场景起草、一致性检查能力，可自行扩展。每个工具有明确的输入输出 schema |
| **C** Context Manager | 管理创作上下文 | 必须实现防止风格漂移和指代漂移的机制（如声音锚点、意象追踪等），每次场景生成时主动注入 |
| **S** State Store | 持久化创作状态 | 支持场景级粒度的 snapshot 和 rollback。重写某场景不影响其他已完成场景 |
| **L** Lifecycle Hooks | 创作边界控制 | 至少覆盖：场景生成前注入风格锚点、生成后检查一致性、超时中断保存当前草稿 |
| **V** Evaluation | 创作轨迹记录 | JSONL，每步记录：当前状态、场景 ID、生成字数、一致性检查结果 |

---

## 三、领域能力

- **规划**：从前提生成情节节拍表、展开为场景级大纲、角色弧线规划
- **声音管理**：定义并维护叙述者风格锚点，每次场景生成时一致注入
- **逐场景生成**：以场景为单位独立生成，注入前文上下文和风格锚点
- **一致性维护**：角色名/特征、时间线、意象/隐喻指代的前后一致性检查
- **修订能力**：扩展（加细节）、压缩（去冗余）、风格重写、节奏调整
- **体裁感知**：不同体裁调整生成策略（惊悚重氛围、言情重情感节拍）
- **篇幅控制**：各场景字数分配、总字数预算追踪
- **质量评估**：风格度量（句长变化、意象密度、修辞频率）、连贯性检查

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

harness 将被用于处理实际的创作任务（不同体裁、不同约束），评测时关注：

- 状态机是否完整走完多阶段创作流程
- 风格锚点是否在每次场景生成时被注入（防止风格漂移）
- 是否实现了指代漂移检测（前面说"蓝色眼睛"后面不能变成"棕色"）
- 场景回滚是否工作（重写场景 3 时恢复到场景 2 的状态）
- 终稿字数是否在目标范围内
- 一致性检查是否能发现明显矛盾

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：无额外特殊依赖
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`）
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`

---

## 七、禁止事项

- ❌ 六组件糅合
- ❌ 场景生成时不注入风格锚点（会导致风格漂移）
- ❌ 一次性生成全文而非逐场景（无法做一致性检查和回滚）
- ❌ 硬编码特定体裁或风格
- ❌ 省略代码
- ❌ 无限重写无退出条件
