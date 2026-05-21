# Agent Harness 构建任务：研究智能体（Research Agent）

构建一个通用的深度研究 harness，能接受研究问题，自主完成信息检索、来源评估、证据组织和结构化报告生成。

---

## 一、接口契约

### 输入（TaskSpec）

```python
{
    "research_questions": list[str],  # 研究问题列表
    "min_sources": int,               # 最少引用来源数（默认 10）
    "max_words": int,                 # 报告最大词数
    "required_sections": list[str],   # 必须包含的章节
    "max_hops": int,                  # 多跳检索最大深度（默认 3）
    "output_dir": str,                # 输出目录
    "constraints": list[str],         # 附加约束
}
```

### 输出（Result）

```python
{
    "status": str,                    # "success" | "partial" | "failed"
    "report_path": str,               # 结构化报告文件路径
    "sources": list[{                 # 使用的来源
        "id": int,
        "url": str,
        "title": str,
        "credibility": str,           # "high" | "medium" | "low"
    }],
    "citation_integrity": {           # 引用完整性
        "total_citations": int,
        "orphaned": int,              # 报告中引用了但参考文献列表没有的
        "unused": int                 # 参考文献列表有但正文没引用的
    },
    "gaps": list[str],                # 未能充分回答的子问题
    "trajectory": str,                # JSONL trajectory 文件路径
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
| **E** Execution Loop | 驱动研究流程 | 显式状态机。必须支持多跳循环（信息不足时回到搜索阶段）且有 `max_hops` 终止条件 |
| **T** Tool Registry | 研究工具集 | 至少覆盖搜索、内容提取、来源评估能力，可自行扩展。工具应有 retry 策略 |
| **C** Context Manager | 管理证据上下文 | 核心是证据库（source → facts 映射）。每条事实必须可溯源到原始来源 |
| **S** State Store | 持久化研究进度 | 维护：来源列表、提取的事实、章节草稿、引用映射表。支持增量更新 |
| **L** Lifecycle Hooks | 研究边界控制 | 至少覆盖：搜索前去重、起草前检查证据充分性、起草后校验引用完整性 |
| **V** Evaluation | 研究轨迹记录 | JSONL，每步记录：查询内容、返回来源数、评估结果、提取的事实条数 |

---

## 三、领域能力

- **查询分解**：将复杂问题拆为原子子查询，识别依赖关系
- **多源搜索**：Web 搜索 + 学术搜索，并行检索，低质量时自动重构查询
- **来源评估**：分类（学术论文 > 官方文档 > 博客 > 社交媒体）、时效性、相关性评分
- **信息提取**：从文档中提取关键事实、数据点、引用，带归属
- **多跳推理**：基于发现生成后续查询，有最大深度限制，支持收敛检测
- **引用管理**：行内引用 + 完整参考文献列表，保证一致性无断链
- **交叉验证**：关键声明跨多源验证，标记矛盾
- **报告生成**：结构化章节，每个事实性陈述有引用支撑，多方观点平衡呈现

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

harness 将被用于处理实际的研究任务（不同主题、不同约束），评测时关注：

- 多跳检索是否在 max_hops 内正确终止（非无限循环）
- 引用完整性：报告中的 [N] 是否都能在参考文献列表找到对应条目
- 证据溯源：报告中的事实性陈述是否都能追溯到具体来源
- 来源去重：同一 URL 是否只处理一次
- 报告结构：是否包含所有 required_sections
- 多方观点：是否呈现不同立场而非单一偏向

---

## 五、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 网络请求：httpx 或 aiohttp
- 搜索接口：通过 Tool 抽象定义（如 `search_web(query) -> results`），具体实现可对接任意搜索 API
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 六、禁止事项

- ❌ 六组件糅合
- ❌ 编造来源或引用（所有引用必须来自实际检索）
- ❌ 引用断链（正文引了 [3] 但参考文献列表没有）
- ❌ 多跳检索无终止条件（必须受 max_hops 约束）
- ❌ 生成无来源支撑的事实性陈述
- ❌ 省略代码
