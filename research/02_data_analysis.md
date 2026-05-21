# Data Analysis Agent Harness 功能能力研究文档

> 基于 DB-GPT DataAnalysisPlanningAgent/DataScientistAgent 的深度源码分析

---

## 一、数据库交互 (Database Interaction)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| Schema 感知 | `RDBMSConnector.get_table_info()` 自动提取 CREATE TABLE + 样本数据行 |
| SQL 生成 | LLM 输出结构化 `SqlInput`（含 sql/display_type/thought），强制符合 dialect |
| SQL 执行 | SQLAlchemy `session.execute(text(sql))`，支持 MySQL/PostgreSQL/SQLite/DuckDB |
| 连接池管理 | pool_size/max_overflow/pool_timeout/pool_recycle/pool_pre_ping |
| DataFrame 转换 | `query_to_df()` 直接返回 pandas DataFrame |

### 调用 Case

```
用户: "上个月各区域的销售额环比增长率是多少"
→ Agent 获取数据库 schema (含 sales 表结构 + 样本行)
→ LLM 生成包含日期筛选和 LAG() 窗口函数的复杂 SQL
→ 执行 SQL → DataFrame → 选择 response_line_chart 展示
→ 输出折线图配置 (time_axis + region_series)
```

```
用户: "帮我分析客户表的数据质量"
→ Agent: SELECT COUNT(*), COUNT(DISTINCT email), COUNT(CASE WHEN phone IS NULL THEN 1 END) FROM customers
→ 输出数据完整性报告 (缺失率、重复率、异常值分布)
```

---

## 二、多轮分析 / 计划分解 (Multi-turn Analysis)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| 自动计划系统 | `PlannerAgent` 将复杂目标拆解为 `GptsPlan` 子任务 (serial_number/content/agent/rely) |
| 依赖传递 | `process_rely_message()` 自动提取依赖步骤的执行结果传递给当前 Agent |
| LOOP 模式 | `AgentRunMode.LOOP`，最多 20 轮 ReAct 动作，直到发出 Terminate 信号 |
| Dashboard 汇总 | `DashboardAssistantAgent` 从历史消息收集所有 SQL，组装多图表报告 |
| 分析框架 | MECE、金字塔原理、BCG矩阵、SWOT、帕累托、价值链 |

### 调用 Case

```
用户: "分析本季度客户流失原因并给出改进建议"
→ PlannerAgent 拆解为:
  1. 查询流失客户基础数据 (DataScientistAgent, rely=[])
  2. 按维度分析流失分布 (DataScientistAgent, rely=[1])
  3. 与留存客户对比分析 (DataScientistAgent, rely=[1,2])
  4. 生成可视化报告 (DashboardAgent, rely=[1,2,3])
  5. 总结改进建议 (SummaryAgent, rely=[1,2,3,4])
→ 后续步骤自动引用前序结果
```

```
用户: "深度分析这份 CSV 的数据特征并给出业务建议"
→ DataAnalysisPlanningAgent 进入 LOOP 模式:
  Round 1: 探索数据结构 (describe + dtypes + head)
  Round 2: 执行统计分析脚本 (均值/方差/分布)
  Round 3: 识别异常值 (IQR/Z-score)
  Round 4: 计算相关性矩阵
  Round 5: 生成可视化 (ECharts)
  Round 6: Terminate + 输出最终报告
```

---

## 三、结果验证 (Result Verification)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| 通用验证流程 | 审查通过? → Action 执行成功? → 输出非空? → correctness_check |
| SQL 执行验证 | **实际执行 SQL 验证数据非空**: `columns, values = await db.query(sql)` |
| 表创建验证 | `SELECT COUNT(*) FROM sqlite_master WHERE type='table'` 确认表存在 |
| 数据插入验证 | `SELECT COUNT(*) FROM table_name` 确认数据已插入 |
| 自动重试 | 验证失败时 fail_reason 作为 observation 传递给 LLM，最多重试 max_retry_count 次 |
| 超时保护 | max_timeout=600 秒 |

### 调用 Case

```
Agent 生成含拼写错误字段名的 SQL:
→ 执行失败: "column 'custmer_name' does not exist"
→ 错误信息自动反馈给 LLM
→ LLM 第二轮修正为 'customer_name'
→ 重新生成正确 SQL → 执行成功
```

```
Agent 查询结果为空:
→ DataScientist 校验: query 返回 0 行
→ 返回失败: "查询结果为空，可能是过滤条件不当"
→ LLM 放宽日期范围或修改 WHERE 条件
→ 重新查询获得有效数据
```

---

## 四、可视化 (Visualization)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| 8 种图表类型 | line_chart, pie_chart, table, scatter, bubble, donut, area_chart, heatmap |
| VIS 协议 | `vis-db-chart` / `vis-dashboard` 格式化为前端可渲染的配置 |
| LLM 自动选图 | 基于 SQL 语义和数据特征从支持类型中选择最合适的展示方式 |
| Dashboard 模式 | 多图表组合，每个图表独立执行 SQL 并生成参数 |
| CSV 交互分析 | ECharts + Tailwind CSS 生成直方图/散点图/箱线图/热力图/时间序列 |
| 数据流 | SQL → DataFrame → `to_json(orient="records")` → VIS 参数 → 前端渲染 |

### 调用 Case

```
用户: "各产品线的季度收入趋势"
→ LLM 生成: SELECT quarter, product_line, SUM(revenue) FROM sales GROUP BY 1,2
→ 判断为时间序列对比 → 选择 response_line_chart
→ 输出: {sql, type:"response_line_chart", title:"季度收入趋势", data:[...]}
```

```
用户: "全面分析销售数据"
→ Dashboard 模式，生成 4 个图表:
  1. 月度销售额趋势 (line_chart)
  2. 各区域销售占比 (pie_chart)
  3. 客户消费金额分布 (scatter_chart)
  4. 详细数据表格 (table)
→ 每个独立执行 SQL → 组装为 vis-dashboard 配置
```

---

## 五、错误恢复 (Error Recovery)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| SQL 执行失败恢复 | 异常捕获 → `ActionOutput(is_exe_success=False, content=f"Error:{e}")` → 反馈给 LLM |
| LLM 输出格式错误 | `_input_convert()` JSON 解析失败 → 返回格式提示要求重新输出 |
| 自动重试循环 | verify 失败 → 记录 fail_reason → 作为新 observation 发送 → 重新思考执行 |
| 上下文溢出恢复 | Layer 4 `reactive_compact` 紧急裁剪；LLM 内置 3 次自动重试 |
| 计划执行失败 | 单任务失败更新状态为 FAILED，记录 retry_times |

### 调用 Case

```
Agent 第一次生成 SQL 使用了不存在的表别名:
→ 执行错误: "ERROR 1054: Unknown column 'a.order_id'"
→ 反馈给 LLM
→ LLM 第二次修正别名引用
→ 成功执行并返回结果
```

```
对话进行到第 30 轮，上下文超限:
→ Layer 1: ObservationMicroCompact 截断旧 observation
→ Layer 2: SessionMemoryCompact 丢弃旧完整轮次
→ Layer 3: FullContextCompression 用 LLM 生成摘要替换
→ Layer 4: 若 context_too_long 错误 → reactive_compact 紧急裁剪
→ 关键发现("A地区流失率异常高于平均3倍")被长期记忆保留
```

---

## 六、记忆/上下文管理 (Memory/Context)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| 三层记忆架构 | 感官记忆(临时) → 短期记忆(buffer 5-10条) → 长期记忆(向量存储+时间衰减) |
| 四层上下文压缩 | WARNING: ObservationMicro + SessionMemory / ERROR: FullCompression / 紧急: Reactive |
| 结构化记忆片段 | question/thought/phase/action/action_input/observation 六字段 |
| 任务进度摘要 | `task_progress_summary` 始终注入每次 LLM 调用，防止 buffer 淘汰后遗忘 |
| 操作快照持久化 | 每次成功操作写入 JSON: `step_001_action_name.json` |
| 记忆恢复 | `recovering_memory()` 从历史 ActionOutput 重建 Agent 记忆 |
| 重要度评分 | `LLMImportanceScorer` + embedding 相似度检测增强 |

### 调用 Case

```
用户关闭浏览器后重新打开:
→ recovering_memory() 从历史消息恢复记忆状态
→ task_progress_summary 注入: "✅ Step 1: 数据探索完成 ✅ Step 2: 统计分析完成"
→ Agent 从 Step 3 继续，无需重复前面工作
```

```
持续 30 轮分析会话:
→ 前期探索的 SQL 日志被 Layer 1 截断
→ 前 10 轮交互被 Layer 2 丢弃
→ 但关键发现写入长期记忆
→ Agent 第 25 轮仍能准确引用第 8 轮发现进行归因分析
→ token 消耗始终控制在预算内
```

---

## 七、Agent 工作流 (Agent Workflow)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| Think-Review-Act-Verify | 加载资源→构建prompt→LLM推理 / 合规审查 / 执行Action / 验证结果 |
| 多 Agent 协作 | PlannerAgent → AutoPlanChatManager 按序选择 Agent 执行 → rely_messages 传递 |
| ReAct 循环 | Thought + Phase + Action + Action Input → Observation → 下一轮 |
| 9 种数据分析动作 | SQL查询、代码执行、统计分析、数据清洗、特征工程、可视化、报告生成等 |

### 调用 Case

```
DataAnalysisPlanningAgent ReAct 循环:
  Thought: "需要先了解数据的基本结构"
  Phase: "data_exploration"
  Action: "execute_code"
  Action Input: "import pandas as pd; df = pd.read_csv('data.csv'); print(df.info())"
  → Observation: "5 columns, 10000 rows, 2 numeric, 3 categorical"
  
  Thought: "数值列需要统计分析"
  Phase: "statistical_analysis"
  Action: "execute_code"
  Action Input: "print(df.describe())"
  → Observation: "mean=... std=... min=... max=..."
  
  ... (继续直到 Terminate)
```

---

## 八、数据导入 (Data Import)

### 核心能力

| 能力 | 实现方式 |
|------|----------|
| Excel/CSV 导入 | `ExcelTableAgent` 将文件转为 SQLite 临时表 |
| 表创建验证 | 确认表存在 + 数据行数 > 0 |
| 自动类型推断 | pandas 推断列类型后映射到 SQL 类型 |
| 数据清洗 | 处理缺失值、编码转换、格式标准化 |

### 调用 Case

```
用户上传 sales_2024.xlsx:
→ ExcelTableAgent 读取 Excel
→ 创建 SQLite 表: CREATE TABLE sales_2024 (date TEXT, region TEXT, amount REAL, ...)
→ 验证: SELECT COUNT(*) = 15000 行已插入
→ DataScientistAgent 可直接对该表执行 SQL 分析
```
