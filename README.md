# Harness Eval

A framework for running Claude Code agents in Docker containers to generate harness code from user prompts.

## How It Works

1. Read tasks from `tasks.jsonl` — each task contains a prompt describing what harness to build
2. Spin up Docker containers with Claude Code + [claude-code-router](https://github.com/musistudio/claude-code-router) pre-configured
3. The agent works in an isolated `/workspace` directory (no Claude Code source code)
4. After completion, collect all output artifacts from each container

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Create config.yaml from the example
cp config.yaml.example config.yaml
# Edit config.yaml with your API endpoint, key, and model name

# 3. Run
python run.py
```

## Task Format (tasks.jsonl)

Three modes for defining tasks:

```jsonl
# Inline prompt
{"id": "my-task", "prompt": "Build a code review harness that..."}

# Prompt from file
{"id": "my-task", "prompt_file": "./prompts/my_task.md"}

# Directory with CLAUDE.md and supporting files
{"id": "my-task", "task_dir": "./my_task_dir"}
```

Optional `files` field to copy extra materials into the agent workspace:

```jsonl
{"id": "writing-harness", "prompt_file": "./prompts/writing_harness.md", "files": {"samples/example.txt": "./data/example.txt"}}
```

## Configuration (config.yaml)

```yaml
base_url: "https://your-api-endpoint/v1"
api_key: "your-api-key"
model_name: "your-model-name"

max_concurrent: 4        # parallel containers
timeout_minutes: 30      # per-task timeout
output_dir: "./outputs"  # where results go
tasks_file: "./tasks.jsonl"
```

## Output

Results are saved to `./outputs/<task-id>/`:

```
outputs/
└── writing-harness/
    ├── meta.json            # status, stdout, stderr
    ├── claude_output.log    # full Claude Code output
    ├── CLAUDE.md            # the prompt that was used
    └── ...                  # all files the agent created
```
