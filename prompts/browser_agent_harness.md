# 任务描述：浏览器智能体 Harness（Browser Agent）

构建一个通用的浏览器自动化 harness，能接受 Web 任务描述（导航、表单填写、数据提取、文件下载等），自主在浏览器中完成多步骤操作。

---

## 组件特化要求

| 组件 | 本 harness 的特定要求 |
|------|----------------------|
| **E** | 分离任务级流程（子目标分解和推进）和单次页面操作逻辑。支持单步 retry 和 skip |
| **T** | 至少覆盖：导航、元素交互（click/fill/select）、数据提取、截图、等待。所有操作前必须先等待元素就绪 |
| **C** | 构建可访问性树摘要（每个可交互元素分配数字索引，裁剪不可见节点），禁止原始 DOM/HTML |
| **S** | 维护子目标依赖图和完成状态。支持断点续跑：中途失败后从最后成功子目标恢复 |
| **L** | 导航后自动等待加载完成、弹窗自动检测并非阻塞处理、超时时截图保存后重试 |
| **V** | 每步记录：URL、操作类型、目标元素索引、操作结果、截图文件路径 |

---

## 功能性质

一个成熟的浏览器代理 harness 运行感知-思考-行动循环，作用于压缩的页面表示。它不摄入原始 DOM（通常 50k+ 节点），而是构建可访问性树摘要：每个可交互元素分配稳定的数字索引，不可见和装饰性节点被裁剪，将数万节点的 DOM 压缩为数百行结构化文本供 LLM 推理。每个循环中 agent 输出一个 JSON 动作（click/fill/scroll/navigate/extract/wait），harness 通过 CDP 或 Playwright 执行，等待 network-idle/element-ready 信号，然后捕获新的页面快照作为下一轮观察。跨页面状态通过持久任务记忆维护——已完成子目标的滚动摘要加当前目标——确保上下文不因页面切换丢失。复杂任务被分解为可变计划（3-10 个子目标）；每完成一个里程碑或遭遇失败后更新计划。动态内容通过显式等待谓词和退避重试处理；弹窗和模态框通过 DOM mutation 观察器检测并非阻塞地关闭后恢复主流程。动作失败时 agent 收到错误、重新获取快照并选择替代路径——对同一元素连续失败 2-3 次后升级策略（滚动可视、换选择器、返回上一页）。提取的数据跨步骤累积，任务完成时输出为结构化 JSON，附带 JSONL 轨迹和带时间戳的截图供审计。

---

## 调用示例

### Case 1：跨站比价

```bash
python -m harness -p "比较 Sony WH-1000XM5 在 amazon.com 和 bestbuy.com 的价格，返回 JSON 包含 {site, price, in_stock}" --output-dir ./output/
```

**行为轨迹：**
- 导航到 amazon.com，等待搜索框出现（index 7），输入产品名，按 Enter，等待结果网格渲染
- 从可访问性树中识别首个匹配产品链接（按文本匹配过滤），点击进入 PDP，从快照的价格区域提取价格，从配送信息提取库存状态
- 新标签页导航到 bestbuy.com 搜索页，重复搜索-点击-提取循环
- 格式化为目标 JSON schema，调用 done 动作
- 处理：Amazon 的人机验证（等待+重试），Best Buy 的 cookie 弹窗（检测并关闭）

**产物：** `result.json`（比价数据），`trajectory.jsonl`（8 步），每个 PDP 加载时的截图

---

### Case 2：多页面表单提交含文件上传

```bash
python -m harness -p "在 portal.example.gov 用环境变量中的凭证登录，进入'新申请'页面，用 ./applicant.json 填写所有必填项，上传 ./id_scan.pdf，提交" --output-dir ./output/
```

**行为轨迹：**
- 导航到登录页，等待用户名输入框出现，填入环境变量凭证，点击提交，等待仪表盘 URL
- 在导航可访问性树中定位"新申请"链接，点击，等待表单渲染（检测到 5+ 输入元素）
- 读取 `applicant.json`，按可访问性树中的字段标签映射（如"姓名"→ index 12），逐一填写；下拉框通过匹配选项文本处理
- 检测文件上传 input，上传 `id_scan.pdf`，等待文件名确认文本出现
- 点击"提交"，等待确认页文本，提取申请编号
- 恢复机制：如中途会话超时检测到登录重定向，重新认证，从最后成功子目标恢复

**产物：** `result.json`（`{status: "success", reference_id: "APP-2024-88712"}`），`trajectory.jsonl`（14 步），表单填写和确认页截图

---

### Case 3：分页表格数据提取

```bash
python -m harness -p "在 crunchbase.com/lists/unicorn-companies 提取 2020 年后成立的所有公司的名称、估值、国家，导出 CSV" --output-dir ./output/
```

**行为轨迹：**
- 导航到列表 URL，等待表格渲染，在可访问性树中识别筛选控件
- 点击"成立日期"筛选器，设置最小年份为 2021，应用筛选，等待表格刷新（行数变化）
- 通过解析可访问性树中的结构化文本提取可见行（每行映射为重复模式：`[name] [valuation] [country] [year]`）
- 检测分页：识别"下一页"按钮（index 47），循环点击+提取直到按钮禁用/消失
- 聚合所有行，去重，写入 CSV

**产物：** `unicorns_post2020.csv`，`result.json`（含行数和状态），`trajectory.jsonl`（22 步跨 6 页）

---

### Case 4：带条件分支的多步工作流

```bash
python -m harness -p "在 github.com 检查 anthropics/claude-code 仓库是否有标签为 bug 且评论超过 10 条的 open issue。如有则收集标题和 URL；如没有则改为搜索全站 'browser automation bug' issues" --output-dir ./output/
```

**行为轨迹：**
- 导航到 `github.com/anthropics/claude-code/issues?q=is:open+label:bug`，等待 issue 列表渲染
- 解析可访问性树中每个 issue 行的评论数元数据，筛选 count > 10
- **分支 A（有匹配）：** 收集符合条件 issue 的 title + URL，如需翻页则继续
- **分支 B（无匹配）：** 导航到全站搜索 `github.com/search?q=browser+automation+bug&type=issues`，提取 top-10 结果
- 格式化为 JSON 数组输出

**产物：** `result.json`（`{status: "success", issues: [...]}`），`trajectory.jsonl`（7-12 步取决于分支），截图

---

## 技术栈补充

- 浏览器自动化：Playwright（推荐 async API）
- Dockerfile 额外要求：`playwright install --with-deps chromium`
