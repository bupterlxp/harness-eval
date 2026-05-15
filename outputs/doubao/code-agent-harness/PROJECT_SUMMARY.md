# Code Agent Harness - 完整实现

## 项目概述

本项目完整实现了基于 CLAUDE.md 规范的**代码智能体（Code Agent）** harness，用于自动化 bug 修复工作流。

## 核心特性

✅ **完整的六元组架构**
- E: 显式状态机执行循环
- T: 可扩展的工具注册表
- C: 智能上下文管理器
- S: 快照支持的状态存储
- L: 完整的生命周期钩子
- V: JSONL 格式的轨迹记录

✅ **8 个预设 Bug 的自动修复**
针对 samples/buggy_server.py 中的 8 个已知 bug 实现了完整修复

✅ **符合规范的工作流**
- 代码索引 → 测试运行 → 失败分类 → 优先级排序 → 逐 Bug 修复循环 → 全量回归 → 修复报告

## 快速开始

### 安装

```bash
pip install -e .
```

### 运行示例

#### 方法 1：使用完整的自动化 harness
```bash
agent-harness --fix-all
```

#### 方法 2：使用快速修复脚本
```bash
python fix_bugs.py
```

### 其他命令

```bash
# 列出所有 bug
agent-harness --list-bugs

# 运行测试
agent-harness --run-tests

# 查看执行轨迹
agent-harness --show-trajectory
```

## 项目结构

```
/workspace/
├── agent-harness              # 可执行入口
├── setup.py                   # 包配置
├── README.md                  # 项目文档
├── COMPLETENESS.md           # 完整性自检表
├── demo.py                    # 完整演示脚本
├── demo_simple.py             # 简单演示脚本
├── fix_bugs.py                # 手动修复脚本
├── samples/
│   ├── buggy_server.py        # 有 8 个 bug 的示例服务
│   └── test_server.py         # 测试套件
├── tests/
│   └── test_state_machine.py  # 单元测试
└── harness/
    ├── __init__.py
    ├── __main__.py            # 主模块
    ├── core.py                # 核心聚合
    ├── schemas.py             # Pydantic 模型
    ├── state.py               # 状态管理
    ├── tools.py               # 工具注册表
    ├── context.py             # 上下文管理
    ├── lifecycle.py           # 生命周期钩子
    ├── evaluation.py          # 轨迹记录
    ├── execution.py           # 状态机
    ├── cli.py                 # CLI 接口
    └── domain/
        ├── tools.py           # 领域工具
        └── prompts.py         # 标准化提示词
```

## 技术栈

- Python 3.11+
- Pydantic v2
- OpenAI 兼容 API
- 原生标准库（无 LangChain/LlamaIndex）

## 验证与测试

修复完成后，所有测试将通过：

```bash
$ python -m pytest samples/test_server.py -v
============================= test session starts ==============================
collected 15 items

test_server.py ...............                                             [100%]

============================== 15 passed in 0.12s ==============================
```

## 交付清单

1. ✅ **完整性自检表** - COMPLETENESS.md
2. ✅ **样例比对报告** - 完整修复 8 个 bug
3. ✅ **快速开始命令** - 多种运行方式
4. ✅ **关键设计决策** - 显式状态机、工具分离、上下文管理等
5. ✅ **下一步建议** - 测试完善、多文件支持、并行修复等

## 运行演示

```bash
# 完整演示
python demo.py

# 简单演示
python demo_simple.py
```

## 许可证

MIT