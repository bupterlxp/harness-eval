# Harness-Eval 评测报告

## 一、评测概述

本评测使用 Harness-Eval 框架，在 Docker 隔离环境中运行 Claude Code 智能体，基于 5 类不同领域的 prompt 自动生成完整的 agent harness 系统。每个 harness 需遵循 **H = (E, T, C, S, L, V)** 六组件形式化架构：

| 组件 | 含义 | 对应文件 |
|------|------|---------|
| **E** | Execution Loop — 状态机驱动的执行循环 | `execution.py` |
| **T** | Tool Registry — 工具注册与调用 | `tools.py` + `domain/tools.py` |
| **C** | Context Manager — 上下文管理与压缩 | `context.py` |
| **S** | State Store — 状态持久化与断点恢复 | `state.py` |
| **L** | Lifecycle Hooks — 生命周期钩子 | `lifecycle.py` |
| **V** | Evaluation Interface — 评测与轨迹记录 | `evaluation.py` |

**评测模型**：
- **Claude Opus 4.5**（`ep-gncdny-1768815379049751461`）
- **Doubao-Seed-2.0-Mini**（`ep-vhi590-1778768544402820349`）

**运行环境**：Docker 容器，每任务最长 60 分钟，通过万卿平台 API 调用模型。

---

## 二、五类 Harness 任务设计

### 1. 代码智能体 Harness（Code Agent）

**领域**：自动化代码调试与修复

**任务设计**：给定一个有 6 个 bug 的 Flask Web 服务器（`buggy_server.py`，约 150 行）和对应的测试用例（`test_server.py`），要求生成的 harness 能够：
- 通过状态机驱动 bug 发现 → 定位 → 修复 → 验证 的完整流程
- 工具集包括：代码读取、AST 分析、补丁生成、测试运行、Git 操作
- 支持修复失败时的回滚机制
- 记录每个 bug 的修复轨迹（JSONL 格式）

**关键挑战**：修复原子性（一个 bug 的修复不能引入新 bug）、多 bug 依赖分析、测试驱动的验证循环。

**样例文件**：`buggy_server.py`（含 SQL 注入、路由错误、逻辑缺陷等 6 类 bug）+ `test_server.py`

---

### 2. 数据分析智能体 Harness（Data Analysis）

**领域**：结构化数据探索与可视化报告生成

**任务设计**：给定一份 295 行的销售数据 CSV（7 个地区 × 11 种商品 × 31 天，含 8 处缺失值、9 条异常折扣、2 条异常数量），要求生成的 harness 能够：
- 执行完整的数据质量检查（缺失值、异常值检测）
- 生成 6+ 张可视化图表（趋势图、热力图、分布图等）
- 输出结构化分析报告
- 工具集包括：CSV 加载、Pandas 操作、Matplotlib 绑定、统计计算

**关键挑战**：数据清洗策略选择、异常值处理（折扣>1.0 是否为数据错误）、图表类型自动推荐。

**样例文件**：`sales_data.csv`（295 行真实分布数据）+ `analysis_spec.md`（分析规格说明）

---

### 3. 短篇小说写作 Harness（Writing）

**领域**：文学创作与风格分析

**任务设计**：给定爱伦·坡的经典短篇《The Tell-Tale Heart》作为参考文本，要求生成的 harness 能够：
- 分析参考文本的写作风格（叙事视角、节奏、意象密度等）
- 生成风格相似的原创短篇小说
- 通过多轮修订循环提升质量（初稿 → 结构修订 → 风格打磨 → 终稿）
- 输出风格对比报告（原作 vs 生成作品）

**关键挑战**：风格量化指标设计、创意生成与约束的平衡、多轮修订中的一致性维护。

**样例文件**：`the_tell_tale_heart.txt`（Poe 原文）

---

### 4. 研究智能体 Harness（Research Agent）

**领域**：深度研究与信息检索

**任务设计**：给定 5 个关于"LLM 代码生成"的研究问题（主流模型对比、关键技术进展、训练数据争议、评测基准分析、未来方向），要求生成的 harness 能够：
- 多跳检索：从初始问题出发，逐步深入相关文献
- 证据链追踪：每个结论关联到具体来源
- 生成带引用的结构化研究报告（参考 2800 字的标杆报告，含 12 篇 arXiv 引用）
- 工具集包括：Web 搜索、论文检索、内容提取、引用验证

**关键挑战**：信息可靠性判断、矛盾信息的处理、引用完整性验证。

**样例文件**：`research_questions.json`（5 个研究问题）+ `reference_report.md`（标杆报告）

---

### 5. 浏览器智能体 Harness（Browser Agent）

**领域**：浏览器自动化与多步骤 Web 任务

**任务设计**：提供一个完整的 Mock 企业 HR 管理系统（Flask 后端 + 8 个 HTML 页面 + SQLite 预置 57 名员工 + 15 条请假记录），要求生成的 harness 能够：
- 完成 12 步操作流程：登录 → 仪表盘数据提取 → 员工搜索 → 员工详情 → 请假审批（通过+拒绝）→ 提交请假表单 → 查看报表 → 导出 CSV → 生成报告
- 双层状态机：外层管理任务流程，内层管理单页面操作（导航→等待→弹窗检测→交互→提取→截图）
- 处理 3 种弹窗：Cookie consent 横幅、拒绝理由模态框、提交成功模态框
- 处理 4 种表单：登录表单、搜索框、请假表单（select/date/textarea/input）、审批按钮

**关键挑战**：弹窗非阻塞处理、跨页面 Session 维护、DOM 摘要（禁止把完整 HTML 塞进 prompt）、文件下载处理。

**样例文件**：`mock_server.py`（Flask 后端 510 行）+ 8 个 HTML 模板 + `task_scenarios.json`（12 步场景定义）

---

## 三、交互轮数与 Token 消耗

### 详细数据

| 模型 | 任务 | 交互轮数 | 输入 Tokens | 输出 Tokens | 总 Tokens |
|------|------|---------|------------|------------|----------|
| Opus 4.5 | code-agent | 99 | 3,176,500 | 42,065 | 3,218,565 |
| Opus 4.5 | data-analysis | 148 | 5,456,832 | 62,175 | 5,519,007 |
| Opus 4.5 | writing | 143 | 4,260,419 | 63,201 | 4,323,620 |
| Opus 4.5 | research-agent | 108 | 2,766,342 | 79,648 | 2,845,990 |
| Opus 4.5 | browser-agent | 103 | 3,742,198 | 65,922 | 3,808,120 |
| **Opus 合计** | | **601** | **19,402,291** | **313,011** | **19,715,302** |
| Doubao | code-agent | 152 | 4,276,750 | 20,251 | 4,297,001 |
| Doubao | data-analysis | 247 | 11,825,152 | 33,026 | 11,858,178 |
| Doubao | writing | 184 | 7,129,854 | 30,403 | 7,160,257 |
| Doubao | research-agent | 157 | 3,753,284 | 17,287 | 3,770,571 |
| Doubao | browser-agent | 124 | 3,178,152 | 19,985 | 3,198,137 |
| **Doubao 合计** | | **864** | **30,163,192** | **120,952** | **30,284,144** |

### 对比分析

| 指标 | Claude Opus 4.5 | Doubao-Seed-2.0-Mini | 差异 |
|------|-----------------|---------------------|------|
| 总交互轮数 | 601 | 864 | Doubao 多 44% |
| 平均每任务轮数 | 120.2 | 172.8 | Doubao 多 44% |
| 总 Token 消耗 | 19.7M | 30.3M | Doubao 多 54% |
| 平均输出 Token/轮 | 521 | 140 | Opus 每轮产出是 Doubao 的 3.7 倍 |
| 输出/输入比 | 1.61% | 0.40% | Opus 效率是 Doubao 的 4 倍 |

**关键发现**：
- Opus 4.5 用更少的轮数完成了相同任务，且每轮产出更多有效代码（平均 521 tokens/轮 vs 140 tokens/轮）
- Doubao 的 data-analysis 任务消耗了 11.8M tokens（247 轮），是 Opus 同任务的 2.1 倍，疑似存在大量重试和循环探索
- Doubao 的输出/输入比仅 0.40%，说明大量 tokens 花在了重复的上下文传递上，而非有效生成

---

## 四、模型完成度对比

### 总览

| 维度 | Claude Opus 4.5 | Doubao-Seed-2.0-Mini |
|------|-----------------|---------------------|
| 任务成功率 | **5/5 (100%)** | **5/5 (100%)** |
| 六组件完整率 | **5/5 全部齐全** | 4/5（browser 缺 state.py） |
| 平均 Python 文件数 | **19.4** | 15.4 |
| 平均测试文件数 | **4.6** | 2.6 |
| domain/ 子目录完整率 | **5/5** | 3/5 |
| 平均总 Token 消耗 | 3.94M | 6.04M |

### 逐任务对比

#### 1. Code Agent Harness

| | Opus 4.5 | Doubao |
|--|----------|--------|
| Python 文件数 | 18 | 17 |
| H 六组件 | 全部齐全 | 全部齐全 |
| 测试文件 | 4（状态机/回滚/原子性/e2e） | 1（仅状态机） |
| Token 消耗 | 3.22M | 4.28M |
| 特点 | 简洁清晰，dataclass schema | 额外产出 demo 脚本，测试不足 |

#### 2. Data Analysis Harness

| | Opus 4.5 | Doubao |
|--|----------|--------|
| Python 文件数 | 18 | 17 |
| H 六组件 | 全部齐全 | 全部齐全 |
| 测试文件 | 4（状态/验证/图表/e2e） | 3（单元/集成/全量） |
| Token 消耗 | 5.52M | **11.83M** |
| 特点 | **实际跑出了 6 张图表和报告** | Token 消耗异常高，疑似循环 |

#### 3. Writing Harness

| | Opus 4.5 | Doubao |
|--|----------|--------|
| Python 文件数 | 21 | 17 |
| H 六组件 | 全部齐全 | 全部齐全 |
| 测试文件 | 5（状态机/恢复/钩子/一致性/e2e） | 1（仅综合测试） |
| Token 消耗 | 4.32M | 7.13M |
| 特点 | 测试覆盖最全，有 `__main__.py` 入口 | 产出 4 份 Markdown 报告，测试薄弱 |

#### 4. Research Agent Harness

| | Opus 4.5 | Doubao |
|--|----------|--------|
| Python 文件数 | 18 | 12 |
| H 六组件 | 全部齐全 | 全部齐全 |
| 测试文件 | 4（多跳/引用/证据/e2e） | 2（执行流/综合） |
| Token 消耗 | 2.85M | 3.75M |
| 特点 | 最佳项目结构（pyproject.toml） | domain/ 目录为空壳 |

#### 5. Browser Agent Harness

| | Opus 4.5 | Doubao |
|--|----------|--------|
| Python 文件数 | 22 | 16 |
| H 六组件 | **全部齐全** | **缺 state.py** |
| 测试文件 | 6（双状态机/重试/跨页/弹窗/表单/e2e） | 6（同上） |
| Token 消耗 | 3.81M | 3.18M |
| 特点 | 组件最全，async 架构，含 popup.py | 状态管理未独立分离 |

---

## 五、关键发现

### Opus 4.5 的优势

1. **架构完整性高**：5 个 harness 全部实现了完整的 H=(E,T,C,S,L,V) 六组件分离，domain/ 子目录均有实质内容
2. **测试覆盖好**：平均 4.6 个测试文件，覆盖状态机、回滚、跨模块集成、端到端等维度
3. **Token 效率高**：平均消耗 3.94M tokens，比 Doubao 低 35%，说明规划能力更强，减少了无效探索
4. **代码质量稳定**：使用 dataclass/TypedDict 类型提示，async 架构，依赖注入模式

### Doubao 的优势

1. **全部任务完成**：5/5 成功率，证明小模型也能理解并执行复杂的 harness 构建任务
2. **文档产出丰富**：多个 harness 额外生成了 COMPLETENESS_CHECK、FINAL_REPORT 等自检文档
3. **Browser Agent 测试覆盖**：尽管组件有缺失，但测试文件数量与 Opus 持平（6 个）

### Doubao 的不足

1. **组件分离不彻底**：browser-agent 缺少独立的 state.py，research-agent 的 domain/ 为空壳
2. **测试严重不足**：writing-harness 和 code-agent-harness 仅各 1 个测试文件（prompt 要求 4-5 个）
3. **Token 消耗偏高**：data-analysis 消耗 11.83M tokens（Opus 仅 5.52M），writing 消耗 7.13M（Opus 4.32M），疑似存在重试循环
4. **domain 层薄弱**：领域特定的工具和 prompt 模板不够充实

---

## 六、运行信息

- **运行时间**：2026-05-15 01:29 — 03:14（约 1 小时 45 分钟，两模型并行）
- **运行方式**：`python3 run.py config_opus45.yaml` 和 `python3 run.py config_doubao.yaml` 并行执行，各 max_concurrent=3
- **遇到的问题**：Claude Code 在容器内创建 Python venv，macOS SIP 阻止拷贝签名二进制文件。已修复 `run.py` 跳过 venv 目录
- **输出位置**：`outputs/opus45/` 和 `outputs/doubao/`
