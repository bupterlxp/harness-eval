# Agent Harness 构建任务：研究智能体（Research Agent）

构建一个通用的深度研究 harness，能接受研究问题，自主完成信息检索、来源评估、证据组织和结构化报告生成。

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

## 二、功能性质

一个成熟的研究智能体 harness 接收自然语言研究问题后，自主将其分解为校准知识缺口的子问题树。它以迭代周期执行多跳检索：初始广泛搜索产出初步发现，对其分析不足之处，触发精炼的后续查询深入追踪特定线索——每个周期继承前序轮次的累积认知。证据管理通过来源追踪的摘要运作：每个检索到的文档被浓缩、标记出处（URL、标题、检索时间戳），与已有证据池去重，并按跨独立来源的证实频率评分。当来源间出现矛盾时，harness 保留竞争性主张及其各自归属而非静默丢弃少数观点，在最终合成中显式呈现分歧。报告生成是有据的：每个事实性主张映射到一个或多个编号引用，来自经验证的证据池，尾部参考文献列表提供完整源 URL。系统通过仅从实际引用的来源构建参考文献列表来强制引用一致性，消除孤立或虚假引用。可配置的深度和广度参数控制详尽覆盖与计算成本间的权衡。

---

## 三、调用示例

### Case 1：技术对比评估

```bash
python -m harness -p "对比 QuantumScape、Toyota、Samsung SDI 截至 2025 年固态电池量产就绪度，谁最接近商用 EV 部署？" --output-dir ./output/
```

**行为轨迹：**
- 分解为子查询："QuantumScape 固态电池产线时间表 2025""Toyota 全固态电池量产状态""Samsung SDI 全固态试产线产能"
- 第一轮搜索从 14 个来源提取产能里程碑、产能数据和合作伙伴公告
- 缺口分析发现 Samsung SDI 正极材料路线缺失，生成追问查询
- 检测矛盾：两来源对 QuantumScape 预估电芯成本不一致，保留双方主张标注 [3] 和 [7]
- 合成 1,800 字对比报告含公司分节和结论排名

**产物：** `report.md`（结构化报告：Introduction、公司分节、对比表、Conclusion），`sources.json`（18 条含 URL、标题、检索时间、相关性评分），内联引用 [1]-[18] 全部可解析

---

### Case 2：多跳历史因果分析

```bash
python -m harness -p "1997 年亚洲金融危机的主要因果因素是什么？IMF 条件性如何影响泰国与韩国的复苏时间线？" --output-dir ./output/
```

**行为轨迹：**
- 生成初始子问题："1997 亚洲金融危机资本流动成因""IMF 泰国 1997 结构调整条件""韩国 IMF 1998 复苏 GDP 时间线"
- 第一轮收集 22 来源含学术论文、IMF 档案、新闻回顾
- 识别缺口：泰国资本管制时间线数据不足，追加查询
- 用世界银行 GDP 恢复曲线与 IMF 项目启动日期交叉验证因果主张
- 对"V 形 vs L 形复苏"争论按各方学者归属呈现 [4], [11], [16]

**产物：** `report.md`（2,200 字，含：危机起源、IMF 条件包、对比复苏分析、史学争论），`evidence_pool.json`（26 来源分质量层），引用映射：19 条无断链

---

### Case 3：技术前沿综述

```bash
python -m harness -p "当前 RAG 系统中减少 LLM 幻觉的主流方法有哪些？总结方法、基准和报告的改进" --output-dir ./output/
```

**行为轨迹：**
- 分解为 4 个子查询跨方法、基准、归因验证、自反思
- 4 个子查询并行第一轮检索返回 31 来源（arXiv 论文、工程博客、基准排行榜）
- 提取结构化数据：方法名、指标改进、使用的基准、发表场所
- 第二跳：初始结果缺少 Chain-of-Verification 细节，追加查询
- 去重 5 个以不同名称描述同一 RARR 方法的来源，合并为单条多出处证据

**产物：** `report.md`（2,500 字综述：方法分类、基准对比表、开放问题），`sources.json`（28 条去重，3 条携带多出处 URL），引用 [1]-[28] 每条关联具体主张

---

### Case 4：政策影响分析

```bash
python -m harness -p "欧盟 AI 法案的高风险分类如何影响在欧运营的招聘工具供应商？出现了哪些合规策略？" --output-dir ./output/
```

**行为轨迹：**
- 生成子查询覆盖法规文本、供应商声明、法律分析、具体厂商响应
- 第一轮检索 17 来源：法规原文、供应商新闻稿、律所分析、新闻报道
- 检测缺口：缺少中小厂商数据，追加"SME AI 招聘工具 EU AI Act 合规成本"查询
- 第三跳：律所备忘录 [6] 与欧盟委员会 FAQ [9] 过渡期截止日矛盾，检索官方法规原文 Article 83 解决 [14]
- 合成报告区分已确认的合规行动和推测性市场预测

**产物：** `report.md`（1,900 字：法规背景、供应商响应分类(退出/适应/合作)、合规成本估算、未解决歧义），`sources.json`（21 条按类型标记），引用 [6] 与 [9] 矛盾在正文经 [14] 显式解决

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
