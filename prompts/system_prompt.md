# Agent Harness 通用规范（参考）

本文件为各领域 harness 的共享参考规范。每个领域的具体提示词中已包含完整的代码骨架和要求。

## 统一接口

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

## 统一输出

`result.json` 必须包含：
```json
{
    "status": "success | partial | failed",
    "trajectory": "path/to/trajectory.jsonl"
}
```

## 通用技术约束

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，环境变量配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK
- 必须提供 `Dockerfile`（基于 `python:3.11-slim`）和 `requirements.txt`
