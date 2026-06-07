# Agent Harness 通用规范

本文件为各领域 harness 的共享参考规范。每个领域的具体提示词中已包含完整的代码骨架和要求。

---

## 什么是 Harness

Harness 是一个驱动 LLM Agent 完成特定任务的执行框架，形式化为 **H = (E, T, C, S, L, V)** 六组件架构：

| 组件 | 模块名 | 职责 |
|------|--------|------|
| **E** | `execution.py` | **Execution Loop** — 状态机驱动的执行循环 |
| **T** | `tools.py` | **Tool Registry** — 工具注册与调用 |
| **C** | `context.py` | **Context Manager** — 上下文管理与压缩 |
| **S** | `state.py` | **State Store** — 状态持久化与断点恢复 |
| **L** | `lifecycle.py` | **Lifecycle Hooks** — 生命周期钩子（操作前/后、失败、超时） |
| **V** | `evaluation.py` | **Evaluation Interface** — 评测与轨迹记录 |

---

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
