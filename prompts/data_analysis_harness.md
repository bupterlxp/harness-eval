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

## 二、功能性质

一个成熟的数据分析 harness 运行为有状态的执行会话，由编译后的处理节点图驱动。它维护一个共享状态对象，所有变量、DataFrame 和中间计算结果在步骤间持久化于同一线程——后续代码在相同命名空间中执行，可按名称引用任何先前产物。核心循环遵循 Plan-Code-Observe 模式：LLM 制定分析计划并分解为子任务，为当前步骤生成可执行的 Python（或 SQL），将其派发到沙箱执行器（带超时/内存限制的 Docker 容器或本地进程），然后检查 stdout、stderr、返回值和渲染的图表来决定是修正、重试还是推进。中间结果被注册到产物表中（记录 shape、dtypes、列摘要、图表路径），以压缩摘要形式注入上下文——绝不注入原始数据。多轮连续性通过双轨机制维护：对话历史提供叙事连贯性，状态快照（按线程 ID 索引）支持暂停-恢复和回滚。验证是分层的：对生成的查询做语义一致性检查，执行前做可行性评估，执行后做输出合理性检查。当执行失败或产生异常结果时，harness 重新进入生成节点而非中止，实现有界重试的自动修复循环。

---

## 三、调用示例

### Case 1：电商用户群留存分析

```bash
python -m harness -p "分析 orders.csv 的月度用户群留存率，找出 3 月留存最差的获客群并分析原因" --output-dir ./output/
```

数据：`orders.csv`（列：`order_id, customer_id, order_date, revenue, product_category, acquisition_channel`）

**行为轨迹：**
- 加载 CSV，检查 shape（84,302 行 x 6 列），运行 `df.dtypes` 和日期范围（2022-01 至 2024-06）
- 生成 cohort 分配：按 `customer_id` 首单月分组，构建 retention pivot table
- 观察到 2023-03 cohort 第 3 月留存 8% vs 平均 18%，标记异常
- 按 `acquisition_channel` 和 `product_category` 下钻 2023-03 群体，卡方检验确认差异显著（p < 0.01）
- 合成报告：将下降归因于付费社交投放吸引的一次性折扣买家

**产物：** `cohort_heatmap.png`（留存热力图），`channel_breakdown.png`（渠道对比柱状图），`REPORT.md`（叙述+统计+建议）

---

### Case 2：传感器异常检测与表征

```bash
python -m harness -p "检测 sensor_data.parquet 中的异常读数，分类异常类型并量化其对停机时间的影响" --output-dir ./output/
```

数据：`sensor_data.parquet`（列：`timestamp, sensor_id, temperature, vibration, pressure, machine_state, downtime_hours`）

**行为轨迹：**
- 加载 parquet，计算各数值列 `describe()`，识别 temperature 范围 [15, 420] 存在超物理边界异常值
- 对每个传感器应用滚动 z-score（window=60），标记 1,247 行 z > 3.5，用 IQR 方法交叉验证
- 对异常点用 DBSCAN 聚类（特征：temperature, vibration, pressure），识别 3 种模式（热冲击、振动爆发、压力骤降）
- 将异常聚类与 `downtime_hours` 关联，发现聚类 0（热冲击）占总停机时间 68%
- 生成时序叠加图和聚类散点图，输出结构化摘要

**产物：** `anomaly_timeseries.png`，`cluster_scatter.png`，`anomaly_stats.csv`（每类统计），`REPORT.md`（分类体系+影响量化+阈值建议）

---

### Case 3：A/B 测试统计评估

```bash
python -m harness -p "评估 experiment_results.csv 中的 A/B 测试，判断 variant B 在转化率和人均收入上是否显著优于对照组，检查新奇效应" --output-dir ./output/
```

数据：`experiment_results.csv`（列：`user_id, variant, signup_date, converted, revenue, session_count, days_in_experiment`）

**行为轨迹：**
- 加载（52,411 行），计算组别样本量，卡方检验确认分组均衡（p=0.87）
- 转化率：control 3.2% vs variant_B 4.1%，双比例 z 检验 z=5.34, p < 0.001，95% CI lift [0.6%, 1.2%]
- 人均收入：Shapiro-Wilk 确认非正态后用 Mann-Whitney U，显著（p=0.003），中位数 lift $0.42
- 新奇效应检查：按 `days_in_experiment` 分为第 1 周 vs 第 2 周+，发现 lift 从 1.4% 衰减到 0.7%
- Power 分析确认样本量充足（achieved power = 0.96）

**产物：** `conversion_funnel.png`，`novelty_decay.png`（每日转化率趋势），`revenue_distribution.png`，`REPORT.md`（go/no-go 建议+统计表+新奇效应警告）

---

### Case 4：多文件销售预测

```bash
python -m harness -p "基于 sales_history.csv 和 promotions.csv 为每个品类构建 90 天销量预测，量化预测不确定性，标记促销提升显著的品类" --output-dir ./output/
```

数据：`sales_history.csv`（`date, product_category, units_sold, price, store_id`）+ `promotions.csv`（`promo_id, product_category, start_date, end_date, discount_pct`）

**行为轨迹：**
- 加载两文件，按品类+日期区间合并创建 `is_promo` 特征，聚合为日品类级汇总（1,095 天 x 8 品类）
- 对每品类做 `seasonal_decompose(period=7)` 分解趋势、周季节性和残差
- 拟合 Holt-Winters（seasonal period=7）+ 促销哑变量外生回归，生成 90 天预测含 80%/95% 预测区间
- 对促销系数做 t 检验，3/8 品类显著（p < 0.05），Electronics 促销期间 +23% 提升
- 编译预测表和不确定性带，生成每品类预测图和汇总对比图

**产物：** `forecast_{category}.png`（x8，含置信带），`promotion_lift.png`，`forecast_summary.csv`，`REPORT.md`（方法论+预测叙述+促销效果排名+模型诊断 MAPE）

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
