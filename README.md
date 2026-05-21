# Harness Eval

在 Docker 容器中运行 Claude Code agent，根据用户 prompt 自动生成 agent harness 代码并评估效果。

## 工作原理

1. 从 `tasks.jsonl` 读取任务——每个任务包含一段描述需要构建什么 harness 的 prompt
2. 启动 Docker 容器，内置预配置的 Claude Code + [claude-code-router](https://github.com/musistudio/claude-code-router)
3. 中间层 model-proxy 透明代理所有 LLM 请求，记录 token 用量和交互轮次
4. Agent 在隔离的 `/workspace` 目录中工作
5. 任务完成后，收集输出产物和 metrics

## 架构

```
┌─────────────────────────────────────────────────┐
│  Docker Container                                │
│                                                  │
│  Claude Code ──► model-proxy(:3457)              │
│                      │  记录 metrics.json        │
│                      ▼                           │
│               claude-code-router(:3456)          │
│                      │                           │
│                      ▼                           │
│               外部 LLM API (万卿/OpenAI/...)     │
└─────────────────────────────────────────────────┘
```

## Prompt 结构

采用 system_prompt + task_prompt 两层结构：

- `prompts/system_prompt.md` — 通用架构约束（ETCSLV 六组件），作为所有 harness 的共享规范
- `prompts/<category>_harness.md` — 每类 harness 的具体要求（功能性质、调用示例、技术栈、Dockerfile）

当前支持 5 类 harness：
| 类别 | Prompt 文件 |
|------|-------------|
| Code Agent | `prompts/code_agent_harness.md` |
| Browser Agent | `prompts/browser_agent_harness.md` |
| Data Analysis | `prompts/data_analysis_harness.md` |
| Research Agent | `prompts/research_agent_harness.md` |
| Creative Writing | `prompts/writing_harness.md` |

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install pyyaml

# 2. 从模板创建配置文件
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的 API 地址、密钥和模型名称

# 3. 运行
python3 run.py
```

## 任务格式（tasks.jsonl）

支持三种任务定义方式：

```jsonl
# 内联 prompt
{"id": "my-task", "prompt": "构建一个代码审查 harness..."}

# 从文件读取 prompt
{"id": "my-task", "prompt_file": "./prompts/my_task.md"}

# 指定目录（需包含 CLAUDE.md）
{"id": "my-task", "task_dir": "./my_task_dir"}
```

可选 `files` 字段，用于将额外参考材料拷贝到 agent 工作区：

```jsonl
{"id": "writing-harness", "prompt_file": "./prompts/writing_harness.md", "files": {"samples/example.txt": "./data/example.txt"}}
```

## 配置说明（config.yaml）

```yaml
base_url: "https://your-api-endpoint/v1"
api_key: "your-api-key"
model_name: "your-model-name"

max_concurrent: 4        # 并行容器数
timeout_minutes: 30      # 单任务超时（分钟）
output_dir: "./outputs"  # 产物输出目录
tasks_file: "./tasks.jsonl"
```

## 输出结构

```
outputs/
├── summary.json             # 汇总：total/success/failed/timeout/error 计数
└── <task-id>/
    ├── meta.json            # 任务状态 + metrics 摘要
    ├── metrics.json         # 完整请求级用量记录
    ├── claude_output.log    # Claude Code 完整输出日志
    ├── CLAUDE.md            # 使用的 prompt
    └── ...                  # agent 生成的所有文件
```

## Metrics 说明

`metrics.json` 由 model-proxy 自动生成，记录每次 LLM 请求的详细信息：

```json
{
  "total_requests": 56,
  "total_input_tokens": 781927,
  "total_output_tokens": 5186,
  "effective_requests": 22,
  "effective_input_tokens": 465460,
  "effective_output_tokens": 5186,
  "retry_requests": 34,
  "requests": [...]
}
```

| 字段 | 含义 |
|------|------|
| `total_*` | 包含所有请求（含重试）的原始计数 |
| `effective_*` | 排除重试后的有效计数（用于评估真实效率） |
| `retry_requests` | 被识别为重试的请求数 |

**重试识别规则**：HTTP 状态码 >= 400（如 429 限流），或响应中无 API 报告的 usage 且 output_tokens=0。这避免了因 API 不稳定（如豆包限流）导致的 token 统计膨胀。

## 已验证的模型

| 模型 | 端点 | 备注 |
|------|------|------|
| Claude Opus 4.5 | 万卿平台 | 稳定，极少重试 |
| Doubao-Seed-2.0-Mini | 万卿平台 | 频繁 429 限流，retry 过滤有效 |
