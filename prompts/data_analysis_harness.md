# Agent Harness 构建任务：数据分析智能体（Data Analysis Agent）

构建一个通用的数据分析 harness，能接受数据文件和分析需求描述，自主完成数据探索、统计分析、可视化和报告生成。

---

## 一、入口与输出

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`
- 工作目录中可能包含任务所需的数据文件等，harness 应自动发现并使用

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
| **E** Execution Loop | 驱动分析流程 | 显式状态机。支持步骤回溯。状态间有明确的输入/输出 |
| **T** Tool Registry | 注册分析工具 | 至少覆盖数据加载、统计计算、可视化生成能力，可自行扩展。每个工具声明输入输出类型 |
| **C** Context Manager | 管理 LLM 上下文 | **禁止**将 DataFrame 全文转成字符串塞进 prompt。必须用 schema + 统计摘要代替 |
| **S** State Store | 持久化分析状态 | 每步执行后 snapshot。支持 rollback 到任意步骤 |
| **L** Lifecycle Hooks | 边界检查 | 至少覆盖：执行前检查数据非空、执行后验证输出合理性、绘图前检查数据量 |
| **V** Evaluation | 结构化轨迹 | JSONL，每步记录：输入 shape、执行代码片段、输出 shape、生成的图表路径 |

---

## 三、领域能力

- **数据接入**：CSV/Excel/JSON/Parquet，自动 schema 检测，编码处理
- **数据质量**：缺失值检测、异常值标记（IQR/Z-score）、类型推断、重复检测
- **分析类型**：描述统计、趋势分析、分组对比、相关性分析、分布分析
- **可视化**：根据数据特征推荐图表类型，生成图表文件（禁止 plt.show()），至少支持折线图/柱状图/散点图/热力图/箱线图
- **验证**：每步变换后检查 shape、数值合理性检查、派生指标交叉验证
- **输出**：可独立执行的 Python 脚本 + 带图表的文字报告 + 结构化洞察

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

harness 将被用于处理实际的数据分析任务（不同数据集、不同分析目标），评测时关注：

- 能否正确加载数据并生成准确的数据画像
- 生成的图表是否为文件（非 plt.show()）且类型合理
- 数值计算是否准确（可手动抽查验证）
- 洞察是否有具体数值支撑（非模糊描述）
- 步骤回溯是否正常工作
- 是否在 max_steps 内完成（未无限循环）
- 是否在 DataFrame 过大时仍能正常工作（上下文压缩）

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：pandas、matplotlib、seaborn、numpy
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`），包括 pandas、matplotlib、seaborn、numpy 等
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`

---

## 七、禁止事项

- ❌ 六组件糅合
- ❌ DataFrame 全文塞进 prompt
- ❌ plt.show() 替代图表文件输出
- ❌ 硬编码数据文件路径或列名
- ❌ 生成没有数据支撑的"洞察"
- ❌ 省略代码
