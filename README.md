# Harness Eval

在 Docker 容器中运行 Claude Code agent，根据用户 prompt 自动生成 harness 代码的框架。

## 工作原理

1. 从 `tasks.jsonl` 读取任务——每个任务包含一段描述需要构建什么 harness 的 prompt
2. 启动 Docker 容器，内置预配置的 Claude Code + [claude-code-router](https://github.com/musistudio/claude-code-router)
3. Agent 在隔离的 `/workspace` 目录中工作（不包含 Claude Code 源码）
4. 任务完成后，收集每个容器的所有输出产物

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 从模板创建配置文件
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的 API 地址、密钥和模型名称

# 3. 运行
python run.py
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

产物输出目录由 `config.yaml` 中的 `output_dir` 指定，默认为 `./outputs`。

每个任务的结果保存在 `<output_dir>/<task-id>/` 下，运行结束后还会生成一个 `summary.json` 汇总所有任务状态：

```
outputs/
├── summary.json             # 汇总：total/success/failed/timeout/error 计数
└── writing-harness/
    ├── meta.json            # 单任务状态、stdout、stderr
    ├── claude_output.log    # Claude Code 完整输出日志
    ├── CLAUDE.md            # 使用的 prompt
    └── ...                  # agent 生成的所有文件
```
