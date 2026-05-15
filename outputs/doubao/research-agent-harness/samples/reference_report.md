# 大语言模型在代码生成领域的最新进展与挑战

## 摘要

大语言模型（LLM）在代码生成领域取得了快速进展，从 2021 年的 Codex 到 2024–2025 年的 Claude、GPT-4o、DeepSeek-Coder-V2 等模型，HumanEval 基准得分从 28.8% 攀升至 90% 以上。本报告综述了主流代码生成模型的技术路线与基准表现，分析了训练数据的来源与版权争议，梳理了从 instruction tuning 到 repository-level context 的关键技术突破，并讨论了当前在复杂项目处理和安全性方面面临的挑战。报告基于 12 篇公开文献，力求客观呈现开源与闭源两条路线的优势与局限。

## 1. 背景与动机

代码生成是当前 AI 研究的核心方向之一。软件开发占全球 GDP 的重要份额，而开发者在编码过程中花费大量时间在重复性任务上。自动代码生成有望显著提升开发效率。

2021 年，OpenAI 发布 Codex（Chen et al., 2021），首次证明了大规模语言模型在代码生成上的可行性。此后，代码生成能力成为衡量 LLM 综合智能的重要维度——代码不仅需要语法正确，还需要逻辑严密、处理边界情况、遵循工程规范，这对模型的推理能力提出了极高要求。

## 2. 主流模型对比

截至 2025 年初，主流代码生成模型可分为闭源和开源两大阵营：

| 模型 | 开发方 | 参数量 | 开源 | HumanEval | MBPP | 特点 |
|------|--------|--------|------|-----------|------|------|
| GPT-4o | OpenAI | 未公开 | 否 | ~90% | ~87% | 多模态，支持图像到代码 |
| Claude 3.5 Sonnet | Anthropic | 未公开 | 否 | ~92% | ~89% | 长上下文（200K），强推理 |
| DeepSeek-Coder-V2 | DeepSeek | 236B (MoE) | 是 | 90.2% | 76.2% | MoE 架构，开源最强之一 |
| CodeLlama | Meta | 7B–70B | 是 | 62.2%(34B) | ~62% | 基于 Llama 2 微调 |
| StarCoder2 | BigCode | 3B–15B | 是 | 46.3%(15B) | ~65% | The Stack v2 训练 |
| Qwen2.5-Coder | 阿里 | 1.5B–32B | 是 | 65.9%(7B) | ~70% | 中英双语，长上下文 |
| CodeGemma | Google | 2B–7B | 是 | 56.1%(7B) | ~60% | 基于 Gemma，fill-in-the-middle |

注：HumanEval/MBPP 数据来自各模型官方技术报告和公开排行榜，不同评测设置（pass@1 vs pass@10、温度参数）下数值有差异，上表以 pass@1 为主。闭源模型的具体得分随版本迭代有波动。

**关键观察**：
- 闭源模型（GPT-4o、Claude）在综合能力上仍领先，但差距在缩小
- 开源模型通过 MoE 架构（DeepSeek-Coder-V2）和专业化训练数据，在特定基准上已接近闭源水平
- 小参数模型（7B 级别）在代码补全等窄任务上性价比极高

## 3. 关键技术进展

### 3.1 Instruction Tuning 与 RLHF

早期代码模型（如 Codex）仅通过代码语料预训练，生成结果常偏离用户意图。instruction tuning（Wei et al., 2022）和 RLHF（Ouyang et al., 2022）的引入使模型能理解自然语言指令并生成符合期望的代码。WizardCoder（Luo et al., 2023）通过 Evol-Instruct 方法对代码指令进行复杂度演化，在 HumanEval 上将开源模型的表现从 ~30% 提升到 57%+。

### 3.2 Fill-in-the-Middle (FIM)

传统自回归模型只能从左到右生成代码，而实际开发中大量场景需要在已有代码中间插入内容。FIM 训练策略（Bavarian et al., 2022）通过重排训练序列，使模型获得双向上下文感知能力。StarCoder（Li et al., 2023）和 CodeGemma 均采用了此策略，显著提升了代码补全的实用性。

### 3.3 Repository-Level Context

单文件代码生成已相对成熟，但真实软件开发涉及跨文件依赖、API 调用链、项目级约定。RepoCoder（Zhang et al., 2023）和 RepoFusion 等方法通过检索相关文件片段注入 context，帮助模型理解项目全局。CrossCodeEval（Ding et al., 2024）提出了跨文件代码补全基准，揭示了当前模型在此方向上的显著不足。

### 3.4 Agent 化代码生成

2024 年以来，代码生成从"单次补全"演进为"多步骤 agent"：模型可以规划任务、调用工具（运行测试、读取文件、执行 shell 命令）、根据反馈迭代修改。SWE-bench（Jimenez et al., 2024）成为衡量此能力的标准基准，要求模型解决真实 GitHub issue。SWE-Agent（Yang et al., 2024）通过设计 agent-computer interface 实现了较高的自动修复率。

## 4. 训练数据：来源与争议

### 4.1 主要数据来源

代码模型的训练数据主要包括：
- **公开代码仓库**：GitHub 公开仓库是最大来源。The Stack v2（Lozhkov et al., 2024）收集了 619 种编程语言、67.5TB 的源代码
- **编程问答**：Stack Overflow 等平台的问答对
- **技术文档**：官方文档、教程、技术博客
- **合成数据**：使用强模型生成训练样本（如 phi-1 使用 GPT-3.5 生成教科书级代码）

### 4.2 版权与许可证争议

训练数据的版权问题是当前最大的法律争议之一：

- **GitHub Copilot 集体诉讼**（2022年11月提起）：原告主张 Copilot 在生成代码时复现了 GPL 等开源许可证下的代码片段，却未遵守相应的署名和许可要求
- **The Stack 的 opt-out 机制**：BigCode 项目允许开发者申请从训练集中移除自己的代码，截至 2024 年约有 1.5 万开发者提出了 opt-out 请求
- **合理使用之争**：模型开发方主张训练属于"变革性使用"（transformative use），而批评者认为直接商业化利用代码训练成果违反了原始许可证精神

开源与闭源阵营在此问题上的立场不同：开源项目（如 StarCoder、The Stack）倾向于提供 opt-out 机制和数据透明度；闭源项目（如 Copilot、GPT-4）的训练数据来源不透明，引发了更多争议。

## 5. 当前挑战

### 5.1 复杂多文件项目

当前模型在处理跨文件依赖时仍表现不佳。SWE-bench 的结果显示，即使最强模型在真实 GitHub issue 修复上的成功率也仅在 30–50% 左右（取决于评测子集）。主要困难包括：
- 理解大型代码库的架构和约定
- 正确定位需要修改的文件和函数
- 确保修改不引入新的回归问题

### 5.2 长上下文利用效率

虽然模型的上下文窗口已扩展到 128K–200K tokens，但研究表明模型在利用长上下文时存在"中间遗忘"现象——对窗口头部和尾部的信息利用较好，中间部分容易被忽略（Liu et al., 2024）。这对需要同时参考多个文件的代码生成场景尤为不利。

### 5.3 安全性风险

代码生成模型的安全性是一个日益受到关注的问题：
- **生成不安全代码**：研究表明 LLM 生成的代码中约 25–40% 包含潜在安全漏洞（Pearce et al., 2022），包括 SQL 注入、XSS、不安全的加密实践等
- **训练数据污染**：攻击者可以通过向公开代码库注入恶意代码片段来"毒化"训练数据
- **过度信任**：开发者可能不加审查地采用 AI 生成的代码，放大了安全风险
- **CWE 覆盖不均**：模型对常见漏洞类型（如 CWE-79 XSS、CWE-89 SQL 注入）有一定意识，但对较少见的安全模式（如竞态条件、不安全的反序列化）几乎没有防护能力

SecurityEval（Siddiq et al., 2022）和 CyberSecEval（Bhatt et al., 2024）等基准正在建立标准化的安全评估框架。

### 5.4 测试生成与验证

生成代码的正确性验证仍依赖人工审查。虽然模型可以生成单元测试，但生成的测试本身也可能有错——这形成了"谁来验证验证者"的困境。

## 6. 未来方向

1. **多 agent 协作**：多个专业化 agent 分工协作（代码生成、审查、测试、部署），通过结构化通信协议协调
2. **形式化验证集成**：将类型检查、静态分析、形式化证明与生成过程集成，在生成阶段就排除安全和正确性问题
3. **个性化代码风格**：根据团队/项目的编码规范和历史代码模式进行适配
4. **端到端软件工程**：从需求理解到代码生成、测试、部署的全流程自动化
5. **可解释的代码推理**：让模型能解释其代码决策，便于开发者审查和信任建立

## 参考文献

1. Chen, M. et al. (2021). Evaluating Large Language Models Trained on Code. arXiv. https://arxiv.org/abs/2107.03374
2. Li, R. et al. (2023). StarCoder: May the source be with you! arXiv. https://arxiv.org/abs/2305.06161
3. Rozière, B. et al. (2024). Code Llama: Open Foundation Models for Code. arXiv. https://arxiv.org/abs/2308.12950
4. Luo, Z. et al. (2023). WizardCoder: Empowering Code Large Language Models with Evol-Instruct. arXiv. https://arxiv.org/abs/2306.08568
5. Zhu, Q. et al. (2024). DeepSeek-Coder-V2: Breaking the Barrier of Closed-Source Models in Code Intelligence. arXiv. https://arxiv.org/abs/2406.11931
6. Jimenez, C. E. et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? arXiv. https://arxiv.org/abs/2310.06770
7. Yang, J. et al. (2024). SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. arXiv. https://arxiv.org/abs/2405.15793
8. Lozhkov, A. et al. (2024). StarCoder 2 and The Stack v2: The Next Generation. arXiv. https://arxiv.org/abs/2402.19173
9. Pearce, H. et al. (2022). Asleep at the Keyboard? Assessing the Security of Code Generated by GitHub Copilot. IEEE S&P. https://arxiv.org/abs/2108.09293
10. Ding, Y. et al. (2024). CrossCodeEval: A Diverse and Multilingual Benchmark for Cross-File Code Completion. NeurIPS 2023. https://arxiv.org/abs/2310.11248
11. Bhatt, M. et al. (2024). CyberSecEval 2: A Wide-Ranging Cybersecurity Evaluation Suite for Large Language Models. Meta. https://arxiv.org/abs/2404.13161
12. Yang, K. et al. (2024). If LLM Is the Wizard, Then Code Is the Wand: A Survey on How Code Empowers Large Language Models to Serve as Intelligent Agents. arXiv. https://arxiv.org/abs/2401.00812
