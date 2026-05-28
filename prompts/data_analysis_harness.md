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

### Data BMK 必须满足的执行契约

这个 harness 会直接接入 MLE-Bench / DAComp 类数据任务，分数取决于真实产物而不是解释文本。必须做到：

- 支持 `--workdir`、`--work-dir`、`--workspace`，并把它作为数据和任务文件根目录；
- 支持 `--max-steps`、`--max-turns`；
- 自动发现工作目录中的 `*.csv`、`*.tsv`、`*.json`、`*.parquet`、`*.xlsx`、`*.sqlite`、`*.db`、`train*`、`test*`、`sample_submission*`、`README*`、`instructions*`；
- 所有最终产物必须写入 `--output-dir`，同时在 `result.json` 中记录绝对路径；
- 运行失败也必须写出 `result.json`、`trajectory.jsonl`、错误日志和 best-effort 报告，不能只返回异常。

### MLE-Bench 产物要求

如果发现 `sample_submission.csv` 或任务说明要求提交文件，必须：

- 读取 sample submission 的列名和行数；
- 生成同 schema 的 `submission.csv`，路径写入 `result.json.submission_path`；
- 如果模型或训练流程失败，使用可解释的 baseline 兜底，例如多数类、均值、中位数、按训练集统计填充，不能 no submission；
- 在 `REPORT.md` 中说明使用的数据、特征、模型或兜底策略。

### DAComp 产物要求

如果任务是开放式数据分析或报告生成，必须：

- 生成 `REPORT.md`，包含问题理解、数据检查、关键计算、结论和局限；
- 至少输出一个机器可读结果文件，例如 `analysis_summary.json` 或 `metrics.csv`；
- 如果有可视化需求，图片保存到 `--output-dir` 并在报告中引用；
- `result.json` 至少包含 `report_path`、`artifacts`、`status`、`trajectory`、`error`。

对于 DAComp 信贷/经营数据类任务，`REPORT.md` 的最低可评分内容必须包括：

- 企业级指标表或汇总表：收入规模、成本/利润代理、收入稳定性、上下游集中度、作废/红冲发票比例、现有信用等级；
- 风险分层规则：至少给出 A/B/C 或 Low/Medium/High 风险分层公式或阈值；
- 授信额度分配方案：总额度必须等于题目给定预算，例如 RMB 100 million，并说明每个等级或企业的分配逻辑；
- 利率定价方案：结合 churn rate 和风险等级，给出利率区间或每档利率；
- 结论表：每个风险层的企业数量、额度占比、建议利率、预期风险说明；
- 至少一个可复查的机器可读产物，例如 `credit_allocation.csv`、`risk_scores.csv`、`analysis_summary.json`。

禁止以下低质量报告通过校验：

- 只列出发现了哪些文件；
- 只列出执行了哪些 step；
- 没有数据计算结果；
- 没有授信额度和利率规则；
- 没有把总额度约束落实到数值；
- 没有引用任何生成的表格、CSV 或图表。

如果 LLM 调用失败，允许写 `partial` 报告留痕，但 `verify_artifacts` 必须返回失败，不能把模板报告当成可提交答案。不要实现固定的“fallback flow complete”路径作为正常结束条件。

### 数据分析工具最低要求

必须实现并在执行循环中真实使用以下工具，不能只声明名字：

- 文件发现和 schema 摘要工具；
- Python 代码执行工具，带超时、异常捕获和 stdout/stderr 记录；
- dataframe 摘要工具，禁止把完整大表塞进 prompt；
- 报告/CSV/图片写入工具；
- 产物校验工具，结束前检查提交文件或报告是否存在。

---

## 二、功能性质

一个成熟的数据分析 harness 运行为有状态的 Plan-Code-Observe 执行循环，在持久化的 Python 命名空间中迭代完成分析任务。

**执行循环与计划分解。** 接收自然语言分析需求后，首先将复杂目标拆解为带依赖关系的子任务序列（如：数据探索 → 统计分析 → 对比检验 → 可视化 → 报告生成），后续步骤自动继承前序步骤的执行结果。核心循环遵循 ReAct 模式：LLM 生成 Thought（分析推理）+ Action（可执行 Python/SQL 代码）→ 执行器运行代码 → Observation（输出/错误/图表）→ 下一轮决策。支持 LOOP 模式运行最多 20 轮自主分析，直到发出 Terminate 信号。提供多种分析框架模板（MECE、金字塔原理、BCG 矩阵、帕累托、SWOT）指导系统化分析思路。

**有状态执行环境。** 维护共享的 Python 命名空间——所有变量、DataFrame、中间计算结果在步骤间持久化于同一进程。后续代码可按名称引用任何先前产物，无需重复加载或计算。代码在带超时和内存限制的沙箱中执行，防止无限循环或内存溢出。中间结果被注册到产物表中（记录 shape、dtypes、列摘要、图表路径），以压缩摘要形式注入上下文——绝不注入原始大规模数据。

**数据库交互。** 自动提取数据库 Schema（CREATE TABLE 语句 + 样本数据行）供 LLM 理解数据结构。LLM 输出结构化 SQL 请求（含 SQL 语句、展示类型选择、推理过程），harness 通过连接池执行并返回 DataFrame。支持 MySQL/PostgreSQL/SQLite/DuckDB 多种方言，自动适配 SQL 语法。

**数据导入与预处理。** 自动发现工作目录中的数据文件（CSV/Excel/Parquet/JSON），推断列类型后加载为 DataFrame 或导入为临时数据库表。处理编码转换、缺失值识别、日期格式标准化等预处理步骤。导入后验证表存在且数据行数 > 0。

**可视化生成。** 支持 8+ 种图表类型（折线图、饼图、散点图、气泡图、环形图、面积图、热力图、表格），LLM 根据数据语义和分析目标自动选择最合适的展示方式。支持 Dashboard 模式：多图表组合，每个图表独立生成数据查询和渲染参数，组装为综合报告。生成的图表保存为图片文件并记录路径供报告引用。

**结果验证与自动修复。** 分层验证机制：代码执行前做语法检查，执行时捕获异常（SQL 字段名错误、类型不匹配、空结果集），执行后做输出合理性检查（如结果为空则放宽条件重查）。验证失败时将完整错误信息作为 observation 反馈给 LLM，自动重试最多 N 次。对生成的查询做语义一致性检查——确保聚合粒度、时间范围与用户意图一致。

**上下文管理与记忆。** 四层上下文压缩：Level 1 截断旧步骤 observation → Level 2 丢弃旧完整轮次 → Level 3 用 LLM 生成摘要替换历史 → Level 4 紧急裁剪应对 context_too_long 错误。任务进度摘要（已完成步骤列表）始终注入每次 LLM 调用，防止压缩后遗忘关键发现。支持会话暂停-恢复：状态快照按线程 ID 索引，可从中断点继续分析。关键发现写入长期记忆，即使对话历史被压缩仍可引用。

**多 Agent 协作。** 复杂任务可分配给专门 Agent：PlannerAgent 拆解计划、DataScientistAgent 执行分析、DashboardAgent 组装多图表报告、SummaryAgent 生成结论。Agent 间通过依赖消息传递结果，支持 DAG 式编排（无依赖任务并行执行，有依赖任务等待前驱完成）。

**数据工程与 Pipeline 构建。** 除开放式分析外，还支持仓库级数据工程任务：基于业务需求在已有代码仓库中构建多阶段数据处理管线。典型工作涉及 30+ 文件、2000+ 行 SQL/Python 代码的创建或修改，分层组织为 staging（数据清洗：有效性/一致性/完整性/异常检测）→ core（业务逻辑：实体整合/维度建模/复杂计算）→ mart（指标聚合：面向特定分析主题的宽表输出）。harness 需要理解跨文件依赖关系（上游表变更级联影响下游），管理 pipeline DAG 中节点的执行顺序，并在已有工程系统上进行演进式修改（新增需求不破坏已有管线）。代码导航通过文件树扫描和 grep 搜索定位目标文件，编辑策略与代码智能体一致（精确字符串替换 + 先读后写 + 自动验证）。

---

## 三、调用示例

### Case 1：电商用户群留存分析（多轮迭代 + 下钻归因）

```bash
python -m harness -p "分析 orders.csv 的月度用户群留存率，找出 3 月留存最差的获客群并分析原因" --output-dir ./output/
```

数据：`orders.csv`（列：`order_id, customer_id, order_date, revenue, product_category, acquisition_channel`）

**行为轨迹：**
- Round 1（数据探索）：
  - Thought: "先了解数据基本结构和时间范围"
  - Action: `df = pd.read_csv('orders.csv', parse_dates=['order_date']); print(df.shape, df.dtypes, df['order_date'].agg(['min','max']))`
  - Observation: 84,302 行 x 6 列，日期范围 2022-01 至 2024-06
- Round 2（Cohort 构建）：
  - Thought: "按首单月分组构建留存矩阵"
  - Action: 按 customer_id 计算首单月分组 → 构建 cohort×month 透视表 → 计算留存率
  - Observation: 30 个月度 cohort，留存率矩阵 30x30
- Round 3（异常检测）：
  - Thought: "扫描留存矩阵寻找异常低值"
  - Action: 计算各 cohort 第 3 月留存，对比总体均值
  - Observation: 2023-03 cohort 第 3 月留存 8% vs 平均 18%，z-score = -3.2，标记为显著异常
- Round 4（多维度下钻）：
  - Thought: "按获客渠道和产品品类拆分 2023-03 群体，找出驱动因素"
  - Action: 对 2023-03 cohort 按 `acquisition_channel` 分组计算留存 + 卡方检验
  - Observation: paid_social 渠道留存仅 3%（其余渠道 12-15%），χ²=847.3, p < 0.001
- Round 5（根因确认）：
  - Thought: "检查 paid_social 用户的购买行为模式"
  - Action: 对比 paid_social vs organic 用户的首单折扣率、复购间隔、客单价
  - Observation: paid_social 用户 92% 使用了 50% off 折扣码，平均客单价仅 $12（organic $48），典型一次性折扣买家行为
- Round 6（可视化 + 报告）：
  - Action: 生成留存热力图 + 渠道对比柱状图 + 撰写报告
  - Terminate

**产物：** `cohort_heatmap.png`（留存热力图含异常标注），`channel_breakdown.png`（渠道留存对比），`REPORT.md`（叙述：3 月留存下降归因于 paid_social 渠道投放策略吸引了一次性折扣买家 + 统计检验结果 + 建议调整投放定向）

---

### Case 2：传感器异常检测与表征（统计方法 + 聚类 + 因果关联）

```bash
python -m harness -p "检测 sensor_data.parquet 中的异常读数，分类异常类型并量化其对停机时间的影响" --output-dir ./output/
```

数据：`sensor_data.parquet`（列：`timestamp, sensor_id, temperature, vibration, pressure, machine_state, downtime_hours`）

**行为轨迹：**
- Round 1（数据概览）：
  - Action: 加载 parquet，`df.describe()` + 缺失值检查 + 时间范围
  - Observation: 2.1M 行，48 个传感器，365 天数据，temperature 范围 [15, 420]——420°C 超物理边界
- Round 2（异常标记）：
  - Thought: "使用滚动 z-score 检测逐点异常，同时用 IQR 交叉验证"
  - Action: 对每个传感器分别计算 rolling z-score(window=60)，标记 |z| > 3.5；IQR 方法标记 Q1-3*IQR 以下或 Q3+3*IQR 以上
  - Observation: z-score 标记 1,247 行，IQR 标记 1,089 行，交集 983 行（高置信异常）
- Round 3（异常分类）：
  - Action: 对异常点用 DBSCAN 聚类（特征：temperature, vibration, pressure 归一化），eps=0.5, min_samples=10
  - Observation: 3 个聚类——Cluster 0: 高温+低振动（热冲击），Cluster 1: 正常温+高振动（机械振动爆发），Cluster 2: 压力骤降+温度微升
- Round 4（影响量化）：
  - Thought: "将异常聚类与后续 24h 内的停机事件关联"
  - Action: 对每次异常事件，查找其后 24h 内是否发生 downtime > 0 的事件，计算关联率和总停机时长
  - Observation: Cluster 0（热冲击）→ 68% 关联停机，平均 4.2h/次；Cluster 1 → 23% 关联，1.1h/次；Cluster 2 → 45% 关联，2.8h/次
- Round 5（可视化 + 报告）：
  - Action: 生成时序叠加图（异常点标红）+ 聚类 3D 散点图 + 停机影响柱状图
  - Terminate

**产物：** `anomaly_timeseries.png`，`cluster_scatter.png`，`impact_summary.png`，`anomaly_stats.csv`（每类统计：频次/关联停机率/平均停机时长/总影响），`REPORT.md`（异常分类体系 + 影响量化 + 优先处理建议：热冲击异常应设 pre-alarm 在 z>2.5 时触发预防性维护）

---

### Case 3：A/B 测试统计评估（多指标 + 新奇效应 + Power 分析）

```bash
python -m harness -p "评估 experiment_results.csv 中的 A/B 测试，判断 variant B 在转化率和人均收入上是否显著优于对照组，检查新奇效应" --output-dir ./output/
```

数据：`experiment_results.csv`（列：`user_id, variant, signup_date, converted, revenue, session_count, days_in_experiment`）

**行为轨迹：**
- Round 1（数据质量 + 均衡检查）：
  - Action: 加载数据，检查样本量、缺失值、variant 分配比例、卡方检验确认分组均衡
  - Observation: 52,411 行，control 26,180 / variant_B 26,231（比例 49.95%:50.05%），卡方 p=0.87 均衡
- Round 2（主效应检验——转化率）：
  - Action: 计算转化率 control 3.2% vs variant_B 4.1%，双比例 z 检验
  - Observation: z=5.34, p < 0.001, 95% CI for lift [0.6%, 1.2%]，效应显著
- Round 3（主效应检验——收入）：
  - Thought: "收入数据通常重尾非正态，先检验分布"
  - Action: Shapiro-Wilk 正态性检验 → 确认非正态(p<0.001) → Mann-Whitney U 检验 → Bootstrap 95% CI
  - Observation: U 检验 p=0.003 显著，中位数 lift $0.42，Bootstrap CI [$0.18, $0.71]
- Round 4（新奇效应检查）：
  - Thought: "按实验天数分段检查效果是否衰减"
  - Action: 按 days_in_experiment 分为 Week 1 (1-7) / Week 2+ (8+)，分别计算 lift
  - Observation: Week 1 lift 1.4%, Week 2+ lift 0.7%——衰减 50%，新奇效应存在
- Round 5（Power 分析 + 结论）：
  - Action: 基于观测效应量计算 achieved power；综合所有检验结果
  - Observation: Power = 0.96，样本量充足
  - Terminate with report

**产物：** `conversion_funnel.png`，`novelty_decay.png`（每日转化率趋势含 95% CI band），`revenue_distribution.png`（双组箱线图+violin），`REPORT.md`（go/conditional-go 建议：效果显著但存在新奇效应衰减，建议延长实验至 4 周后重新评估稳态效果）

---

### Case 4：多文件销售预测（特征工程 + 时间序列 + 不确定性量化）

```bash
python -m harness -p "基于 sales_history.csv 和 promotions.csv 为每个品类构建 90 天销量预测，量化预测不确定性，标记促销提升显著的品类" --output-dir ./output/
```

数据：`sales_history.csv`（`date, product_category, units_sold, price, store_id`）+ `promotions.csv`（`promo_id, product_category, start_date, end_date, discount_pct`）

**行为轨迹：**
- Round 1（数据加载 + 合并）：
  - Action: 加载两文件，按品类+日期区间合并创建 `is_promo` 和 `discount_pct` 特征，聚合为日品类级汇总
  - Observation: 1,095 天 x 8 品类，促销覆盖率 12-28% 不等
- Round 2（时序分解 + 特征工程）：
  - Action: 对每品类做 `seasonal_decompose(period=7)` 分解趋势/周季节性/残差；创建 weekday、month、holiday 特征
  - Observation: 明显周季节性（周末高峰），Electronics 有上升趋势，Food 平稳
- Round 3（模型拟合 + 预测）：
  - Thought: "Holt-Winters 适合有季节性的序列，加入促销作为外生变量"
  - Action: 拟合 Holt-Winters(seasonal=7) + 促销哑变量外生回归，生成 90 天预测含 80%/95% 预测区间
  - Observation: 8 品类模型均已拟合，in-sample MAPE 范围 4.2%-11.7%
- Round 4（促销效果检验）：
  - Action: 对每品类的促销系数做 t 检验，计算促销期间提升百分比
  - Observation: 3/8 品类显著(p<0.05)——Electronics +23%, Beauty +18%, Sports +12%；其余不显著
- Round 5（模型诊断 + 输出）：
  - Action: 计算 holdout MAPE（留最后 30 天验证）、残差自相关检验(Ljung-Box)，生成预测图和汇总表
  - Observation: holdout MAPE 5.1%-13.4%，残差无显著自相关（所有 p>0.05）
  - Terminate

**产物：** `forecast_{category}.png`（x8，含 80%/95% 置信带 + 促销期间标注），`promotion_lift.png`（品类×促销效果条形图），`forecast_summary.csv`（每品类 90 天预测值 + 上下界），`REPORT.md`（方法论：Holt-Winters + 外生回归 / 预测结果叙述 / 促销效果排名 / 模型诊断指标 / 建议：Electronics 和 Beauty 品类应增加促销频率）

---

### Case 5：数据工程——多层 Pipeline 构建（仓库级代码编排 + 分层建模 + 级联验证）

```bash
python -m harness -p "基于业务需求文档 requirements.md，在已有数据仓库项目中新增'用户生命周期价值(LTV)'主题域。需要构建完整的 staging→core→mart 三层 pipeline，输出 mart_user_ltv 宽表供 BI 团队使用" --output-dir ./output/
```

环境：已有 dbt 风格数据仓库项目，含 32 张源表（平均 412 列），目录结构 `models/staging/`, `models/core/`, `models/mart/`, `tests/`, `macros/`

**行为轨迹：**
- Round 1（需求理解 + 仓库探索）：
  - Action: 读取 `requirements.md`，扫描项目文件树结构，读取 `schema.yml` 理解已有表关系
  - Observation: 需求要求计算用户级 LTV（= 历史总收入 + 预测未来 12 月收入），需整合 `raw_orders`, `raw_payments`, `raw_subscriptions`, `raw_refunds` 四张源表，输出含 30+ 字段的宽表
  - 已有项目结构：staging 层已有 `stg_orders.sql` 和 `stg_payments.sql`，但缺少 subscriptions 和 refunds 的 staging

- Round 2（Staging 层——数据清洗）：
  - Thought: "先补全缺失的 staging 模型，再构建 core 层整合"
  - Action: 新建 `models/staging/stg_subscriptions.sql`——
    - 清洗：过滤无效 subscription_id（NULL 或负数）、标准化日期格式、去重（按 subscription_id 取最新记录）
    - 类型转换：将 `amount_cents` 转为 `amount_dollars`
  - Action: 新建 `models/staging/stg_refunds.sql`——
    - 清洗：关联验证（refund.order_id 必须存在于 orders 表）、异常值检测（refund_amount > order_amount 标记为异常）
  - Action: 更新 `models/staging/schema.yml` 添加新模型的 column 定义和 tests

- Round 3（Core 层——业务逻辑整合）：
  - Action: 新建 `models/core/int_user_revenue_history.sql`——
    - JOIN stg_orders + stg_payments + stg_refunds，按 user_id 计算净收入时间序列
    - 窗口函数计算月度活跃标记、累计消费、平均订单间隔
  - Action: 新建 `models/core/int_user_subscription_metrics.sql`——
    - 计算 MRR、churn 日期、tenure_months、upgrade/downgrade 事件
  - Action: 新建 `models/core/int_user_ltv_prediction.sql`——
    - 基于 BG/NBD 模型参数（简化为 SQL 可计算的 recency/frequency/monetary 聚合）预测未来 12 月期望收入

- Round 4（Mart 层——指标聚合输出）：
  - Action: 新建 `models/mart/mart_user_ltv.sql`——
    - JOIN 三个 core 中间表，生成 30+ 字段宽表：
    - 用户基础属性 / 历史行为指标(total_orders, total_revenue, avg_order_value, days_since_last_order) / 订阅指标(current_plan, mrr, tenure) / LTV 预测(predicted_12m_revenue, ltv_segment) / 风险标记(churn_risk_score)
  - Action: 更新 `models/mart/schema.yml`，定义字段文档和数据质量 tests

- Round 5（验证——级联测试）：
  - Action: 新建 `tests/test_mart_user_ltv.sql`——
    - not_null tests on key columns
    - referential integrity: user_id exists in source
    - business logic validation: ltv >= 0, churn_risk between 0 and 1
  - Action: 执行 `dbt run --select +mart_user_ltv`（级联构建全部上游依赖）
  - Observation: **失败** — `int_user_revenue_history.sql` 报错：`column "payment_status" is ambiguous`（stg_orders 和 stg_payments 都有此列）
  - Action: 编辑 `int_user_revenue_history.sql`，为 JOIN 中的歧义列添加表别名前缀
  - Action: 重新执行 `dbt run`
  - Observation: 全部 6 个新模型构建成功

- Round 6（数据质量验证）：
  - Action: 执行 `dbt test --select +mart_user_ltv`
  - Observation: 14 tests passed, 0 failed
  - Action: 执行抽样查询验证输出合理性——`SELECT COUNT(*), AVG(predicted_12m_revenue), MAX(churn_risk_score) FROM mart_user_ltv`
  - Observation: 158,432 用户，平均预测收入 $342，最大风险分 0.97，合理
  - Terminate

**产物：** 新增/修改 8 个 SQL 文件（staging×2 + core×3 + mart×1 + test×1 + schema.yml×1），`trajectory.jsonl`（6 轮含 1 次 SQL 错误修复），`REPORT.md`（Pipeline 架构说明 + 字段文档 + 数据质量报告）

---

## 四、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 可用：pandas、matplotlib、seaborn、numpy、scipy、scikit-learn
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 五、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`），包括 pandas、matplotlib、seaborn、numpy、scipy 等
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`
