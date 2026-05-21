# Research Agent Harness 功能能力研究文档

> 基于 dzhng/deep-research、gpt-researcher、MS-Agent (ModelScope)、DeepResearch (Alibaba) 四个项目的深度分析

---

## 一、多跳检索 (Multi-hop Retrieval)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 递归深度研究 | gpt-researcher | `deep_research()`: breadth(3) × depth(2) 搜索树，每层从结果提取 follow-up questions 递归 |
| 迭代搜索循环 | MS-Agent | Searcher 默认4轮: 查询构建→Web搜索→证据评估→结构化存储 |
| 广度+深度控制 | gpt-researcher | 每层广度减半 `max(2, breadth//2)`，深度 depth-1 直到为1停止 |
| Evidence-Driven | MS-Agent | 根据已收集证据中的 gap 动态构造后续搜索查询 |
| 子查询分解 | gpt-researcher | `plan_research_outline()` 初始搜索后 LLM 生成 max_iterations 个子查询 |
| 多引擎并行 | MS-Agent | Exa + arXiv + SerpAPI 同时搜索，5 并发抓取 + 15 摘要工作线程 |
| RL 训练触发 | DeepResearch(Alibaba) | GRPO 训练的检索触发策略，自动决定何时需要搜索 |

### 调用 Case

```
研究 "人工智能对医疗行业的影响":
→ 第1轮(depth=2, breadth=3): 搜索总体概述
→ 发现子主题: "AI辅助诊断"/"药物研发AI"/"AI手术机器人"
→ 第2轮(depth=1, breadth=2): 每个子主题深入搜索
→ 从第2轮发现追问: "FDA对AI医疗设备的监管进展"
→ 总计 3×3 + 3×2 = 15 次搜索，覆盖多层知识
```

```
MS-Agent 4轮迭代搜索:
→ Round 1: "碳捕获技术概述" → 发现 DAC 是重要方向
→ Round 2: "DAC 直接空气捕获成本分析" → 发现 Climeworks 项目
→ Round 3: "Climeworks Orca 工厂运营数据" → 获得具体数字
→ Round 4: "DAC vs 传统 CCS 对比" → 完善论证
→ 每轮输出 findings/gaps/next_steps
```

---

## 二、证据管理 (Evidence Management)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 向量嵌入过滤 | gpt-researcher | `EmbeddingsFilter(similarity_threshold=0.35)` 按相似度筛选 |
| 文档分块压缩 | gpt-researcher | `RecursiveCharacterTextSplitter(chunk_size=1000, overlap=100)` |
| 结构化证据卡片 | MS-Agent | EvidenceTool: 标题/支持内容/矛盾证据/来源URL/摘要/标签/质量评分/唯一ID |
| 持久化存储 | MS-Agent | `evidence/notes/`(单条) + `evidence/analyses/`(综合) + `evidence/index.json`(索引) |
| URL 去重 | gpt-researcher | visited_urls 集合确保不重复抓取 |
| 上下文词数限制 | gpt-researcher | MAX_CONTEXT_WORDS=25000, `trim_context_to_word_limit()` |
| 小文档优化 | gpt-researcher | 总字符<8000 时跳过嵌入压缩直接使用 |
| 文件锁安全 | MS-Agent | 所有证据读写使用文件锁保证并发安全 |
| Analysis 记录 | MS-Agent | 综合多条 note 的中间推理: 比较/框架/场景映射/建议，引用 note ID |

### 调用 Case

```
搜索"量子计算最新进展"抓取50个网页(100万字):
→ RecursiveCharacterTextSplitter 切分为 1000 个 chunk
→ EmbeddingsFilter 按"量子纠错/量子优越性"相似度过滤
→ 保留约 2.5 万词高相关上下文
→ 大幅降低 LLM 输入成本和噪音
```

```
MS-Agent 证据收集:
→ 搜索方案A性能数据 → evidence_store.write_note(
    title="方案A延迟指标",
    content="P99延迟<10ms at 100K QPS",
    source="https://benchmark.example.com",
    tags=["performance", "latency"],
    quality_score=0.9
  )
→ 搜索方案B → 创建对应 note
→ evidence_store.write_analysis(
    title="方案A vs B性能对比",
    content="A在延迟上优于B 40%，但B吞吐量高2x",
    references=["note_abc123", "note_def456"]
  )
```

---

## 三、基于证据的综合生成 (Grounded Synthesis)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 上下文作为唯一信息源 | gpt-researcher | Prompt: "Using the above information, answer..." |
| 多层深度综合 | gpt-researcher | "Synthesize from multiple levels of research depth" |
| 专业角色注入 | gpt-researcher | 动态选择 Agent (金融分析师/旅行顾问/学术研究员) |
| 禁止幻觉 | gpt-researcher | "based ONLY on the provided search results" |
| 引用追踪 | MS-Agent | citations 字典: learning → URL 映射 |
| 结构化报告 | DeepResearch(Alibaba) | Rational-Evidence-Summary 三层结构 |

### 调用 Case

```
用户: "SpaceX Starship 2024年试飞结果"
→ 收集多个新闻源报道作为 context
→ LLM Prompt: "Information: {50个相关文档片段}. Using the above, answer..."
→ 生成报告: 每个事实陈述来源于已抓取上下文(非训练数据)
→ "第四次试飞成功回收助推器([SpaceNews](url))"
```

---

## 四、引用处理 (Citation Handling)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 行内超链接引用 | gpt-researcher | `([in-text citation](url))` 格式置于句末 |
| APA 格式 | gpt-researcher | `Author, A. A. (Year). Title. [url](url)` |
| 参考文献列表 | gpt-researcher | `add_references()` 在报告末尾追加 `## References` |
| Deep Research 引用 | gpt-researcher | `process_research_results()` 从结果提取 learning→URL 映射 |
| 证据卡片溯源 | MS-Agent | 每条 note 关联 source URL，analysis 引用 note ID |

### 调用 Case

```
生成气候变化政策报告:
→ 正文: "全球碳排放在2023年达到历史新高([IPCC AR6](https://...))"
→ "中国承诺2060年前碳中和([新华社](https://...))"
→ 末尾: ## References
  - [IPCC Sixth Assessment Report](https://ipcc.ch/...)
  - [新华社: 中国碳中和承诺](https://xinhuanet.com/...)
```

---

## 五、任务分解 (Task Decomposition)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 6 种分析框架 | MS-Agent | MECE/金字塔/BCG矩阵/帕累托/SWOT/价值链 |
| SplitTask 工具 | MS-Agent | 接受任务数组，支持 parallel/sequential 执行模式 |
| TodoList 管理 | MS-Agent | plan.json: pending/in_progress/completed/cancelled + 优先级 |
| 子查询并发 | gpt-researcher | max_iterations 个子查询通过 asyncio 并发执行 |
| DAG Workflow | MS-Agent | 有向无环图式任务编排，父输出自动传递给子任务 |
| 层级分解 | DeepResearch(Alibaba) | 高层问题→子问题→搜索查询 三级分解 |

### 调用 Case

```
用户: "全面评估某公司投资价值"
→ SWOT 原则分解:
  1. [parallel] 宏观环境分析 (Searcher)
  2. [parallel] 行业竞争格局 (Searcher)
  3. [parallel] 财务数据对比 (Searcher)
  4. [parallel] 管理层评估 (Searcher)
  5. [sequential, rely=[1,2,3,4]] 综合投资建议 (Reporter)
→ 前4步并行执行，第5步等待所有完成后综合
```

```
MS-Agent DAG Workflow:
→ Task A: 收集基础数据 → 
→ Task B (依赖A): 统计分析 → 
→ Task C (依赖A): 趋势分析 →
→ Task D (依赖B,C): 综合报告
→ A 完成后 B/C 自动并行启动
→ B,C 都完成后 D 自动启动
```

---

## 六、工具编排 (Tool Orchestration)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| ToolManager | MS-Agent | 命名空间索引 + MAX_CONCURRENT=20 + 超时30s(研究场景2400s) |
| AgentTool | MS-Agent | 子 Agent 暴露为可调用工具，支持后台线程/隔离进程/流式结果 |
| WebSearchTool | MS-Agent | 多引擎(Exa/SerpAPI/arXiv) + 内容获取 + 可选摘要 + 并发URL抓取 |
| MCP 集成 | MS-Agent | stdio/SSE/WebSocket/streamable HTTP 四种传输连接 MCP 服务器 |
| 并行工具调用 | MS-Agent | LLMAgent.parallel_tool_call() 原生支持 |
| 内容优化器 | MS-Agent | ContentOptimizer: 相关性重排序(标题重叠度+来源可信度+时间新旧) + 智能摘要 |
| JinaReader | MS-Agent | 网页内容提取, 指数退避重试, 异步批量抓取 |

### 调用 Case

```
Researcher 同时搜索3个子话题:
→ parallel_tool_call 启动 3 个 Searcher (AgentTool)
→ 每个 Searcher 内部并行抓取 5 个 URL (JinaReader)
→ ContentOptimizer 重排序结果 (可信度+相关性+时间)
→ ToolManager semaphore 控制总并发 ≤ 20
→ 3个子话题同时完成 → Researcher 综合所有结果
```

---

## 七、记忆与上下文管理 (Memory/Context)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 语义记忆 + RAG | MS-Agent | 向量检索 + BM25 混合 |
| Round-Aware 提醒 | MS-Agent | SearcherCallback 在接近最大轮次时注入提醒避免无限循环 |
| 文件系统持久化 | MS-Agent | 所有中间产物(证据/分析/搜索结果)持久化到磁盘 |
| 上下文预算 | gpt-researcher | MAX_CONTEXT_WORDS=25000 动态截断 |
| 跨运行知识复用 | MS-Agent | 证据库在多次研究间共享，支持断点续传 |

### 调用 Case

```
研究任务执行到第28/30轮:
→ SearcherCallback 注入: "接近最大轮次，请优先完成关键证据收集"
→ Searcher 停止扩展新方向，专注填补现有 gap
→ 最终输出: 结构化 JSON (findings + citations + follow_ups)
```

---

## 八、多 Agent 协作架构 (Multi-Agent Architecture)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| Researcher→Searcher→Reporter | dzhng/deep-research | 三角色分工: 规划/执行/写作 |
| 主控+子智能体 | MS-Agent | Researcher 作为主控调用 Searcher 作为工具 |
| Breadth-First 探索 | dzhng/deep-research | 先广度探索子主题，再深入各分支 |
| 独立 Searcher 配置 | MS-Agent | searcher.yaml: 最多30轮对话, 5条/搜索, 15摘要线程 |
| Reporter 综合 | dzhng/deep-research | 收集所有 Searcher 结果后统一生成报告 |
| Writer Agent | gpt-researcher | 独立的写作 Agent 从研究结果生成长报告 |

### 调用 Case

```
dzhng/deep-research 工作流:
→ Researcher: 分析问题 → 生成3个搜索方向
→ Searcher×3: 并行执行广度探索
→ Researcher: 评估结果 → 识别需要深入的2个方向
→ Searcher×2: 深入搜索
→ Reporter: 综合所有发现 → 生成结构化报告
```

```
gpt-researcher Writer Agent:
→ 研究阶段完成: 收集了 25000 词上下文 + 引用列表
→ Writer Agent 启动: 按 outline 分段生成
→ 每段引用来源, 末尾附完整 References
→ 输出: 3000-5000 词结构化报告
```

---

## 九、报告生成 (Report Generation)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 多种报告类型 | gpt-researcher | research_report/resource_report/outline_report/custom_report/subtopic_report |
| 长报告分段写作 | gpt-researcher | outline → 逐节生成 → 拼接 |
| Markdown 输出 | gpt-researcher/MS-Agent | 标准 Markdown + 行内引用 |
| 结构化 JSON 交付 | MS-Agent | Searcher Phase 3: 最终 JSON (findings/sources/follow_ups) |
| 多格式导出 | gpt-researcher | Markdown/PDF/Docx |
| Deep Research 报告 | gpt-researcher | 综合多层深度研究 + 完整引用 |

### 调用 Case

```
用户: "写一份关于量子计算的深度研究报告"
→ 类型: deep_research_report
→ 多层搜索完成后:
  1. 生成 outline (5-8 个大节)
  2. 逐节生成内容 (每节 500-1000 词)
  3. 每段嵌入行内引用
  4. 添加 References 列表
  5. 输出 4000 词 Markdown 报告
```
