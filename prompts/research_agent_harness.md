# Agent Harness 构建任务：研究智能体（Research Agent）

构建一个通用的深度研究 harness，能接受研究问题，自主完成信息检索、来源评估、证据组织和结构化报告生成。

## Scaffold-native 最低实现要求

如果当前 creation profile 是 `claude_code_scaffold_native`，工作区已经有 `generated_program.py`、`scaffold_manifest.json` 和 `harness_scaffold/`。你必须直接修改并实现 `generated_program.py` 中的 `GeneratedHarnessProgram.run(...)`，不能停留在 scaffold seed。

必须满足：

- 删除或替换 `raise NotImplementedError`、`TODO`、stub fallback；
- `generated_program.py` 必须真实调用 `harness_scaffold` runtime，并驱动 query planning、search/fetch、evidence tracking、answer synthesis 和 verifier；
- 可以新增模块，但新增模块必须被 `generated_program.py` 实际调用；
- 不能只写 README、说明文档、helper 模块或未接入的工具；
- 运行后必须写出 `result.json`、`trajectory.jsonl`、stdout/stderr 日志，以及 `answer.md` / `answer.json`、`sources.json`、`evidence.json` 或等价 citation trace；
- 如果 search API 不可用，必须结构化记录缺失依赖并输出 `partial`，不能伪造 citation、URL 或证据。

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

### Research BMK 必须满足的执行契约

这个 harness 会直接接入 DeepResearch bench / BrowseComp 类研究任务。分数取决于答案是否正确且证据可追溯，而不是报告篇幅。因此必须做到：

- 根据问题类型选择直接答案、结构化答案或报告，不能所有任务都输出冗长综述；
- 每个事实性结论必须关联 evidence id、source URL 或可复查的来源摘要；
- `sources.json` / `evidence.json` 必须记录 search query、source title、URL、抓取时间、支撑片段和质量判断；
- `trajectory.jsonl` 必须记录 query decomposition、search/fetch、evidence_add、synthesis、verification 等关键步骤；
- `success` 的最低条件是答案非空、证据 trace 非空、引用和最终答案一致；
- 无证据、无 search trace、只靠模型常识生成的答案必须标记为 `partial` 或 `failed`。

---

## 二、功能性质

一个成熟的研究智能体 harness 接收自然语言研究问题后，自主将其分解为校准知识缺口的子问题树，通过多跳迭代检索构建证据体系，最终合成有据可查的结构化报告。

**多跳迭代检索。** 核心搜索引擎以广度×深度参数控制的递归模式运行：初始广泛搜索（breadth 个并行子查询）产出初步发现，对每层结果分析不足之处和知识缺口，自动生成精炼的后续查询深入追踪特定线索——每个周期继承前序轮次的累积认知。搜索深度逐层递减（每层广度减半直到下限），形成先宽后深的搜索树。支持多引擎并行搜索（通用 Web、学术论文库、专业数据源），并发抓取网页内容后用智能摘要压缩为证据片段。整个检索过程以迭代周期运行（默认 3-4 轮），每轮输出：当前发现 → 知识缺口分析 → 下一轮查询计划。

**证据管理与质量评估。** 每个检索到的文档经过处理管线：内容提取 → 文本分块（1000 字/块，100 字重叠）→ 向量嵌入相似度过滤（阈值 0.35 以上保留）→ 结构化证据卡片生成（标题/支持内容/矛盾证据/来源 URL/摘要/标签/质量评分/唯一 ID）。证据池具备：URL 去重防止重复抓取、上下文词数限制（25000 词上限动态截断）、小文档优化（总字符<8000 时跳过嵌入压缩直接使用）。跨多条证据的综合分析记录为 Analysis 文档，引用具体证据 ID，支持比较/框架映射/场景分析等推理模式。

**矛盾处理与多元视角。** 当来源间出现矛盾时，harness 保留竞争性主张及其各自归属而非静默丢弃少数观点。矛盾检测通过对同一事实点的多源证据交叉比对实现，在最终合成中显式呈现分歧并标注各方引用。用户可配置矛盾处理策略（并列呈现/权重排序/显式解决）。

**任务分解与并行编排。** 支持多种分析框架指导分解（MECE/金字塔/BCG矩阵/帕累托/SWOT/价值链），复杂研究问题被拆解为带依赖关系的子任务 DAG：无依赖的子查询通过 asyncio 并发执行，有依赖的按序等待前驱完成。层级分解从高层问题→子问题→具体搜索查询，每层可独立评估完成度。支持 parallel/sequential 两种执行模式混合。

**引用系统与溯源。** 全程维护 learning→URL 的精确映射。报告中每个事实性主张映射到一个或多个编号引用 `[N]`，来自经验证的证据池。尾部参考文献列表提供完整源信息（URL、标题、检索时间戳）。系统通过仅从实际引用的来源构建参考文献列表来强制引用一致性——消除孤立引用或虚假引用。支持 APA 格式和行内超链接两种引用风格。

**报告生成与精确问答。** 支持两种输出模式：(1) 结构化报告——多种类型（对比评估/综述/大纲/深度研究），长报告采用分段写作（先 outline 逐节生成再拼接）；(2) 精确问答——对于有明确答案的问题（事实性问题、计算题、专业知识题），在研究完成后提炼为简洁的直接答案（可能是一个数字、一个名称、一段公式推导、或一个多选项判断），避免输出冗长报告而丧失问题解答精度。系统根据问题类型自动判断输出模式：开放探索性问题→报告，封闭事实性问题→精确答案+支撑证据。综合多层深度研究结果时，从所有搜索层的发现中提炼主题和趋势。严格遵循"仅基于检索到的证据"原则，禁止使用模型训练知识填充，确保每个主张都有证据支撑。

**上下文管理与预算控制。** 上下文词数硬限（25000 词），超限时动态截断最低相关性证据。搜索过程维护 visited_urls 集合避免重复访问。接近最大搜索轮次时注入提醒要求优先完成关键证据收集而非继续扩展新方向。证据库支持跨运行共享和断点续传。可配置的深度（depth）和广度（breadth）参数控制详尽覆盖与计算成本间的权衡。

**多 Agent 协作架构。** 支持 Researcher→Searcher→Reporter 三角色分工：Researcher 作为主控分析问题和规划搜索方向；多个 Searcher 并行执行搜索、抓取和证据提取；Reporter 综合所有 Searcher 结果生成最终结构化报告。每个 Searcher 独立配置搜索轮数和并发参数，可适应不同子任务的复杂度。

---

## 三、调用示例

### Case 1：技术对比评估（多维度搜索 + 矛盾处理 + 结构化对比）

```bash
python -m harness -p "对比 QuantumScape、Toyota、Samsung SDI 截至 2025 年固态电池量产就绪度，谁最接近商用 EV 部署？" --output-dir ./output/
```

**行为轨迹：**
- 任务分解（MECE 框架）：
  - 子查询 1："QuantumScape 固态电池 2024-2025 产线时间表 量产进度"
  - 子查询 2："Toyota 全固态电池 量产计划 合作伙伴 EV 部署"
  - 子查询 3："Samsung SDI 全固态 试产线 产能 正极材料路线"
  - 子查询 4："固态电池 技术对比 能量密度 循环寿命 成本 2025"
- Round 1（广度搜索，breadth=4，并行执行）：
  - 4 个子查询同时搜索 → 从 14 个来源提取信息
  - QuantumScape：QS-0 预生产线 2024Q4 投产，24 层电芯良率提升至 >90%，与 PowerCo(大众子公司) 合作
  - Toyota：2027-2028 量产目标，与 Idemitsu 合作硫化物电解质，充电 10 分钟续航 1200km 目标
  - Samsung SDI：全固态原型 2025 年展示，硫化物电解质路线，9 分钟充至 80%
  - 通用对比数据：能量密度 400-500 Wh/kg(固态) vs 250-300(液态当前)
- 缺口分析：
  - Samsung SDI 正极材料技术路线细节不足
  - QuantumScape 预估成本数据来源不一致
- Round 2（深度追踪，针对缺口）：
  - 追加查询："Samsung SDI 固态电池 正极材料 NMC vs 硫化物 技术路线 2025"
  - 追加查询："QuantumScape 固态电池 电芯成本 $/kWh 预估 分析师报告"
- 矛盾检测与处理：
  - 来源 [3]（投行报告）预估 QuantumScape 电芯成本 $80/kWh by 2027
  - 来源 [7]（行业分析）预估 $120-150/kWh by 2028
  - 保留双方主张：在报告中标注 "成本预估存在分歧：乐观预测 $80/kWh [3] vs 保守预测 $120-150/kWh [7]，差异主要来自良率假设不同"
- 证据综合（18 条证据，去重后）：
  - 按公司分节组织：技术路线 / 产线进度 / 合作伙伴 / 量产时间表
  - 生成对比表格（6 维度 × 3 公司）
  - 结论排名：Toyota（规模化路径最清晰但时间最晚）> QuantumScape（进度最快但良率风险）> Samsung SDI（技术验证阶段）

**产物：** `report.md`（1,800 字结构化报告：Introduction / 公司分节×3 / 对比表 / 成本争议分析 / Conclusion 含排名），`sources.json`（18 条含 URL、标题、检索时间、相关性评分、质量层级），引用 [1]-[18] 全部可解析且无孤立引用

---

### Case 2：多跳历史因果分析（迭代深入 + 交叉验证 + 学术争论呈现）

```bash
python -m harness -p "1997 年亚洲金融危机的主要因果因素是什么？IMF 条件性如何影响泰国与韩国的复苏时间线？" --output-dir ./output/
```

**行为轨迹：**
- 任务分解（因果链框架）：
  - 子问题 A："1997 亚洲金融危机 触发因素 资本流动 汇率机制"
  - 子问题 B："IMF 泰国 1997 结构调整计划 具体条件 时间线"
  - 子问题 C："韩国 IMF 1998 改革措施 GDP 恢复曲线"
  - 子问题 D："泰国 vs 韩国 复苏对比 为何韩国更快"
- Round 1（广度搜索）：
  - 从 22 个来源收集——包含学术论文(NBER working papers)、IMF 档案文档、新闻回顾(FT/WSJ)、世界银行数据
  - 关键发现：泰国固定汇率制崩溃 → 资本外逃 → 货币贬值 59% → 银行系统性危机
  - IMF 条件：泰国 16 条结构调整（含金融自由化+财政紧缩），韩国 14 条（含财阀改革+劳动市场开放）
- Round 2（缺口追踪——泰国资本管制细节）：
  - 追加查询："Thailand 1997 capital controls timeline Baht defense reserves depletion"
  - 获得关键数据：泰国央行在危机前 5 个月秘密消耗 $23.4B 外汇储备 defend 泰铢
- Round 3（定量交叉验证）：
  - 世界银行 GDP 数据：韩国 1998Q1 谷底(-6.7%) → 1999Q4 恢复至危机前水平（V 形）
  - 泰国 1998Q2 谷底(-12.5%) → 2003 才恢复（L 形/U 形）
  - 将 GDP 恢复曲线与 IMF 项目启动日期交叉标注
- Round 4（学术争论整理）：
  - 争论焦点："V 形 vs L 形复苏的决定因素"
  - Stiglitz [4] 归因于 IMF 财政紧缩使危机恶化
  - Radelet & Sachs [11] 归因于资本账户自由化顺序不当
  - Fischer [16] 辩护 IMF 条件性，认为韩国快速复苏证明条件有效
  - 保留三方视角，按各自论据和证据质量呈现

**产物：** `report.md`（2,200 字：危机起源(资本流动+固定汇率+道德风险) / IMF 条件包对比表 / 复苏时间线图表描述 / 学术争论三方呈现 / 结论：制度质量和改革执行力是复苏速度的关键变量），`evidence_pool.json`（26 来源，按质量分三层：Tier 1 学术/IMF 官方, Tier 2 主流媒体, Tier 3 博客/评论），引用 [1]-[22] 无断链

---

### Case 3：技术前沿综述（并行子查询 + 证据去重 + 结构化提取）

```bash
python -m harness -p "当前 RAG 系统中减少 LLM 幻觉的主流方法有哪些？总结方法、基准和报告的改进" --output-dir ./output/
```

**行为轨迹：**
- 任务分解（方法-基准-效果三维）：
  - 子查询 1："RAG hallucination reduction methods retrieval augmented generation 2024 2025"
  - 子查询 2："LLM factuality benchmarks evaluation metrics TruthfulQA FActScore"
  - 子查询 3："chain of verification self-reflection attribution RAG accuracy improvement"
  - 子查询 4："RAG vs fine-tuning hallucination reduction comparison survey"
- Round 1（4 个子查询并行搜索）：
  - 返回 31 来源（arXiv 论文 18 篇、工程博客 8 篇、基准排行榜 3 个、综述论文 2 篇）
  - 结构化提取每条证据：方法名 / 核心思路 / 使用基准 / 报告指标改进 / 发表场所
- 证据去重：
  - 检测到 5 个来源以不同名称描述同一 RARR(Retrofit Attribution using Research and Revision)方法
  - 合并为单条多出处证据，保留所有 URL
  - 最终去重后 28 条有效证据
- Round 2（缺口追踪）：
  - 初始结果缺少 Chain-of-Verification(CoVe) 的具体实验数据
  - 追加查询："Chain of Verification CoVe Meta 2024 results benchmark numbers"
  - 获得：CoVe 在 longform QA 上 factuality +23%，在 biography generation 上 -41% hallucination rate
- 证据组织（方法分类学）：
  - A. 检索增强类：RAG, REALM, RETRO, Self-RAG (检索时机自主决策)
  - B. 验证修正类：CoVe, RARR, CRITIC (后验事实核查+修正)
  - C. 归因追踪类：AttributedQA, WebGPT (每句附来源)
  - D. 训练策略类：DPO for factuality, RLHF with factuality reward
  - 基准对比表：TruthfulQA / FActScore / FEVER / HaluEval 跨方法对比
- 合成：每类方法的优势/局限/适用场景 + 开放问题（检索噪音、延迟成本、多跳推理中的级联错误）

**产物：** `report.md`（2,500 字综述：方法分类学(4 类) / 每类代表方法 2-3 个含效果数据 / 基准对比表 / 趋势分析(Self-RAG 和归因追踪是主流方向) / 开放问题 3 个），`sources.json`（28 条去重证据，3 条携带多出处 URL），引用 [1]-[28] 每条关联具体方法或数据主张

---

### Case 4：政策影响分析（法规解读 + 厂商响应 + 矛盾解决）

```bash
python -m harness -p "欧盟 AI 法案的高风险分类如何影响在欧运营的招聘工具供应商？出现了哪些合规策略？" --output-dir ./output/
```

**行为轨迹：**
- 任务分解（利益相关者框架）：
  - 子查询 1："EU AI Act high-risk classification employment recruitment Article 6"
  - 子查询 2："HR tech AI vendor EU AI Act compliance response 2024 2025"
  - 子查询 3："AI recruitment tool bias audit conformity assessment EU requirement"
  - 子查询 4："EU AI Act transition period timeline enforcement penalties"
- Round 1（17 来源）：
  - 法规文本：Article 6(2) + Annex III 明确将"招聘和人员选拔"列为高风险
  - 大厂响应：HireVue 宣布欧洲业务增加 bias audit、SAP SuccessFactors 建立 AI 治理团队
  - 律所分析：高风险分类要求——合格评估+技术文档+人类监督+准确性指标+风险管理体系
- 缺口分析：
  - 缺少中小厂商数据——大厂有资源合规，SME 呢？
  - 过渡期截止日有矛盾信息
- Round 2（中小企业追踪）：
  - 追加查询："SME AI recruitment tool EU AI Act compliance cost burden small vendor"
  - 发现：合规成本预估 €200K-€500K/年（律所估算 [8]），部分小厂商宣布退出欧洲市场
- Round 3（矛盾解决）：
  - 矛盾：律所备忘录 [6] 声称过渡期为 24 个月（2025 年 8 月截止）
  - 欧盟委员会 FAQ [9] 提及"高风险 AI 系统 36 个月过渡期"
  - 追加查询定位法规原文 Article 83：确认高风险系统过渡期为 36 个月（2027 年 8 月）
  - 在报告中显式解决："[6] 引用的 24 个月适用于通用 AI 模型义务，高风险系统的正确过渡期为 36 个月 [14]，符合 Article 83 原文"
- 合成（区分已确认事实 vs 推测）：
  - 已确认：法规分类、合规要求清单、大厂公开响应
  - 推测性：SME 退出规模预测、长期市场集中度影响
  - 供应商策略分类：退出欧洲(2 家小厂) / 合规适应(大厂) / 合作外包(中厂委托第三方审计)

**产物：** `report.md`（1,900 字：法规背景(Article 6+Annex III) / 合规要求清单(6 项) / 供应商响应三分类(退出/适应/合作)含具体厂商名 / 合规成本估算(€200K-500K/年) / 过渡期矛盾解决(24m vs 36m→原文确认 36m) / 未解决歧义：罚金执行力度预测），`sources.json`（21 条，按类型标记：法规原文/厂商声明/律所分析/新闻报道），引用 [6] 与 [9] 矛盾在正文经 [14] 显式解决

---

### Case 5：高难度专业问答（精确答案模式 + 多跳推理 + 证据链）

```bash
python -m harness -p "In the 1890s, a French mathematician proved that the three-body problem has no general closed-form solution expressible as algebraic and transcendental functions of time. Who was this mathematician, and what specific convergence issue did he identify with the series solutions that had been proposed?" --output-dir ./output/
```

**行为轨迹：**
- 问题类型判断：封闭事实性问题（有明确答案）→ 切换至精确问答模式（非报告模式）
- 任务分解（因果推理链）：
  - 子查询 1："three-body problem no closed-form solution proof 1890s French mathematician"
  - 子查询 2："series solution three-body problem convergence divergence history"
- Round 1（定向搜索，breadth=2）：
  - 来源 [1]（数学史百科）：Henri Poincaré, 1890, memoir submitted to King Oscar II prize
  - 来源 [2]（学术论文）：Poincaré 证明了三体问题的解不能表示为时间的单值解析函数
  - 来源 [3]（教科书引用）：之前 Lindstedt 和 Delaunay 提出的级数解在一般情况下发散
- Round 2（精确细节追踪）：
  - 追加查询："Poincaré three body problem series divergence small denominators"
  - 来源 [5]：Poincaré 识别了"小分母问题"（small denominators/divisors）——当频率接近共振时，级数中的分母趋近于零导致项无界增长，使得形式级数解实际发散
  - 来源 [6]（原始论文引用）：确认是 1890 年的 memoir（非 1892 年的 Les Méthodes Nouvelles），但后者包含更完整阐述
- 答案提炼：
  - 直接答案：Henri Poincaré
  - 收敛问题：他识别出级数解中的"小分母问题"（problème des petits diviseurs）——当行星轨道频率接近有理比值（近共振条件）时，摄动级数的分母可任意接近零，导致级数发散而非收敛
  - 证据链：[1] 身份确认 + [3] 级数发散事实 + [5][6] 小分母机制细节

**产物：** `answer.json`（`{answer: "Henri Poincaré", detail: "He identified the small divisors problem...", confidence: 0.95, sources: [1,3,5,6]}`），`evidence_chain.json`（推理步骤 + 每步支撑证据），`sources.json`（6 条）

---

## 四、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 网络请求：httpx 或 aiohttp
- 搜索接口：通过 Tool 抽象定义（如 `search_web(query) -> results`），具体实现可对接任意搜索 API
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 五、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`），包括 httpx 或 aiohttp 等网络库
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`
