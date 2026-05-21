# Browser Agent Harness 功能能力研究文档

> 基于 browser-use 和 OpenHarness 的深度源码分析

---

## 一、多页面执行 (Multi-page Execution)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 标签页管理 | browser-use | 每个 tab 用 TargetID 后4字符标识，支持 switch/close/new_tab |
| 自动检测新 tab | browser-use | 点击链接后 `_detect_new_tab_opened` 自动切换到新标签页 |
| Tab 状态呈现 | browser-use | `BrowserStateSummary.tabs` 列表每步呈现给 LLM (URL+标题+活跃标记) |
| 并行工具执行 | OpenHarness | `asyncio.gather()` 多工具调用并发执行 |

### 调用 Case

```
用户: "在 Google 搜索三个竞品的价格并做对比"
→ Agent: navigate("google.com") 搜索竞品A → 点击结果(新标签打开)
→ Tab状态: [tab_a3f2(google), *tab_b7c1(竞品A官网)]
→ 提取价格 → switch_tab(tab_a3f2) → 搜索竞品B
→ 再次点击(新tab) → 提取价格B
→ 重复获取价格C → 汇总三个价格做对比
```

---

## 二、DOM 交互 (DOM Interaction)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 索引点击 | browser-use | 增量编号的交互元素索引 `[index]<tag attr/>` |
| 坐标点击 | browser-use | 视口坐标直接点击，支持 LLM 截图到实际视口的坐标转换 |
| DOM 序列化 | browser-use | `DOMTreeSerializer` 树形格式 + 缩进层级表示 |
| Shadow DOM 穿透 | browser-use | 穿透 Shadow DOM 边界为内部元素分配索引 |
| iframe 嵌套 | browser-use | 跨 iframe 分配全局唯一索引 |
| 新元素标记 | browser-use | 与上步对比，新出现的用 `*[index]` 前缀标记 |
| Paint order 过滤 | browser-use | 移除被遮挡的不可见元素 |
| 页面内容搜索 | browser-use | `search_page` JS 搜索 DOM 文本 |
| CSS 选择器查询 | browser-use | `find_elements` 通过 CSS 选择器定位 |
| 可点击检测 | browser-use | `ClickableElementDetector` 判断哪些元素应显示为可交互 |

### 调用 Case

```
Agent 在复杂 SPA 页面填写表单 (Shadow DOM 组件):
→ DOMTreeSerializer 穿透 Shadow DOM 为 input 分配 index=35
→ Agent: fill(index=35, value="John Doe")
→ 无需了解 Shadow DOM 内部结构

Agent 从页面截图定位按钮:
→ 截图分析: 提交按钮在坐标 (450, 320)
→ 坐标转换: LLM截图尺寸 → 实际视口尺寸
→ click_coordinate(x=450, y=320)
```

---

## 三、任务状态维护 (Task-state Maintenance)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 结构化 AgentState | browser-use | 步数/连续失败数/计划状态/最近模型输出 |
| 每步自评估 | browser-use | LLM 输出: evaluation_previous_goal + memory + next_goal |
| 历史记录 | browser-use | `AgentHistoryList` 完整记录每步的动作/结果/浏览器状态快照 |
| 持久化 todo | browser-use | `todo.md` 清单文件跟踪多步任务进度 |
| 事件流格式化 | browser-use | `agent_history_description` 将历史格式化为评估+记忆+目标+结果 |
| 任务记录 | OpenHarness | TaskRecord: ID/类型/状态(pending→running→completed)/时间戳/返回码 |
| 成本追踪 | OpenHarness | CostTracker 累计 input_tokens 和 output_tokens |

### 调用 Case

```
Agent 执行"收集20篇论文元数据":
→ Step 12: evaluation="成功提取第12篇" / memory="已收集12/20篇" / next_goal="导航到第13篇"
→ todo.md: [x]论文1-12 [ ]论文13-20
→ Step 13导航失败 → evaluation="页面加载失败" → 自动重试
→ 从 memory "已收集12/20" 恢复到正确位置继续
```

---

## 四、子目标分解 (Sub-goal Decomposition)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 动态计划 | browser-use | `PlanItem(text, status: pending/current/done/skipped)` |
| 计划更新 | browser-use | LLM 输出 `plan_update: list[str]` 创建/更新计划 |
| 自动推进 | browser-use | `_update_plan_from_model_output()` 自动标记 done/current |
| 可视化渲染 | browser-use | `[x]/[>]/[ ]/[-]` 标记文本注入 LLM 上下文 |
| 简单/复杂分流 | browser-use | 系统提示: 简单任务直接执行, 复杂任务输出 3-10 项计划 |

### 调用 Case

```
用户: "在电商网站找到5款满足特定规格的笔记本并比较"
→ Agent 输出 plan_update:
  [ ] 导航到电商网站
  [ ] 应用CPU/RAM/价格筛选条件
  [ ] 逐一查看并记录5款产品规格
  [ ] 汇总对比表格
→ 执行中第2步筛选器不可用 → Agent 输出新 plan_update 修改策略:
  [x] 导航到电商网站
  [-] 应用筛选条件 (不可用)
  [>] 手动搜索关键词筛选
  [ ] 逐一查看产品
  [ ] 汇总对比
```

---

## 五、上下文压缩 (Context Compression)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 每N步压缩 | browser-use | `compact_every_n_steps=25` 触发 |
| 字符数触发 | browser-use | `trigger_char_count=40000` 字符下限 |
| 保留最近N条 | browser-use | `keep_last_items=6` 保留完整历史 |
| 摘要最大长度 | browser-use | `summary_max_chars=6000` |
| 压缩提示 | browser-use | `<compacted_memory>` 标签包裹，注明"视为未验证上下文" |
| 历史项限制 | browser-use | 超出时保留首尾，中间 "[... N previous steps omitted...]" |
| DOM 截断 | browser-use | `max_clickable_elements_length=40000` 限制元素文本长度 |
| 自动 compaction | OpenHarness | 每次 API 调用前检查 token 超阈值 → 自动压缩对话历史 |

### 调用 Case

```
Agent 执行 100+ 步的数据收集任务:
→ 第50步: 历史超过 40000 字符
→ 压缩: 前44步总结为 6000 字符摘要
→ 保留最近 6 步完整信息
→ LLM 继续高效工作不超出 context window

DOM 特别复杂的页面(电商列表):
→ 原始 DOM 序列化 = 120000 字符
→ max_clickable_elements_length=40000 截断
→ 只展示前 40000 字符的可交互元素
→ 必要时 Agent 可 scroll_down 获取更多
```

---

## 六、长链控制流 (Long Chain Control Flow)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 循环检测 | browser-use | `ActionLoopDetector`: 5/8/12 次重复动作递增警告 |
| 页面停滞检测 | browser-use | `PageFingerprint` 连续5步页面无变化时警告 |
| 步数预算警告 | browser-use | ≥75% 预算时注入提示要求优先保存已有成果 |
| 最后一步强制完成 | browser-use | 最后一步可用动作限制为只有 `done` |
| 连续失败终止 | browser-use | `max_failures=5` 次后强制终止 |
| 重计划提示 | browser-use | 连续3次失败且有计划时建议修改计划 |
| 探索提示 | browser-use | 无计划执行5步后提示创建计划 |
| Fallback LLM | browser-use | 主 LLM 速率限制时自动切换备用 LLM |
| 每步超时 | browser-use | step_timeout=180s, llm_timeout, 动作超时=180s |
| 最大轮次 | OpenHarness | 达到最大轮次限制时停止工具调用循环 |

### 调用 Case

```
Agent 反复点击已过期的按钮:
→ 第5次: "Warning: You seem to be repeating the same action. Consider an alternative."
→ 第8次: "Strong warning: Repeated action detected 8 times. Change your approach."
→ 第12次: "Critical: You MUST try a completely different strategy now."
→ 如果继续无效 → max_failures=5 → 强制终止

100步任务到第76步:
→ budget_warning: "You have used 76% of your step budget (76/100). 
   Prioritize saving any results you have so far."
→ Agent 开始保存已收集数据 → 尝试完成剩余工作
→ 第100步: 可用动作限制为 done → 输出已有结果
```

---

## 七、错误恢复 (Error Recovery)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 动作级错误捕获 | browser-use | 每个动作返回 `ActionResult(error=...)` 结构化反馈给 LLM |
| 浏览器重连 | browser-use | 连接断开后自动重连 |
| 页面加载重试 | browser-use | 加载失败自动重试 |
| Watchdog 弹窗处理 | browser-use | 自动检测并处理弹窗/Cookie 横幅/CAPTCHA 等阻塞 |
| API 指数退避 | OpenHarness | 最大3次重试, BASE_DELAY×2^attempt(上限30s), 随机抖动0-25% |
| 可重试状态码 | OpenHarness | 429/500/502/503/529 |
| 工具超时追踪 | OpenHarness | 工具执行超时记录，超限转离线存储 |
| Autopilot 修复循环 | OpenHarness | 验证失败最多重试 max_attempts 次，携带失败元数据 |
| 进程终止升级 | OpenHarness | terminate() → 超时 → kill() |

### 调用 Case

```
Agent 点击按钮但页面弹出 Cookie 横幅遮挡:
→ Watchdog 检测到 Cookie banner
→ 自动点击 "Accept All" 关闭
→ 重试原始点击操作 → 成功

API 限流:
→ 第1次: 429 Too Many Requests → 等待 2s
→ 第2次: 429 → 等待 4s + 随机抖动
→ 第3次: 200 OK → 继续执行
→ 若3次都失败 → 切换 Fallback LLM
```

---

## 八、多 Agent 协调 (Multi-Agent Coordination)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| Coordinator-Worker 模式 | OpenHarness | 协调器编排任务, Worker 自主执行 |
| 并行 Worker 启动 | OpenHarness | "Parallelism is your superpower. Launch independent workers concurrently." |
| XML 信封通信 | OpenHarness | Worker 结果通过 `<task-notification>` 传递回协调器 |
| Agent 定义 | OpenHarness | `AgentDefinition`: system_prompt/tools/model/effort/max_turns |
| 三层加载 | OpenHarness | 内置 → 用户 → 插件 (后者覆盖前者) |
| Swarm 模块 | OpenHarness | 文件邮箱通信 + 团队生命周期 + 子进程隔离 + 资源锁 |
| Worktree 隔离 | OpenHarness | git worktree 允许多分支并行工作 |

### 调用 Case

```
复杂任务 "监控5个竞品网站的价格变动":
→ Coordinator: 分析任务 → 启动 5 个并行 Worker
→ Worker 1-5: 各自导航到一个竞品网站 → 提取价格
→ 通过 <task-notification> 报告结果
→ Coordinator: 收集所有结果 → 生成对比报告
```

---

## 九、记忆系统 (Memory System)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| Markdown 文件持久化 | OpenHarness | MEMORY.md 索引 + 各条目独立文件 |
| 多因子相关性搜索 | OpenHarness | 元数据匹配(2x)+正文匹配(1x)+重要性(0.4x)+频次(0.5x)+新鲜度(0.3x) |
| 重要度评分 | OpenHarness | importance: 0-N 标度 |
| TTL 过期 | OpenHarness | ttl_days 支持自动过期 |
| 重复检测 | OpenHarness | 签名比对防止重复条目 |
| 中文分词 | OpenHarness | 汉字逐字处理支持中文搜索 |
| Reranker 重排 | OpenHarness | 3x 候选筛选后可选 Reranker 重排 |
| 截断注入 | OpenHarness | 最终结果截断至 8000 字符注入 prompt |
| 技能系统 | OpenHarness | Markdown 文件加载领域知识，五层优先级 |
| 原子写入 | OpenHarness | 文件排他锁保证数据完整性 |

### 调用 Case

```
用户新会话: "继续上周的竞品分析"
→ 记忆搜索: "竞品分析" 关键词匹配
→ 找到3条相关记忆: 
  - 竞品A价格趋势 (importance=8, 3天前)
  - 竞品B新功能发布 (importance=6, 5天前)  
  - 分析方法论笔记 (importance=4, 12天前)
→ 多因子评分排序 → 截断至 8000 字符 → 注入对话上下文
→ Agent: "上周分析了竞品A和B，发现A价格上涨趋势明显..."
```

---

## 十、工具系统 (Tool System)

### 核心能力

| 能力 | 代表项目 | 实现方式 |
|------|----------|----------|
| 44 个内置工具 | OpenHarness | 文件/Shell/Web/MCP/媒体/任务/定时 等分类 |
| BaseTool 抽象基类 | OpenHarness | name + description + input_model (Pydantic) + async execute() |
| ToolRegistry | OpenHarness | 注册/检索/API schema 生成 |
| MCP 集成 | OpenHarness | HTTP transport 连接外部 MCP 服务器 |
| LSP 工具 | OpenHarness | document_symbol/workspace_symbol/go_to_definition/find_references/hover |
| 定时调度 | OpenHarness | cron_create/delete/list + sleep |
| 浏览器动作 | browser-use | click/fill/scroll/navigate/switch_tab/extract_content/search_page/screenshot |

### browser-use 动作清单

| 动作 | 参数 | 功能 |
|------|------|------|
| click | index 或 coordinate | 点击元素 |
| fill | index + text | 输入文本 |
| scroll | direction + amount | 滚动页面 |
| navigate | url, new_tab? | 导航到 URL |
| switch_tab | tab_id | 切换标签页 |
| close_tab | tab_id | 关闭标签页 |
| extract_content | goal | 提取页面内容 |
| search_page | query | 页面内搜索 |
| find_elements | selector | CSS 选择器查找 |
| screenshot | - | 截取页面截图 |
| done | result | 完成任务并返回结果 |

### 调用 Case

```
Agent 完成电商价格提取:
→ navigate("https://shop.example.com/search?q=laptop")
→ scroll(direction="down", amount=3) # 加载更多产品
→ extract_content(goal="获取前5个产品的名称和价格")
→ 结果: [{name:"ThinkPad X1", price:"$1299"}, ...]
→ done(result="5款笔记本价格已提取")
```
