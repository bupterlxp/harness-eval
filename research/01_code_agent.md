# Code Agent Harness 功能能力研究文档

> 基于 SWE-agent、Aider、OpenHands、Moatless Tools、OpenCode、mini-swe-agent 六个生产级项目的深度源码分析

---

## 一、执行循环 (Execution Loop)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 状态机驱动循环 | OpenHands | `IDLE → RUNNING → FINISHED/STUCK/ERROR/PAUSED` 枚举控制退出 |
| while-true 持续循环 | OpenCode | 每轮：获取消息 → 检查溢出 → 构建 prompt → 调用 LLM → 处理工具结果 |
| ReAct 格式循环 | SWE-agent | Thought → Action → Observation 三段式 |
| maxSteps 预算限制 | OpenCode/OpenHands | 达到上限时注入 "MAX_STEPS" prompt 要求输出总结 |
| Doom Loop 检测 | OpenCode | 连续 3 次相同 tool+params 时弹出确认 |
| Stuck 检测 | OpenHands | 5 种模式检测（重复 action、重复 error、自言自语、A-B-A-B 循环、context overflow 循环） |

### 调用 Case

```
用户: "修复 src/auth.py 中的登录 bug"
→ Agent 循环: read_file(src/auth.py) → think("问题在第23行...") → edit_file(修复) → bash("pytest tests/test_auth.py") → [测试失败] → read_file(查看错误) → edit_file(再次修复) → bash(再次测试) → [通过] → finish("已修复")
```

```
用户: "重构整个项目的日志系统"
→ Agent 进入 plan 模式 → 分析现有日志 → 输出规划 → 切换 build → 循环执行: 逐文件修改 → 测试 → 直到所有文件完成
→ maxSteps 到达75% → 注入预算警告 → Agent 优先完成核心修改
```

---

## 二、上下文/对话压缩 (Context Management)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| History Processor 管道 | SWE-agent | 可组合处理器链: LastNObservations + ClosedWindow + RemoveRegex + CacheControl |
| LLM 驱动摘要压缩 | OpenCode | 超阈值时调用 compaction agent 生成结构化摘要 (Goal/Progress/Key Decisions/Next Steps) |
| 滚动压缩 | OpenHands | `RollingCondenser` 在 token/事件数超限时用 LLM 生成摘要替换旧事件 |
| 增量更新 | OpenCode | 已有 previous-summary 时更新而非重建 |
| Repo-map (仓库索引) | Aider | PageRank + tree-sitter 生成 token 预算内的仓库结构概览 |
| Filemap (AST缩略) | SWE-agent | tree-sitter 解析，函数体 >5 行时只保留签名 |
| Observation 硬截断 | SWE-agent/OpenHands | 超 50k/100k 字符截断，完整输出保存到文件 |
| 尾部保留 | OpenCode | 保护最近 2 轮对话原文 + 最近 40K token 工具输出 |
| 分层 Chunk 预算 | Aider | system/examples/repo_map/readonly/chat_files/history/current/reminder 分层裁剪 |
| Prompt Cache | Aider/SWE-agent | Anthropic cache_control 标记 + 后台 ping 保持缓存存活 |
| 历史摘要 | Aider | done_messages 超阈值时用 weak_model 压缩旧对话 |

### 调用 Case

```
对话超过 180K token:
→ OpenCode: 自动将前面的修改历史压缩为"已完成 12 个文件重构，当前正在修复 3 个类型错误"
→ 保留最近的错误信息原文供模型继续修复
→ 注入 "Continue if you have next steps" 消息让对话无缝继续
```

```
SWE-agent 执行 30 步:
→ LastNObservations(n=5) 只保留最新 5 步 observation 原文
→ 前 25 步替换为 "Old environment output: (n lines omitted)"
→ ClosedWindowHistoryProcessor 对已被新窗口替代的旧文件视图打标
→ 有效 token 消耗从 120K 降到 40K
```

```
Aider 30 轮对话后:
→ 早期对话自动压缩为摘要
→ 当前 3 个编辑文件完整展示
→ repo-map 用 1024 token 显示仓库其余关键结构
→ 若编辑文件太多超出 context window，警告并建议 /drop
```

---

## 三、工具系统 (Tool Registry)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 统一工具注册表 | OpenCode/OpenHands | `Tool.define()` + Effect 依赖注入 / `ToolDefinition[ActionT, ObservationT]` 泛型基类 |
| JSON Schema 参数校验 | OpenCode/OpenHands | 每个工具有 Pydantic 模型或 JSON Schema 定义入参 |
| MCP 协议集成 | OpenCode | 通过 stdio/SSE/HTTP 连接外部 MCP 服务器动态注册工具 |
| 并行执行 | OpenHands | `ParallelToolExecutor` 通过 `declared_resources()` 判断资源冲突，无冲突则并行 |
| 权限控制 | OpenCode | 每个 agent 有独立 permission ruleset: allow/ask/deny 三级 + glob 路径匹配 |
| 输出截断 | OpenCode | 超过 2000 行或 50KB 写入临时文件 |
| 安全评估 | OpenHands | 每个工具调用自动注入 `security_risk` 和 `summary` 参数 |

### 标准工具清单

| 分类 | 工具 |
|------|------|
| 文件读写 | read_file, write_file, file_edit (字符串替换), apply_patch (多文件 diff) |
| 代码搜索 | grep (正则), glob (模式匹配), semantic_search (向量), find_class, find_function |
| Shell | bash (PTY模式, timeout, 输出截断) |
| Git | diff, status, commit, patch, revert, worktree |
| 代码智能 | LSP (go_to_definition, find_references, hover, diagnostics) |
| 任务管理 | todo_write, task (子 agent 委派), task_status (轮询) |
| 规划 | think (无副作用推理), plan_exit (切换到 build) |
| 网络 | web_fetch, web_search |
| 用户交互 | ask_user_question, finish |

### 调用 Case

```
Agent 需要同时编辑 3 个不同文件:
→ ParallelToolExecutor 判断无资源冲突 → 并行执行三次 file_edit
→ 如果两次编辑涉及同一文件 → 自动串行化

Agent 发现需要查数据库 schema:
→ 用户安装了 MCP database server
→ OpenCode 自动发现并注册 query_schema 工具
→ Agent 在编辑 SQL 时直接查询验证字段名正确性
```

---

## 四、代码编辑策略 (Edit Strategies)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 精确字符串替换 | OpenCode/SWE-agent | SEARCH/REPLACE 块，old_string 必须唯一匹配 |
| 9 级模糊匹配 | OpenCode | Simple → LineTrimmed → BlockAnchor → WhitespaceNormalized → IndentationFlexible → ... |
| apply_patch 格式 | OpenCode/OpenHands | 多文件 Add/Update/Delete/Move 操作 |
| whole file 格式 | Aider | 弱模型输出整个文件内容替换 |
| unified diff | Aider | 标准 unified diff 格式 |
| architect 模式 | Aider | 强模型出方案 + 编辑模型执行 |
| 编辑后自动格式化 | OpenCode | 调用 prettier/oxfmt 等 formatter |
| 编辑后 LSP 检查 | OpenCode | 每次编辑后调用 `lsp.diagnostics()` 检查并反馈错误 |
| Linter 验证 | SWE-agent | 编辑后运行 flake8，语法错误时回滚编辑 |
| 缩进智能修正 | Moatless | `find_match_when_ignoring_indentation()` 检测统一偏移后自动修正 |
| 文件锁 | OpenCode | 信号量锁防止并发编辑冲突 |

### 调用 Case

```
模型输出的 oldString 有轻微空白差异:
→ SimpleReplacer 失败
→ LineTrimmedReplacer 失败
→ BlockAnchorReplacer: 首尾行精确匹配 + 中间 Levenshtein 相似度 0.85 > 阈值 0.3 → 成功定位并编辑

编辑引入类型错误:
→ OpenCode: edit_file 完成 → LSP diagnostics 检测到 "Property 'foo' does not exist on type 'Bar'"
→ 追加到工具输出: "LSP errors detected, please fix:"
→ 模型下一轮自动修正

SWE-agent 编辑后 flake8 报错:
→ windowed_edit_linting 模式: 编辑直接回滚
→ 反馈: "Your proposed edit has introduced new syntax error. Changes NOT applied."
→ 模型重新生成正确编辑
```

---

## 五、错误恢复 (Error Recovery)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| API 指数退避重试 | OpenCode/OpenHands | 初始 2s, 因子 2x, 尊重 retry-after 头, 最大 30s |
| 格式错误重试 | SWE-agent | 模型输出无法解析时自动添加错误消息重新 query, 最多 3 次 |
| 工具名修复 | OpenCode | 尝试 lowercase 修复大写的工具名; 否则路由到 "invalid" 工具让模型重试 |
| Bash 语法预检 | SWE-agent | 执行前 `bash -n` 语法检查，错误不执行而是反馈给模型 |
| 上下文溢出处理 | OpenCode/OpenHands | 不重试，直接触发 compaction/condensation |
| 自动提交兜底 | SWE-agent | 致命错误退出时自动提取 git diff 作为提交 |
| Stuck 自动停止 | OpenHands | 连续 4 次相同 action+error → 状态设为 STUCK → 终止 |
| LLM 无响应恢复 | OpenHands | temperature 从 0 调为 1.0 重试 |
| 命令超时处理 | SWE-agent | 单命令超时中断 + 连续 N 次超时终止 agent |

### 调用 Case

```
Agent 执行 pip install nonexistent-package 反复失败:
→ OpenHands StuckDetector: 4 次相同 action + 相同 error
→ is_stuck() = True → 状态变 STUCK → 终止循环
→ 通知用户 "Agent 陷入了重复模式"

模型消耗了 $3 的 cost_limit:
→ OpenHands: emit ConversationErrorEvent(code="MaxIterationsReached")
→ SWE-agent: attempt_autosubmission_after_error() → git diff --cached > model.patch
→ 即使 agent 没显式 submit，已有修改也被保存
```

---

## 六、Git 集成与版本管理 (Git Integration)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 自动提交 | Aider | 每次 LLM 编辑后 auto_commit, message 由 weak_model 生成 |
| Dirty commit | Aider | 编辑前对脏文件先提交，确保可分别回滚 |
| Snapshot/Revert | OpenCode | 独立 git-dir 存储快照, 支持回退到任意消息点 |
| Worktree 隔离 | OpenCode/OpenHands | git worktree 创建独立分支工作区 |
| Patch 追踪 | Moatless | unified diff patch 跟踪所有修改, 支持 shadow mode |
| 提交前自审 | SWE-agent | 第一次 submit 展示 diff 要求自检，第二次才真正提交 |
| /undo 命令 | Aider | 只回滚由 Aider 创建的 commit |

### 调用 Case

```
用户: "撤销你刚才的改动"
→ OpenCode Revert: 找到对应消息点快照 → 计算所有后续 patch → 反向应用 → 精确恢复
→ Aider /undo: 检查 aider_commit_hashes → git checkout HEAD~1 逐文件恢复 → amend
```

---

## 七、多文件协调 / 子 Agent (Multi-file & Sub-agents)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| Task 工具委派 | OpenCode/OpenHands | 主 agent 通过 task 工具启动子 agent |
| 并行子 agent | OpenCode | "单条消息多个 tool_use" 同时启动 |
| 独立权限隔离 | OpenCode | 每个子 agent 有独立 permission ruleset |
| Agent 角色定义 | OpenCode | build(全能)/plan(只读)/explore(搜索)/scout(文档研究) |
| fork 对话 | OpenHands | 深拷贝对话状态创建分支, 子对话独立 |
| 前台/后台模式 | OpenCode | background=true 启动异步 agent + task_status 轮询 |

### 调用 Case

```
用户: "给这 5 个 API endpoint 都写单元测试"
→ 主 agent 分析后同时启动 5 个 general 子 agent
→ 每个负责一个 endpoint 测试文件
→ 各子 agent 在独立 worktree 中并行工作
→ 主 agent 通过 task_status 轮询进度
→ 全部完成后汇总结果
```

---

## 八、规划模式 (Planning)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 独立 Plan 模式 | OpenCode | 禁止编辑代码，只能分析规划，产出 .md 计划文件 |
| Plan→Build 切换 | OpenCode | plan_exit 工具 → 用户确认 → 注入计划内容 → 切换到 build agent |
| 结构化任务分解 | Moatless | CreateTasks 工具生成带优先级的子任务列表 |
| MCTS 搜索树 | Moatless | Select-Expand-Simulate-Backpropagate, 失败路径可回溯 |
| TodoWrite 进度追踪 | OpenCode | 创建 markdown checklist 追踪多步进度 |
| Strategy Template | SWE-agent | 实例模板后追加策略提示引导先思考再动手 |
| Submit Review | SWE-agent | 提交前展示 diff 要求自审 |

### 调用 Case

```
用户: "帮我规划如何把 Express 项目迁移到 Fastify"
→ Agent 进入 plan 模式 → 分析路由/中间件/数据库层
→ 产出 .opencode/plans/migration.md 结构化计划
→ 用户审阅确认 → plan_exit → 切换 build → 按步骤执行

Moatless 修复 bug:
→ 第一次修改方案测试失败 (reward=-50)
→ MCTS 回溯到修改前节点
→ 尝试另一种修复方案
→ 测试通过 (reward=+80) → 选择此路径
```

---

## 九、评估与质量保证 (Evaluation)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| Critic 评估系统 | OpenHands | CriticBase 在 FinishAction 后评估质量, 打分 < 阈值自动重试 |
| 迭代精炼 | OpenHands | success_threshold + max_iterations, 低分触发 follow-up 修正 |
| 事件持久化 | OpenHands | 每个事件序列化为 JSON 文件 (`events/000000.json`) |
| Token/Cost 追踪 | Moatless/OpenHands | 每次 LLM 调用记录 prompt_tokens/completion_tokens/cost |
| Trajectory 持久化 | Moatless | 节点树序列化为 JSON, 支持从文件恢复完整状态 |
| 测试验证完成 | Moatless | VerifiedFinish 要求提交时说明添加了哪些测试 |

### 调用 Case

```
Agent 声称完成 API 实现:
→ Critic 评分 0.4 (阈值 0.7)
→ 系统自动发送: "任务不完整(预测成功率 40%), 请检查每个需求"
→ Agent 进入第二轮迭代修正
→ 最多重试 3 次
```
