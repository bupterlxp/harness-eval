# Writing Agent Harness 功能能力研究文档

> 基于 AutoResearchClaw（学术写作）和 webnovel-writer（长篇小说创作）的深度源码分析

---

## 一、长文规划 (Long-form Planning)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 多阶段状态机 | AutoResearchClaw | 23 阶段 Pipeline (Research Scoping → Finalization)，8 个 Phase |
| 三级递进规划 | webnovel-writer | 总纲 → 卷纲(节拍表+时间线) → 章纲(CBN/CPNs/CEN 结构化节点) |
| Outline 生成 | AutoResearchClaw | 从前序 artifact (analysis/decision/experiment_data) 构建 preamble → LLM 生成结构化 outline |
| 时间线硬约束 | webnovel-writer | 每章带时间锚点，必须单调递增(除闪回)，倒计时事件标记 D-N |
| 跨卷一致性 | webnovel-writer | 上一卷未回收伏笔强制出现在新卷规划中 |
| 章节字数目标 | AutoResearchClaw | 每节定义严格字数范围 (abstract: 180-220, method: 1000-1500) |
| Fallback 保底 | AutoResearchClaw | LLM 返回空时有 `_default_paper_outline()` 保底结构 |

### 调用 Case

```
学术论文规划:
→ Phase A-F: 文献综述/假设/实验 → 积累 artifact
→ Stage 16 (PAPER_OUTLINE): 综合所有 artifact → LLM 生成论文骨架
→ Introduction 引用文献综述结果 / Method 对应假设 / Results 展示实验数据
→ 结构: Abstract → Introduction → Related Work → Method → Experiments → Results → Conclusion
```

```
网络小说规划 (第3卷):
→ /webnovel-plan 技能启动
→ 检索第1卷未回收伏笔 ("主角身世之谜" 超40章未回收) → 标记为紧急
→ 生成卷纲: 节拍表(中段反转/危机链递增) + 时间线(D-15→D-0 倒计时)
→ 章纲: 每章 CBN(起点) + 2-4 CPNs(推进) + CEN(终点)
→ 相邻章 CEN→CBN 必须逻辑承接
```

---

## 二、记忆结构 (Memory Structure)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 三层记忆 | webnovel-writer | Working(本章即时) + Episodic(近期事件) + Semantic(全书长期) |
| 7 分桶语义记忆 | webnovel-writer | character_state/story_facts/world_rules/timeline/open_loops/reader_promises/relationships |
| 记忆去重 | webnovel-writer | 按 category 主键规则去重(如 subject+field)，旧值降级为 outdated |
| 防膨胀压缩 | webnovel-writer | >500 条触发: 同key只留最新/清理已回收伏笔/50章前timeline合并摘要 |
| 智能过滤注入 | webnovel-writer | 根据章纲内容做关键词匹配过滤 → 按预算截断 → 只注入相关记忆 |
| 三分区记忆 | AutoResearchClaw | ideation/experiment/writing 分区 JSONL 持久化 |
| 时间衰减检索 | AutoResearchClaw | `0.5*cosine_sim + 0.2*time_decay + 0.2*confidence + 0.1*access_count` |
| WritingMemory | AutoResearchClaw | 专门记录 review_feedback 和 successful_structure |
| 状态管理 | webnovel-writer | active/outdated/contradicted/tentative 四种记忆状态 |

### 调用 Case

```
写到第180章，主角需要使用第23章获得的剑:
→ Semantic memory "artifact_obtained" 事件记住剑的存在及属性
→ MemoryOrchestrator 检测到章纲提到武器名
→ 自动将相关记忆项注入任务书
→ 避免写出与之前矛盾的描述
```

```
学术写作第三次生成论文:
→ WritingMemory 检索到之前同类主题 review feedback:
  "Method section needs more formal notation" + 解决方案 "Added Eq. 1-3"
→ 自动注入写作 prompt → 避免重复犯错
```

---

## 三、风格控制 (Style Control)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 学术风格指南 | AutoResearchClaw | NeurIPS/ICLR/ICML 2024-2025 最佳论文提炼标准 |
| Anti-AI 对抗 | webnovel-writer | 8 个 LLM 写作癖好识别规则 + 5 个即时检查项 + 替代方案速查 |
| 题材裁决层 | webnovel-writer | 9 张 CSV 知识表 → 路由匹配 → 每章生成 reasoning (style_priority/pacing_strategy) |
| 反套话规则 | AutoResearchClaw | 禁止 'delves into'/'paves the way'/'paradigm shift' 等 |
| 反重复规则 | AutoResearchClaw | 每个具体数字最多出现 2 个 section |
| 叙事写作规则 | AutoResearchClaw | 强制 Topic→Evidence→Analysis→Transition 段落结构，禁正文 bullet list |
| 风格适配器 | webnovel-writer | 按题材加权 (玄幻偏动作/言情偏情绪弧/悬疑偏线索) |
| 会议模板 | AutoResearchClaw | 内置 NeurIPS/ICML/ICLR 2024-2026 完整 LaTeX 样式 |
| 项目经验积累 | webnovel-writer | 有效风格模式写入 project_memory.json (hook/pacing/dialogue/payoff) |

### 调用 Case

```
学术论文风格控制:
→ LLM 生成 "This paper delves into the realm of adaptive learning"
→ anti_hedging_rules + FORBIDDEN 列表触发
→ Revision 阶段强制 LLM 重写为精确学术表述
→ 同时 writing_structure block 确保 heading 层级正确
```

```
网络小说风格控制:
→ 审查检测到最近3章 ai_flavor issue 出现5次 ("缓缓说道"密集)
→ 写入 anti_patterns.json
→ 下次写章时任务书明确提醒: "删万能副词(缓缓/淡淡/微微)，换具体动作"
→ 并给出替代示例
```

---

## 四、批评-修改循环 (Critique-Revise Loop)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| AI Peer Review | AutoResearchClaw | Stage 18: LLM 扮演评审生成 Strengths/Weaknesses/Actionable revisions |
| 多视角辩论 | AutoResearchClaw | innovator/pragmatist/contrarian 三角色辩论 |
| Paper Revision | AutoResearchClaw | reviews + draft + metrics + quality directives → LLM 修改 |
| 长度保护 | AutoResearchClaw | 修改版短于原文 80% → 自动重试加强长度约束 → 最坏保留原文 |
| 迭代管线 | AutoResearchClaw | quality_gate < 阈值 → 自动重跑 stages 16-22 → 上轮 reviews 作为 context |
| 收敛条件 | AutoResearchClaw | 分数达标 / 连续N轮变化<0.5 / 达到最大迭代次数 |
| 六维审查 | webnovel-writer | reviewer agent 检查词汇/句式/叙事/情感/对话/AI味 6 个维度 |
| 数据完整性守卫 | AutoResearchClaw | 禁止 LLM 在响应评审时捏造新数据 |

### 调用 Case

```
论文第一轮生成后:
→ quality_gate 评分 5.2/10 (阈值 7.0)
→ 评审指出: "weak baselines, missing ablations"
→ 写入 iteration_context.json
→ 第二轮 Stage 16: 调整 outline 加强 ablation
→ Stage 17: 重新撰写 → Stage 18: 再次评审
→ 循环直到 ≥ 7.0 或达到最大迭代
```

```
小说章节审查:
→ reviewer 六维检测:
  - 词汇层: "缓缓"出现4次 → HIGH severity
  - 句式层: 连续3个"他/她+动词"结构 → MEDIUM
  - 对话层: 对白缺少潜台词 → LOW
→ HIGH/MEDIUM issue 回流到 anti_patterns.json
→ 下一章写作时 context-agent 自动加入避雷提醒
```

---

## 五、长上下文管理 (Long Context Management)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 分段写作 | AutoResearchClaw | 3 次 LLM 调用拼接完整论文 (前/中/后段) |
| 滚动 preamble | AutoResearchClaw | 所有前序阶段产物压缩为 preamble 注入当前阶段 |
| Artifact 文件系统 | AutoResearchClaw | 每阶段产物持久化到文件，后续阶段按需读取 |
| 六层主链架构 | webnovel-writer | Knowledge→Reasoning→Contract→Context→Commit→Projection |
| load-context 基础包 | webnovel-writer | 一次返回: contracts/recent_summaries/urgent_loops/active_rules/protagonist |
| 按需深查 | webnovel-writer | 基础包不足时: query-entity/query-rules/get-timeline |
| RAG 混合检索 | webnovel-writer | 向量嵌入 + BM25 + Rerank 重排序 |
| 记忆预算分配 | webnovel-writer | 按 task_type 分配 working/episodic/semantic 三层配额，总上限30条 |
| 优先级截断 | webnovel-writer | world_rule > character_state > relationship > story_fact > open_loop |

### 调用 Case

```
论文写作 Stage 17 (PAPER_DRAFT):
→ preamble 包含: 文献综述摘要 + 假设列表 + 实验数据汇总
→ 第1次调用: 写 Abstract + Introduction + Related Work
→ 第2次调用: 写 Method + Experiments (含上文作为前序)
→ 第3次调用: 写 Results + Conclusion
→ 拼接为完整论文
```

```
写第180章，需要远距离引用:
→ load-context 返回基础包 (近2章摘要 + 前3条紧急伏笔)
→ 章纲提到"玄铁剑" → 触发按需深查 query-entity("玄铁剑")
→ 从 semantic memory 检索到第23章获得事件
→ 注入上下文: "玄铁剑: 第23章从密室获得，属性:..."
→ 总 token 控制在预算内 (working 15条 + episodic 8条 + semantic 7条)
```

---

## 六、多 Rollout 质量保证 (Multi-rollout Quality)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 多视角生成 | AutoResearchClaw | 同一阶段用不同角色生成多个候选 (optimist/skeptic/methodologist) |
| 最佳选择 | AutoResearchClaw | 多候选中选择质量最高的进入下一阶段 |
| 保底机制 | AutoResearchClaw | LLM 无输出时有 default fallback |
| 迭代精炼 | AutoResearchClaw | 完整执行→评分→低分则重跑写作阶段→注入上轮feedback |
| 五投影层 | webnovel-writer | 5 个 projection writers 生成不同草稿 → 选优合并 |

### 调用 Case

```
假设生成阶段:
→ innovator: "提出激进的新方法X"
→ pragmatist: "在现有方法Y基础上改进"
→ contrarian: "质疑前提条件，探索方法Z"
→ 三个假设进入辩论 → 选择最有前景的进入实验设计
```

---

## 七、输出格式 (Output Formatting)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| LaTeX 论文 | AutoResearchClaw | Markdown → LaTeX 转换，内置会议模板 |
| APA 引用 | AutoResearchClaw | 正文行内引用 + 末尾 References 列表 |
| 章节 Markdown | webnovel-writer | 标准化章节格式输出 |
| 图表嵌入 | AutoResearchClaw | 实验数据生成图表代码，嵌入论文 |
| 元数据记录 | webnovel-writer | chapter_commit 记录: state_changes/entities_new/relationships_new |

### 调用 Case

```
论文最终输出:
→ Markdown 格式论文 → LaTeX 模板 (NeurIPS 2025 格式)
→ 每个数据点后有行内引用: ([Author, 2024](url))
→ 末尾 References 列表自动生成
→ 图表从实验数据自动生成 matplotlib/pgfplots 代码
```

```
小说每章输出:
→ 正文 (3000-5000字) + chapter_commit 元数据
→ commit 记录: state_changes=["主角突破到金丹期"]
→ entities_new=["新角色张三"] 
→ 自动更新 memory_scratchpad.json
```
