# Agent Harness 构建任务：检索/研究智能体（Research Agent）

你将为**深度研究与信息检索**领域构建一个完整的 agent harness。本提示词是你的工作 spec，定义了方法论、形式化约束、交互规范和交付标准。

---

## 一、用户输入

### 1. 功能样例（FEATURE_EXAMPLE）

#### 1.1 理想输入（IDEAL_INPUT）

```
研究主题：大语言模型在代码生成领域的最新进展与挑战
研究问题：
  1. 目前主流的代码生成大模型有哪些？它们在 HumanEval 和 MBPP 等基准上的表现如何？
  2. 代码生成模型的训练数据来源有哪些？存在哪些数据质量和版权问题？
  3. 从 Codex 到 GPT-4 到 Claude，代码生成能力经历了哪些关键技术突破？
  4. 当前代码生成模型在处理复杂、多文件项目时面临哪些挑战？
  5. 代码生成模型在安全性方面存在哪些风险？如何评估生成代码的安全性？
约束：
  - 引用至少 10 个可靠来源
  - 报告不超过 3000 词
  - 必须包含：摘要、背景与动机、主流模型对比、关键技术进展、当前挑战、未来方向、参考文献
  - 引用格式：作者(年份). 标题. 来源. URL
  - 报告必须客观，呈现多方观点，避免偏向单一厂商
```

#### 1.2 理想产出（IDEAL_OUTPUT）

完整参考报告存放在：**`./samples/reference_report.md`**
研究任务规格存放在：**`./samples/research_questions.json`**

> 在阶段 1 开始之前，你必须先用 Read 工具完整读取 `./samples/reference_report.md` 和 `./samples/research_questions.json`，作为后续设计、实现、比对的事实基准。
> 该参考报告的关键属性（用于后续比对）：
> - 结构化报告，包含 7 个必需章节（摘要、背景与动机、主流模型对比、关键技术进展、当前挑战、未来方向、参考文献）
> - 12 个引用来源，每个都有 arXiv URL
> - 主流模型对比表格（7 个模型 × 参数量/开源/HumanEval/MBPP/特点）
> - 所有事实性陈述有引用支撑
> - 开源 vs 闭源两条路线的优势与局限并列呈现
> - 覆盖 4 大技术进展（instruction tuning、FIM、repo-level context、agent 化）
> - 覆盖 4 大挑战（多文件项目、长上下文、安全性、测试验证）

#### 1.3 中间过程预期（EXPECTED_TRAJECTORY）

```
1. 问题分解 → 将 5 个研究问题拆解为具体的检索查询（至少 10 个查询）
2. 初轮检索 → 对每个查询执行搜索，收集候选来源
3. 来源评估 → 评估每个来源的可靠性（学术论文 > 技术博客 > 新闻）、时效性、相关性
4. 深度阅读 → 对高质量来源提取关键信息、数据点、引用
5. 证据组织 → 按章节将提取的信息归类，识别信息缺口
6. 缺口填补 → 对信息不足的章节发起补充检索（多跳检索）
7. 交叉验证 → 对关键数据点（如基准得分）做多源交叉验证
8. 草稿撰写 → 按章节撰写报告，每个事实性陈述附上引用
9. 一致性检查 → 确保引用编号正确、无断链、无矛盾陈述
10. 终稿输出 → 格式化报告 + 完整参考文献列表
```

### 2. 交互形式（INTERACTION_SPEC）

- 命令行交互，支持长任务的进度汇报
- 检索过程实时展示（正在搜索 → 找到 N 个结果 → 评估中）
- 每完成一个章节，向用户展示该章节草稿供审查
- 用户可随时追加问题或调整方向
- `/sources` 列出已收集的所有来源及其评估等级
- `/gaps` 展示当前信息缺口
- `/outline` 展示当前报告大纲及各章节完成度
- `/verify [claim]` 对指定陈述做交叉验证

---

## 二、形式化基础（不可妥协）

**H = (E, T, C, S, L, V)**

| 符号 | 组件 | 代码层面的硬性要求 |
|------|------|---------------------|
| **E** Execution Loop | 状态机：DECOMPOSE → SEARCH → EVALUATE → EXTRACT → ORGANIZE → GAP_FILL → CROSS_VALIDATE → DRAFT → CONSISTENCY_CHECK → FINALIZE。GAP_FILL 可回到 SEARCH（多跳循环），有最大跳数限制 |
| **T** Tool Registry | 搜索引擎接口、网页内容提取器、PDF/论文解析器、引用格式化器、事实验证器。每个工具有 rate limit 和 retry 策略 |
| **C** Context Manager | 三层上下文：(1) 证据库（source → extracted_facts 的映射）(2) 大纲上下文（当前章节结构和已有内容）(3) 查询历史（避免重复检索）。压缩策略：证据按相关性评分排序，低于阈值的降级存储 |
| **S** State Store | 维护：来源列表及其评估状态、提取的事实/数据点、章节草稿、引用映射表。支持增量更新和全量快照 |
| **V** Evaluation Interface | JSONL trajectory：每步记录查询、来源评估结果、提取的信息、引用关系 |
| **L** Lifecycle Hooks | pre_search（去重检查）、post_search（来源质量过滤）、pre_draft（检查证据充分性）、post_draft（引用完整性校验）、on_rate_limit（退避等待） |

**关键判别准则**：
- E 的多跳检索必须有 **max_hops** 限制（默认 3），防止无限循环
- C 的证据库必须支持 **来源溯源**——每条事实都能追溯到原始 URL + 具体段落
- T 的搜索工具必须支持 **uncertainty-driven trigger**——当某个主题的证据不足时自动触发检索，而非固定轮次
- S 的引用映射表必须保证 **引用一致性**——报告中的 [1] 对应参考文献列表中的 [1]，不能断链

---

## 三、样例驱动的差异比对准则

`./samples/research_questions.json` 是事实基准。

| 阶段 | 比对动作 |
|------|---------|
| **设计期** | E 的状态机能否覆盖 5 个研究问题的完整检索-撰写流程？T 的工具是否覆盖学术检索和网页检索两个通道？ |
| **实现期** | C 的证据库结构能否支撑"至少 10 个来源"的约束？引用映射是否从第一次添加来源时就建立？ |
| **验证期** | (1) 报告是否包含全部 7 个章节 (2) 引用数 ≥ 10 (3) 模型对比表是否有 ≥ 5 个模型 (4) 引用是否完整无断链 (5) 是否呈现多方观点 |

---

## 四、工作流程

### 阶段 1：理解与规划

1. **读取样例**：读取 `./samples/research_questions.json`
2. **解析研究任务**：分析 5 个研究问题之间的依赖关系，确定最优检索顺序
3. **从样例反推架构**：推导 E/T/C/S/L/V 的设计
4. **领域故障分析**：
   - E 缺失 → 检索-撰写循环失控，在搜索阶段消耗所有预算
   - T 缺失 → 只能搜索不能提取，大量来源无法利用
   - C 缺失 → 证据散落在对话历史中，撰写时无法有效组织
   - S 缺失 → 中途中断后所有收集的证据丢失
   - L 缺失 → 触发 rate limit 后直接崩溃，无退避重试
   - V 缺失 → 无法追溯某个结论来自哪个来源
5. **工具清单**：
   - `web_search(query, max_results)` → safe
   - `fetch_page(url)` → safe
   - `extract_facts(content, questions)` → safe
   - `evaluate_source(url, content)` → safe（返回可靠性评分）
   - `format_citation(source_info)` → safe
   - `cross_validate(claim, sources)` → safe
   - `draft_section(section, evidence, outline)` → safe
6. **TodoWrite**

### 阶段 2：实现

```
harness/
├── __init__.py
├── schemas.py        # Source, Evidence, Citation, Section, ResearchQuery, ValidationResult
├── state.py          # S: EvidenceStore + CitationMapper + DraftManager
├── tools.py          # T: ToolRegistry
├── context.py        # C: EvidenceContext + OutlineContext + QueryHistory
├── lifecycle.py      # L: 去重 / 质量过滤 / 证据充分性检查 / 引用完整性 / rate limit
├── evaluation.py     # V: JSONL trajectory
├── execution.py      # E: 研究状态机（含多跳循环）
├── core.py           # H: 六组件聚合
├── cli.py            # 交互层（含 /sources /gaps /outline /verify）
└── domain/
    ├── tools.py      # 搜索引擎 / 网页提取 / 事实验证 / 引用格式化 / 章节起草
    └── prompts.py    # 问题分解 prompt / 来源评估 prompt / 撰写 prompt
samples/
└── research_questions.json
tests/
├── test_multi_hop.py          # 验证多跳检索的终止条件
├── test_citation_integrity.py # 验证引用一致性
├── test_evidence_tracking.py  # 验证证据溯源
└── test_e2e.py
```

### 阶段 3：验证与比对

1. pytest 全绿
2. 以 IDEAL_INPUT 运行 harness
3. 比对：
   - 章节覆盖度（7/7）
   - 引用数量（≥ 10）
   - 引用完整性（无断链）
   - 模型对比表（≥ 5 个模型）
   - 多方观点（开源 vs 闭源至少各有一段论述）
   - 多跳检索是否触发（至少发生 1 次缺口填补）

---

## 五、技术栈

- Python 3.11+，full type hints
- **LLM 调用必须使用 OpenAI 兼容接口**（`openai` Python SDK），**禁止使用 `anthropic` SDK**。配置从环境变量读取：
  - `OPENAI_BASE_URL`：API 端点地址（如 `http://127.0.0.1:3457/v1`）
  - `OPENAI_API_KEY`：API 密钥
  - `MODEL_NAME`：模型标识符
  - 调用方式：`client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])`，然后使用 `client.chat.completions.create(model=os.environ["MODEL_NAME"], ...)`
- httpx / aiohttp（网络请求）
- 禁止 LangChain / LlamaIndex / AutoGen

---

## 六、交付清单

1. 完整性自检表
2. 样例比对报告（7 章节 × 完成度 × 引用数 × 质量评估）
3. 快速开始命令
4. 关键设计决策（多跳最大深度 / 来源评估权重 / 证据压缩策略）
5. 下一步建议

---

## 七、禁止事项

- ❌ 不要省略代码
- ❌ 不要把六组件糅合
- ❌ 不要编造来源或引用
- ❌ 不要忽略引用一致性检查
- ❌ 不要跳过来源评估步骤
- ❌ 不要让多跳检索无限循环

---

现在，请确认你已读取 `./samples/research_questions.json`，然后从**阶段 1**开始。
