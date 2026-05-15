# Agent Harness 构建任务:短篇小说写作

你将为**短篇小说写作**领域构建一个完整的 agent harness。本提示词是你的工作 spec,定义了方法论、形式化约束、交互规范和交付标准。

---

## 一、用户输入

### 1. 功能样例(FEATURE_EXAMPLE)

样例包含三块内容,作为 harness 的**事实基准(ground truth)**。

#### 1.1 理想输入(IDEAL_INPUT)

用户在调用 harness 时提交的任务规格,形如:

```
体裁:心理惊悚 / 哥特短篇
篇幅:约 2000–2500 词(英文)
视角:第一人称不可靠叙述者
核心张力:叙述者向读者倾诉自己策划并实施的一桩谋杀,并坚称自己神志清醒
关键约束:
  - 杀机来自一个具体而非理性的执念物(如身体某部位、器官、物件)
  - 必须有"延宕铺垫(七夜窥伺)→ 第八夜爆发"的双段式时间结构
  - 杀人后必须有"看似完美的隐藏",但被一种感官信号(声/影/气味)逐渐瓦解
  - 结尾必须是叙述者在外人面前主动崩溃、自我招供
风格要求:
  - 大量破折号、感叹号、词语重复("louder, louder, louder")
  - 直接呼告读者("you fancy me mad")
  - 以听觉意象为主导(心跳、怀表、墙中虫鸣构成隐喻链)
```

#### 1.2 理想产出(IDEAL_OUTPUT)

完整范文存放在: **`./samples/the_tell_tale_heart.txt`**

> 这是 Edgar Allan Poe 的 *The Tell-Tale Heart* (1843),公有领域作品。
> 在阶段 1 开始之前,你必须先用 Read 工具完整读取这份文件,作为后续设计、实现、比对的事实基准。
> 该样例的关键属性(用于后续比对):
> - 总长度约 2200 词
> - 开篇即以呼告体奠定不可靠叙述
> - 时间结构清晰:七夜铺垫 → 第八夜行凶 → 隐藏 → 警察来访 → 心跳重现 → 招供
> - 听觉意象贯穿:墙中死表虫 → 怀表般的心跳 → 不断放大的"louder"
> - 结尾以感叹号密集的爆发性句子收束

#### 1.3 中间过程预期(EXPECTED_TRAJECTORY)

harness 在生成 IDEAL_OUTPUT 这类作品时,应当大体经历如下步骤(每一步都是 E 状态机的一个阶段、且会写入 S 与 V):

```
1. 解析任务规格 → 抽取体裁/视角/篇幅/约束/风格,落库为 task_spec
2. 构造叙述者档案 → 生成"叙述者声音样本"(50–100 词)供风格锚定
3. 生成情节纲要 → 至少包含执念物 / 触发事件 / 延宕段 / 高潮 / 隐藏 / 暴露 / 招供 七拍
4. 生成场景级大纲 → 把七拍展开为 5–10 个场景,每场景标注 POV / 时间 / 关键意象
5. 逐场景起草 → 每场景独立生成草稿,生成时必须从 C 注入"叙述者声音样本"和"已确立意象表"
6. 一致性核查 → 检查执念物指代、时间线、意象链是否前后呼应;不一致则触发局部重写
7. 风格修订 → 检查节奏/句长/标点密度,使其匹配风格要求
8. 终稿装配 → 拼接所有场景,做最后的连接句润色,输出最终全文
```

### 2. 交互形式(INTERACTION_SPEC)

与 Claude Code 一致:

- 命令行交互(CLI),支持单次任务和多轮对话两种模式
- 流式输出(token 级流式)
- 工具调用前展示意图、调用后展示结果摘要
- 危险操作(覆盖已有稿件、调用付费 LLM API、写文件到非工作目录)需人在环审批
- 支持 `/` 命令(`/clear`、`/compact`、`/resume`、`/trajectory`、`/diff`)
- 中断信号(Ctrl+C)优雅终止并保存当前场景草稿
- 退出后可通过 session id 恢复
- 额外提供 `/diff` 命令:把当前最新全稿与 `./samples/the_tell_tale_heart.txt` 做结构/风格/意象三维比对,输出报告

---

## 二、形式化基础(不可妥协)

你构建的 harness 必须严格对应 Meng et al. (2026) 提出的六元组:

**H = (E, T, C, S, L, V)**

| 符号 | 组件 | 代码层面的硬性要求 |
|------|------|---------------------|
| **E** Execution Loop | 显式状态机(用 enum 定义状态),δ 函数对所有事件含异常都有定义,满足 safety + liveness |
| **T** Tool Registry | Pydantic schema 声明 IO,注册时校验,失败有结构化异常分类 |
| **C** Context Manager | 独立模块,实现压缩 / 检索 / 优先级三接口,禁止在 E 内拼 prompt 字符串 |
| **S** State Store | commit / recover / snapshot 三个原子操作,支持崩溃恢复 |
| **L** Lifecycle Hooks | pre/post hook 总线,覆盖至少 5 类边界事件,与组件逻辑解耦 |
| **V** Evaluation Interface | 结构化 JSONL trajectory,达到 V3 级别(含中间推理、上下文快照、目标进度) |

**关键判别准则**(论文中区分 harness 与非 harness):
- E 的 `step()` 必须显式 `match` 当前 state 决定下一步,**禁止 `while True` + 一堆 if**(这是 ReAct 式非 harness 的反模式)
- E↔S(崩溃恢复)、C↔L(上下文策略钩子)、T↔V(工具轨迹)这三对耦合必须显式编码,不能藏在隐式调用里
- V 不是 logging。logging 给人看,V 给评估管线消费,两条独立路径

---

## 二·五、样例驱动的差异比对准则(贯穿全程)

`./samples/the_tell_tale_heart.txt` 中的全文是你工作的**事实基准**,不是装饰性参考。在三个阶段,你都必须把"当前设计/实现"与样例做显式比对:

| 阶段 | 比对动作 | 比对对象 |
|------|---------|---------|
| **阶段 1 设计期** | 逐项问自己:我设计的 E 状态机能否覆盖 EXPECTED_TRAJECTORY 的每一步?T 的工具集能否生成样例中那种意象链与节奏?C 的上下文类别能否承载"叙述者声音"+"已确立意象表"+"时间线"三类中间产物? | 设计草案 ↔ 样例文件 |
| **阶段 2 实现期** | 每实现一个文件,问:这块代码是为了支撑样例中的哪个特征(不可靠叙述 / 七夜延宕 / 听觉意象链 / 爆发式收束)?如果完全删掉,样例还能跑通吗? | 当前文件 ↔ 样例的具体特征 |
| **阶段 3 验证期** | 实跑 IDEAL_INPUT,把 ACTUAL_OUTPUT 与样例做结构(七拍是否齐全)/ 风格(标点密度、呼告频率、重复修辞)/ 意象(执念物→听觉信号→招供的隐喻链)三维比对 | 实跑结果 ↔ 样例 |

**核心原则**:
- **样例是合同**。harness 是否对路,不由"代码是否优雅"或"组件是否齐全"决定,而由"能否在 IDEAL_INPUT 上产出与样例对齐的作品"决定
- **差异要追溯到组件**。看到产出有差异,不要只调 prompt——先问"这是 E/T/C/S/L/V 哪个组件的设计漏洞",再修对应文件。例如:
  - 七拍缺一拍 → E 状态机漏了状态 / T 缺少"情节纲要生成器"工具
  - 风格不像 → C 没有把"叙述者声音样本"持续注入到每个场景的 prompt
  - 意象链断裂 → S 没有维护"已确立意象表",或 C 检索时未优先注入
  - 后半段重复前半段桥段 → C 的去重/压缩策略失效
- **比对要可见**。最终交付时必须附上比对报告,让用户能直接看到"哪些维度对齐了、哪些还差、为什么差"

---

## 三、工作流程(必须按此顺序执行)

### 阶段 1:理解与规划

1. **读取样例**:用 Read 工具完整读取 `./samples/the_tell_tale_heart.txt`,作为后续所有设计的事实基准
2. **解析 FEATURE_EXAMPLE**:用 3–5 句话复述你对样例任务的理解,确认核心循环、输入输出、关键中间态
3. **从样例反推架构**:基于 IDEAL_INPUT → IDEAL_OUTPUT(样例文件)→ EXPECTED_TRAJECTORY,推导出
   - E 的状态机大致需要哪些状态(尤其是七拍叙事对应的状态)
   - T 必须提供哪些工具(情节生成器 / 场景起草器 / 一致性检查器 / 风格审查器 / 意象表管理器 等),缺一个会导致样例哪部分无法生成
   - C 需要管理哪些类别的上下文(叙述者声音样本、已确立意象表、当前场景历史、整体大纲、风格锚点)
   - S 在哪些时间点必须做 snapshot(每场景写完后、风格修订前后、终稿前)
4. **领域故障分析**:列出短篇小说写作领域下 E/T/C/S/L/V 各自缺失会导致的具体故障(每条 1 句),例如:
   - E 缺失 → 写到中段陷入循环重写或无法收尾
   - T 缺失 → 没有意象表管理器,导致执念物指代漂移
   - C 缺失 → context 爆炸或叙述者声音前后割裂
   - S 缺失 → 中途崩溃后从头开始,已生成的场景丢失
   - L 缺失 → 调用付费 LLM 无审批门、无审计
   - V 缺失 → 无法对照样例做差异分析
5. **工具清单**:列出 5–8 个该领域必需的工具,标注每个工具的 IO schema 摘要和"危险等级"(safe / needs_approval)
6. **TodoWrite**:把后续实现拆成原子任务写入 todo list,每个任务对应一个文件或一组测试

阶段 1 完成后，把上述六项以摘要形式输出，然后**直接进入阶段 2**，不要等待用户确认。

### 阶段 2:实现

按以下顺序逐文件实现,每完成一个文件用 `bash` 跑一次 import 检查:

```
harness/
├── __init__.py
├── schemas.py        # 所有 Pydantic 模型(状态、事件、轨迹记录、工具 IO、task_spec、scene、imagery_entry)
├── state.py          # S: StateStore + SQLite 后端 + Snapshot
├── tools.py          # T: ToolRegistry + Tool 基类 + 异常分类
├── context.py        # C: ContextManager + 压缩/检索/优先级策略(含叙述者声音锚定)
├── lifecycle.py      # L: HookManager + 事件类型 + 审批钩子
├── evaluation.py     # V: TrajectoryRecorder(JSONL,V3 级别)
├── execution.py      # E: ExecutionLoop + State enum + 七拍叙事状态机
├── core.py           # H 类:六组件聚合,提供 run(task) 入口
├── cli.py            # 交互层:实现 INTERACTION_SPEC,含 /diff 命令
└── domain/
    ├── tools.py      # 写作专属工具(情节生成器、场景起草器、一致性检查器、风格审查器、意象表管理器、对照比对器)
    └── prompts.py    # 写作专属 prompt 模板(叙述者声音模板、场景起草模板、风格修订模板)
samples/
└── the_tell_tale_heart.txt   # IDEAL_OUTPUT 范文(用户已提供)
tests/
├── test_state_machine.py     # safety + liveness
├── test_recovery.py          # 模拟在场景 4 崩溃,验证从 snapshot 恢复后能继续生成场景 5+
├── test_hooks.py             # 验证 L 与组件逻辑解耦
├── test_imagery_consistency.py # 验证意象表能阻止指代漂移
└── test_e2e.py               # 跑通 FEATURE_EXAMPLE,生成一篇 2000+ 词的同体裁作品
example.py
README.md
```

### 阶段 3:验证与样例比对(核心环节,不可跳过)

1. 跑 `pytest`,所有用例必须通过
2. **以 IDEAL_INPUT 为输入运行 harness**,得到 ACTUAL_OUTPUT 和 ACTUAL_TRAJECTORY
3. **三维度比对差异**:
   - **结构差异**:ACTUAL_OUTPUT 是否包含 EXPECTED_TRAJECTORY 的七拍?每拍篇幅占比是否合理?(参照样例:延宕段约占 30%,行凶段约 15%,警察来访到招供约 35%)
   - **风格差异**:破折号密度、感叹号密度、呼告读者出现的次数、重复修辞("louder, louder, louder"式)出现频次,是否与样例同量级?
   - **意象差异**:ACTUAL_OUTPUT 是否建立了类似"听觉信号 → 心理崩溃"的隐喻链?执念物在全文是否前后一致?
   - **过程差异**:ACTUAL_TRAJECTORY(从 V 层 JSONL 读取) vs EXPECTED_TRAJECTORY,标记缺失/多余/顺序错乱的步骤
   - **故障行为差异**:在场景 4(行凶夜)模拟工具崩溃,确认 E↔S 恢复联动后能否仍然抵达完整结尾
4. **诊断与修正**:针对每条差异,定位是哪个组件(E/T/C/S/L/V)的问题,而非简单调 prompt
5. **迭代直到收敛**:修正后重跑步骤 2–3,直到产出和过程差异降到可接受阈值(由用户判断)。每轮迭代记录"差异 → 定位组件 → 修改文件 → 验证结果"的链路
6. 输出**完整性自检表 + 样例比对报告**,前者对照六元组逐项标注实现等级(complete / partial / stub),后者列出最终残留的差异及其原因

---

## 四、技术栈

- 使用 **Python 3.11+**,full type hints
- **LLM 调用必须使用 OpenAI 兼容接口**（`openai` Python SDK），**禁止使用 `anthropic` SDK**。配置从环境变量读取：
  - `OPENAI_BASE_URL`：API 端点地址（如 `http://127.0.0.1:3457/v1`）
  - `OPENAI_API_KEY`：API 密钥
  - `MODEL_NAME`：模型标识符
  - 调用方式：`client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])`，然后使用 `client.chat.completions.create(model=os.environ["MODEL_NAME"], ...)`
- 其余依赖(异步方案、数据校验、持久化、CLI 渲染、日志)由你根据 FEATURE_EXAMPLE 自行选择最合适的库
- **禁止**引入 LangChain / LlamaIndex / AutoGen 等重型 agent 框架——目的是让六组件清晰可见,而非被框架的抽象遮蔽

---

## 五、CLI 交互规范(实现 INTERACTION_SPEC 的具体要求)

如果用户未特殊指定,默认实现以下行为(对齐 Claude Code 体感):

1. **入口**:`python -m harness.cli` 进入 REPL,或 `python -m harness.cli "任务描述"` 单次执行
2. **流式渲染**:模型 token 流式输出,工具调用展示为可折叠块(`▼ Tool: draft_scene(scene_id=4, ...)`)
3. **审批门**:任何标记 `needs_approval=True` 的工具调用前(覆盖已有稿件 / 调用付费 API / 写非工作目录),暂停并展示参数,等用户 `y/n/edit`
4. **斜杠命令**:
   - `/clear` 清空当前会话上下文(C 重置,S 保留 snapshot)
   - `/compact` 触发 C 的压缩策略,展示压缩前后 token 数
   - `/resume <session_id>` 从 S 加载历史会话恢复
   - `/trajectory` 打印当前 V 记录的 JSONL 路径
   - `/diff` 把当前最新全稿与 `./samples/the_tell_tale_heart.txt` 做结构/风格/意象三维比对,输出 markdown 表格
5. **中断**:Ctrl+C 触发 E 的优雅终止,先 commit 当前 S 状态再退出
6. **会话 ID**:每次启动生成 UUID,所有 S 写入和 V 记录都按 session_id 分目录

---

## 六、交付清单

完成后,你的最终消息必须包含:

1. **完整性自检表**(六组件 × 实现等级 × 已知限制)
2. **样例比对报告**:三栏格式,左栏列出样例(`./samples/the_tell_tale_heart.txt`)的关键维度(七拍结构 / 风格特征 / 意象链)和 EXPECTED_TRAJECTORY 的关键步骤,中栏标注 ACTUAL 表现,右栏标注差异及定位到的组件原因
3. **快速开始**:三条命令演示如何跑通 FEATURE_EXAMPLE,并复现样例比对结果
4. **关键设计决策摘要**:列出 3–5 个你做出的非显然权衡(如 C 层选择哪种压缩策略 / S 层场景级 snapshot 频率 / 意象表用什么数据结构 / 一致性检查放在 T 还是 L),每条说明理由
5. **下一步建议**:指出当前 stub 化或 partial 的组件、未对齐的样例维度,以及生产化所需工作

---

## 七、禁止事项

- ❌ 不要省略代码("此处略"、"..."、"TODO: 用户补充")。要么完整实现,要么用 `raise NotImplementedError("明确说明缺失原因")`
- ❌ 不要把六组件糅合进一两个大类
- ❌ 不要用 `print` 替代 V 层 trajectory(可以同时用,但 V 必须独立写 JSONL)
- ❌ 不要在代码里硬编码 API key 或路径
- ❌ 不要跳过阶段 1 直接开写——领域分析的质量决定整个 harness 是否对路
- ❌ 不要把样例文件的内容硬编码进代码——始终从 `./samples/the_tell_tale_heart.txt` 读取

---

现在,请确认你已通过 Read 工具读取 `./samples/the_tell_tale_heart.txt`,然后从**阶段 1**开始。
