# 研究智能体Harness

一个用于自动化学术研究和信息检索的Python智能体框架。

## 项目概述

本项目实现了一个完整的研究智能体harness，遵循CLAUDE.md中的规范，能够自动完成从问题分解、文献检索、证据提取到报告撰写的完整研究流程。

## 核心特性

- 🧠 **完整的执行状态机**: 实现了DECOMPOSE → SEARCH → EVALUATE → EXTRACT → ORGANIZE → GAP_FILL → CROSS_VALIDATE → DRAFT → CONSISTENCY_CHECK → FINALIZE的完整流程
- 🔍 **多源检索**: 支持网络搜索和网页内容提取
- 📊 **来源评估**: 自动评估来源可靠性和相关性
- 📝 **证据提取**: 使用LLM从内容中提取事实性证据
- 📚 **结构化报告**: 自动生成符合学术规范的研究报告
- 📈 **进度追踪**: 完整的轨迹记录和评估
- 🔄 **多跳检索**: 支持智能缺口填补和迭代检索

## 快速开始

### 安装依赖

```bash
pip install openai httpx
```

### 环境变量配置

```bash
export OPENAI_BASE_URL="http://127.0.0.1:3457/v1"
export OPENAI_API_KEY="your-api-key"
export MODEL_NAME="claude-3-5-sonnet-20240620"
```

### 运行示例任务

```bash
python -m harness.cli --sample
```

### 交互式模式

```bash
python -m harness.cli --interactive
```

### 自定义研究任务

```bash
python -m harness.cli --topic "你的研究主题" --questions "问题1" "问题2" "问题3"
```

## 项目结构

```
harness/
├── __init__.py
├── schemas.py        # 数据结构定义
├── state.py          # 状态管理
├── tools.py          # 工具注册表
├── context.py        # 上下文管理
├── lifecycle.py      # 生命周期钩子
├── evaluation.py     # 轨迹评估
├── execution.py      # 执行状态机
├── core.py           # 主Harness入口
├── cli.py            # 命令行界面
└── domain/
    ├── __init__.py   # 领域专用工具和提示词

samples/
└── research_questions.json  # 示例研究任务

tests/
├── test_research_harness.py   # 单元测试
└── test_execution_flow.py    # 流程测试
```

## 核心组件

### 1. 数据结构 (`schemas.py`)

定义了研究过程中的核心数据类型：
- `Source`: 表示来源文档
- `Evidence`: 提取的事实性证据
- `Citation`: 引用条目
- `Section`: 报告章节
- `ResearchQuery`: 研究查询

### 2. 状态管理 (`state.py`)

维护研究过程中的所有状态：
- `EvidenceStore`: 证据存储
- `CitationMapper`: 引用映射
- `DraftManager`: 草稿管理
- `ResearchStateStore`: 完整研究状态存储

### 3. 工具注册表 (`tools.py`)

提供各种研究工具：
- `WebSearchTool`: 网络搜索
- `PageFetcherTool`: 网页内容提取
- `SourceEvaluatorTool`: 来源评估
- `CitationFormatterTool`: 引用格式化
- `LLMClient`: LLM交互客户端

### 4. 上下文管理 (`context.py`)

管理研究过程中的上下文：
- `EvidenceContext`: 证据上下文
- `OutlineContext`: 报告大纲
- `QueryHistory`: 查询历史
- `ResearchContext`: 综合上下文

### 5. 生命周期钩子 (`lifecycle.py`)

实现研究流程中的各个生命周期钩子：
- 搜索前后处理
- 证据充分性检查
- 引用完整性验证
- 速率限制处理

### 6. 执行状态机 (`execution.py`)

实现完整的研究执行循环，包含所有状态处理逻辑。

## 支持的命令

在交互式模式下，支持以下命令：

- `new <topic>` - 创建新的研究任务
- `status` - 显示当前任务状态
- `sources` - 列出已收集的来源
- `gaps` - 显示信息缺口
- `outline` - 显示报告大纲
- `report` - 显示当前报告
- `run` - 运行研究任务
- `save <path>` - 保存研究状态
- `load <path>` - 加载研究状态
- `exit/quit` - 退出程序
- `help/?` - 显示帮助信息

## 研究流程

1. **问题分解**: 将研究问题分解为具体的搜索查询
2. **初轮检索**: 执行搜索并收集来源
3. **来源评估**: 评估每个来源的可靠性和相关性
4. **证据提取**: 从高质量来源提取事实性证据
5. **证据组织**: 将证据按章节分类
6. **缺口填补**: 识别信息缺口并执行补充检索
7. **交叉验证**: 验证关键证据的可靠性
8. **草稿撰写**: 自动撰写各章节内容
9. **一致性检查**: 验证引用完整性和内容一致性
10. **终稿输出**: 生成完整研究报告

## 示例输出

运行示例任务后，将在`output/`目录生成以下文件：
- `final_report.md`: 完整的研究报告
- `research_trajectory_*.jsonl`: 完整的执行轨迹
- `research_state.json`: 研究状态快照

## 测试

运行所有测试：

```bash
pytest tests/ -v
```

## 关键设计决策

### 1. 多跳检索限制
- 默认最大跳数: 3
- 防止无限循环，同时允许足够的迭代

### 2. 来源评估权重
- 学术论文: 5分
- 技术博客/官方文档: 4分
- 新闻报道: 3分
- 论坛讨论: 2分
- 未知来源: 1分

### 3. 证据压缩策略
- 按相关性和可靠性排序
- 自动过滤低质量来源
- 保留最相关的证据

## 技术栈

- Python 3.11+
- OpenAI兼容的LLM API
- httpx (异步HTTP客户端)
- 无LangChain/LlamaIndex/AutoGen依赖

## 许可证

MIT License