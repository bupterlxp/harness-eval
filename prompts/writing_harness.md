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

## 三、功能性质

一个成熟的创意写作 harness 运行为分层自主管线，将种子前提转化为结构连贯的长篇手稿。它首先将概念展开为基础产物——角色注册表、世界规则圣经、主题支柱和层级大纲（幕→章→场景节拍）——然后按序生成散文，每个写作单元前注入相关记忆、写完后沉淀新事实。一致性通过持久的"正典层"强制：角色档案追踪每个实体在每个故事节点的认知状态，时间线同步并行线索，世界规则作为硬性契约在每次写入调用前被读取。风格控制通过声音指纹和语调护栏运作——在评分时评估并作为 few-shot 锚点注入。初稿完成后进入 critique-revise 循环：对抗性读者（机械模式检测器和独立 LLM 评委）标记陈词滥调、展示 vs 叙述违规、声音漂移和情节矛盾，产出优先排序的修订简报指导定向章节改写。循环持续直到改进趋于平台或评估反馈从实质性转为修饰性。对于超出上下文限制的作品，harness 维护压缩的章节摘要、实体状态投影和基于 RAG 的先前文本检索，确保第 150 章的生成与第 1 章基于相同的契约真实。

---

## 四、调用示例

### Case 1：史诗奇幻系列——卷初始化

```bash
python -m harness -p "前提：一位失势的制图师发现她画的边界能重塑现实，被曾雇佣她的帝国追杀。体裁：史诗奇幻。目标 12 万字，3 卷。第三人称有限轮换 POV。语调：抒情但推进感强，Ursula Le Guin meets Joe Abercrombie" --output-dir ./output/
```

**行为轨迹：**
- 展开前提为主设定：主角 Seren Voss（制图师，34岁，负罪感驱动弧线），反派 Chancellor Orvain，魔法系统规则（墨缚约束、地理代价机制），三卷情节脊柱含幕级转折点
- 生成卷一大纲：28 章，每章 3-5 场景节拍指定 POV 角色、地点、冲突类型和故事价值转换（如 Ch.4 Beat 2："Seren 发现她擦去的 Thornmere 地图导致小镇消失——价值转换：否认→恐惧"）
- 创建声音指纹文档，采样 Le Guin 的周期句结构和 Abercrombie 的简洁内心独白
- 初始化实体注册表：角色认知状态（Seren 知道 X，尚不知道 Y）+ 三 POV 线程的时间线同步表
- 产出就绪报告：每章预估 token 预算、RAG 索引配置、需追踪 payoff 的伏笔钩子

**产物：** `MASTER_SETTING.json`，`volume_1_outline.md`，`voice_fingerprint.md`，`entity_registry.json`，`timeline_sync.csv`

---

### Case 2：悬疑小说——中段章节生成

```bash
python -m harness -p "起草第 14 章 'The Second Witness'。POV: Detective Mara Cosgrave。节拍：[Mara 对峙证人 Yusuf Okafor 后者翻供] [Mara 注意到与法医报告矛盾的细节] [章末 Mara 手机显示被停职搭档的未接来电]" --output-dir ./output/
```

**行为轨迹：**
- 检索上下文窗口：第 13 章摘要、Mara 当前认知状态（知道仓库火灾，不知道 Yusuf 与受害者的家族关联）、Yusuf 档案、活跃情节线（7 条中 3 条标记为"14-16 章收敛"）
- 生成 3,200 字章节草稿：场景转换、对话密集的对峙、植入细节（法医时间戳矛盾）
- 机械筛查：标记一处"telling"段落和两处副词过度使用，自动内联修订
- 声音护栏评估（目标：简洁、Ellroy 式句式节奏）——评分 7.8/10，过阈值，不触发声音修订循环
- 更新实体注册表：Mara 现在知道 Yusuf 翻供；沉淀章节摘要和伏笔债务（"法医矛盾必须在 Ch.18 前解决"）

**产物：** `chapters/ch14_the_second_witness.md`，`revision_log_ch14.json`，更新的 `entity_registry.json` 和 `memory_scratchpad.json`

---

### Case 3：文学小说——全卷修订

```bash
python -m harness -p "对卷一执行对抗性修订。关注：[第 8-12 章节奏] [Elena 声音一致性] [兄弟债务支线的解决]。最多 4 轮修订" --output-dir ./output/
```

**行为轨迹：**
- 加载卷一全稿（1-24 章，~85,000 字）通过压缩摘要 + RAG 检索，构建三维度评估修订简报
- 第 1 轮：对抗性读者面板（4 人设：文学评论家、类型读者、发展编辑、连续性检查员）对三个维度逐章评分。识别 Ch.9-11 为节奏死区（平均参与度 5.2/10），两个 Elena POV 章句法模式漂移向叙述者，兄弟债务线 Ch.6 引入后到 Ch.22 无跟进
- 第 2 轮：生成定向修订——Ch.9 从 4,100 字压缩至 2,800（删冗余闪回），Ch.10 新增 400 字推进债务线，Elena 章节重新注入声音锚点（恢复其标志性断句和地中海习语）
- 第 3 轮：重评。节奏提升至 7.1，Elena 一致性 8.4，支线连续性已解决。反馈从"需要实质性重构"转为"轻微修饰建议"——检测到平台
- 在第 3 轮终止（低于 max 4），生成修订摘要含前后指标

**产物：** `revision_report_v1.md`（含逐章 delta 评分），8 个章节文件被修改，`revision_history.json`（完整 diff 日志），更新的 `voice_fingerprint.md`

---

### Case 4：连载网文——大规模连续性管理

```bash
python -m harness -p "起草第 147 章 'What the River Remembers'。系列《流浪王座》卷六。POV: Kael。约束：[必须引用 Kael 在 ch.38 对 Commander Lirien 的誓言] [河灵魔法系统：代价是记忆而非法力] [Kael 尚不知 Saya 在 ch.142 桥塌中存活]" --output-dir ./output/
```

**行为轨迹：**
- 通过 RAG 检索：ch.38 誓言场景（原始措辞）、河灵魔法规则（世界圣经）、Kael 当前认知状态（412 条已知事实，23 条显式排除含 Saya 存活）、最近 3 章摘要、卷六大纲 ch.147 节拍
- 生成 2,900 字章节：Kael 施展河灵之力代价为一段童年记忆（从 ch.12 既有背景中选取），内心独白引用誓言原文，以戏剧反讽结尾（读者知 Saya 活着，Kael 在哀悼）
- 一致性检查器验证：誓言引用匹配 ch.38 源文本，记忆代价遵循既定规则（代价与法术规模成正比，per 世界圣经 v3.2），Kael 对话不含不应知道的信息
- 沉淀至记忆便笺："Kael 已失去对姐姐名字的记忆（ch.147 法术代价）"——标记为高影响角色状态变更需后续响应
- 更新时间线：ch.147 距 ch.146 三天；Saya 时间线（并行线程）领先 5 天，按大纲预计 ch.152 收敛

**产物：** `chapters/v6_ch147_what_the_river_remembers.md`，更新的 `entity_states/kael.json`（记忆清单已修改），`continuity_check_ch147.json`（pass, 0 违规），更新的 `timeline_sync.csv`

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
