# Agent Harness 构建任务：浏览器智能体（Browser Agent）

构建一个通用的浏览器自动化 harness，能接受 Web 任务描述（导航、表单填写、数据提取、文件下载等），自主在浏览器中完成多步骤操作。

## Scaffold-native 最低实现要求

如果当前 creation profile 是 `claude_code_scaffold_native`，工作区已经有 `generated_program.py`、`scaffold_manifest.json` 和 `harness_scaffold/`。你必须直接修改并实现 `generated_program.py` 中的 `GeneratedHarnessProgram.run(...)`，不能停留在 scaffold seed。

必须满足：

- 删除或替换 `raise NotImplementedError`、`TODO`、stub fallback；
- `generated_program.py` 必须真实调用 `harness_scaffold` runtime，并驱动 browser action planning、state tracking、action execution、observation parsing 和 final result writing；
- 可以新增模块，但新增模块必须被 `generated_program.py` 实际调用；
- 不能只写 README、说明文档、helper 模块或未接入的工具；
- 运行后必须写出 `result.json`、`trajectory.jsonl`、stdout/stderr 日志，以及 final state/result artifact、action trace、截图或提取数据；
- 如果浏览器服务、页面或凭证不可用，必须结构化记录失败原因并输出 `partial` 或 `failed`，不能伪造完成状态。

---

## 一、入口与输出

```bash
python -m harness -p "任务描述" --output-dir ./output/
```

- `-p`：自然语言任务描述（harness 自行解析并执行）
- `--output-dir`：输出目录，执行完成后在该目录下生成 `result.json`

`result.json` 必须包含以下字段，其余字段可自行扩展：

```python
{
    "status": str,       # "success" | "partial" | "failed"
    "trajectory": str,   # JSONL trajectory 文件路径
}
```

### Browser BMK 必须满足的执行契约

这个 harness 会直接接入 TheAgentCompany / browser-task 类长链任务。评测会检查最终环境状态和操作轨迹。因此必须做到：

- 每一步 action 必须是可执行的浏览器动作或等价工具动作，例如 navigate、click、type、select、upload、extract、wait、screenshot、done；
- `trajectory.jsonl` 每行必须记录 action、observation、state summary、error、retry 或 final decision；
- 必须维护当前 URL、页面标题、活跃元素、已完成子目标、待完成子目标和已收集数据；
- 最终 `result.json` 必须包含 status、final_state、collected_data 或 reference id，并指向关键 artifact；
- 页面不可访问、服务未启动、凭证缺失时，必须把缺失依赖写入 result 和 trajectory，不能把模拟数据当成真实完成结果。

---

## 二、功能性质

一个成熟的浏览器代理 harness 运行感知-思考-行动循环，在压缩的页面表示上进行推理和操作，自主完成多步骤 Web 任务。

**页面状态感知与 DOM 压缩。** 不摄入原始 DOM（通常 50k+ 节点），而是构建可访问性树摘要：每个可交互元素分配稳定的数字索引，不可见和装饰性节点被裁剪，将数万节点的 DOM 压缩为数百行结构化文本供 LLM 推理。支持 Shadow DOM 穿透（为嵌套组件内部元素分配索引）、跨 iframe 全局唯一索引、paint order 过滤（移除被遮挡的不可见元素）。新出现的元素与上一步对比后特殊标记，帮助 LLM 识别页面变化。DOM 文本超出长度限制时截断（保留前 N 个可交互元素），Agent 可通过滚动获取更多。

**动作执行与等待机制。** 每个循环中 agent 输出一个 JSON 动作（click/fill/scroll/navigate/switch_tab/close_tab/extract_content/search_page/screenshot/wait/done），harness 通过 CDP 或 Playwright 执行。支持索引点击（基于可访问性树中的稳定索引）和坐标点击（基于截图分析的视口坐标，含 LLM 截图尺寸→实际视口的坐标转换）。执行后等待 network-idle/element-ready 信号，然后捕获新的页面快照作为下一轮观察。动态内容通过显式等待谓词和退避重试处理。

**多标签页管理。** 每个标签页以唯一标识追踪，支持创建新标签页、切换、关闭。点击链接后自动检测是否打开了新标签页并切换过去。每步向 LLM 呈现完整的标签页状态列表（URL+标题+活跃标记），确保 Agent 始终了解所有打开页面的状态。支持跨标签页的数据收集——在多个站点分别提取信息后汇总。

**子目标分解与动态计划。** 复杂任务被分解为可变计划（3-10 个子目标），每个子目标有状态标记（pending/current/done/skipped）。计划在执行中动态更新：每完成一个里程碑自动推进，遭遇失败后可修改策略。简单任务直接执行，复杂任务 LLM 输出初始计划后按序推进。计划可视化（checklist 标记）注入 LLM 上下文帮助追踪进度。

**任务状态维护与记忆。** 跨页面状态通过持久任务记忆维护——已完成子目标的滚动摘要加当前目标——确保上下文不因页面切换丢失。每步 LLM 输出结构化自评估：上一步是否达成目标 + 当前记忆摘要 + 下一步目标。完整的动作历史记录每步的浏览器状态快照和执行结果，格式化为评估+记忆+目标+结果的事件流供 LLM 参考。

**长链控制流与循环检测。** 循环检测器追踪重复动作：5 次相同动作发出警告，8 次强烈警告，12 次要求必须切换策略。页面停滞检测：连续 5 步页面内容指纹无变化时警告。步数预算管理：达到 75% 时注入提示要求优先保存已有成果；最后一步可用动作限制为只有 done，强制输出已收集的结果。连续 N 次失败后可触发计划重制。Fallback LLM：主模型速率限制时自动切换备用模型。

**上下文压缩。** 对于长任务（50+ 步），按步数或字符数阈值触发压缩：将旧步骤历史总结为摘要（标记为未验证上下文），保留最近 N 步完整信息。DOM 文本按最大长度截断。压缩后 Agent 仍可通过 memory 字段保持关键信息的连续性。

**错误恢复与弹窗处理。** 动作失败时 agent 收到结构化错误信息，重新获取页面快照后选择替代路径——对同一元素连续失败 2-3 次后升级策略（滚动使元素可视、换选择器、返回上一页）。弹窗/模态框/Cookie 横幅通过 DOM 变化观察器自动检测，非阻塞地关闭后恢复主流程。浏览器连接断开后自动重连。页面加载失败自动重试。API 调用失败采用指数退避重试（最大 3 次，随机抖动）。

**数据提取与结构化输出。** 提取的数据跨步骤累积，支持页面内容搜索（JS 搜索 DOM 文本）和 CSS 选择器查询。分页数据通过循环检测"下一页"按钮并迭代提取直到按钮消失/禁用。任务完成时输出为结构化 JSON，附带 JSONL 轨迹和带时间戳的截图供审计。

---

## 三、调用示例

### Case 1：跨站比价（多标签页 + 弹窗处理 + 数据汇总）

```bash
python -m harness -p "比较 Sony WH-1000XM5 在 amazon.com 和 bestbuy.com 的价格，返回 JSON 包含 {site, price, in_stock}" --output-dir ./output/
```

**行为轨迹：**
- Step 1：计划生成——
  ```
  [>] 在 Amazon 搜索并提取价格和库存
  [ ] 在 Best Buy 搜索并提取价格和库存
  [ ] 汇总为目标 JSON 格式
  ```
- Step 2（navigate）：导航到 amazon.com，等待页面加载完成
- Step 3（DOM 快照）：可访问性树呈现搜索框（index 7: `<input name="field-keywords"/>`），输入 "Sony WH-1000XM5"，按 Enter
- Step 4（等待+识别）：等待搜索结果网格渲染（检测到新元素出现），在可访问性树中识别首个匹配产品链接——按产品名文本匹配过滤，排除广告标记结果
- Step 5（点击+提取）：点击进入 PDP（产品详情页），等待价格区域渲染。从快照提取：
  - 价格：`$278.00`（index 23: `<span class="a-price-whole">278</span>`）
  - 库存状态：`In Stock`（index 31: `<span>In Stock</span>`）
  - 自评估："Amazon 价格已获取 ✓"
- Step 6（新标签页）：navigate("https://www.bestbuy.com", new_tab=true)
  - 标签页状态更新：[tab_a3f2(Amazon PDP), *tab_b7c1(Best Buy)]
- Step 7（Cookie 弹窗处理）：
  - DOM 变化检测到 Cookie consent 模态框覆盖页面
  - 自动识别 "Accept All" 按钮（index 4），点击关闭
  - 恢复主流程
- Step 8（搜索）：在 Best Buy 搜索框输入产品名，等待结果
- Step 9（提取）：进入 PDP，提取价格 `$279.99` 和库存 `Available for shipping`
- Step 10（汇总+done）：
  ```json
  [
    {"site": "amazon.com", "price": "$278.00", "in_stock": true},
    {"site": "bestbuy.com", "price": "$279.99", "in_stock": true}
  ]
  ```
  - 计划更新：所有项标记 [x] done

**产物：** `result.json`（比价数据 JSON），`trajectory.jsonl`（10 步，含每步 DOM 快照摘要和动作），`screenshots/`（Amazon PDP + Best Buy PDP 各一张）

---

### Case 2：多页面表单提交含文件上传（认证 + 表单映射 + 会话恢复）

```bash
python -m harness -p "在 portal.example.gov 用环境变量中的凭证登录，进入'新申请'页面，用 ./applicant.json 填写所有必填项，上传 ./id_scan.pdf，提交" --output-dir ./output/
```

**行为轨迹：**
- Step 1（计划）：
  ```
  [>] 登录 portal.example.gov
  [ ] 导航到"新申请"页面
  [ ] 填写表单必填项
  [ ] 上传身份证文件
  [ ] 提交并获取确认编号
  ```
- Step 2（登录）：导航到登录页，等待表单渲染。DOM 快照显示：
  - index 5: `<input id="username" required/>`
  - index 6: `<input id="password" type="password" required/>`
  - index 8: `<button type="submit">Sign In</button>`
- Step 3（填写凭证）：从环境变量读取 `GOV_USERNAME` 和 `GOV_PASSWORD`，fill(index=5, value=username)，fill(index=6, value=password)，click(index=8)
- Step 4（等待仪表盘）：等待 URL 变更为 `/dashboard`，确认登录成功
- Step 5（导航）：在 DOM 快照的导航菜单中定位"新申请"链接（index 14: `<a href="/applications/new">新申请</a>`），点击
- Step 6（表单发现）：等待表单渲染，DOM 快照显示 12 个输入元素（7 个 required 标记）。读取 `applicant.json` 内容：
  ```json
  {"name": "张伟", "id_number": "110101199001011234", "phone": "13800138000", "address": "北京市朝阳区...", "email": "zhang@example.com"}
  ```
- Step 7（表单填写）：按可访问性树中的字段标签映射：
  - "姓名" → index 20, fill("张伟")
  - "身份证号" → index 21, fill("110101199001011234")
  - "联系电话" → index 22, fill("13800138000")
  - "地址" → index 23, fill("北京市朝阳区...")
  - "电子邮箱" → index 24, fill("zhang@example.com")
  - "申请类型" → index 25 (select), 选择匹配选项文本
  - "紧急程度" → index 26 (radio), click 选中对应项
- Step 8（文件上传）：检测 index 28 为 `<input type="file">`，上传 `./id_scan.pdf`，等待文件名确认文本出现（"id_scan.pdf 已上传"）
- Step 9（提交）：点击"提交申请"按钮（index 30），等待确认页渲染
- Step 10（提取确认）：从确认页提取申请编号："APP-2024-88712"
  - **异常路径处理**：如中途检测到 URL 重定向回登录页（会话超时），自动重新执行 Step 2-3 认证流程，然后从最后成功的子目标恢复（不重填已提交的表单，而是检查是否有草稿保存）

**产物：** `result.json`（`{status: "success", reference_id: "APP-2024-88712"}`），`trajectory.jsonl`（10-14 步），`screenshots/`（表单填写完成截图 + 确认页截图）

---

### Case 3：分页表格数据提取（循环检测 + 筛选操作 + CSV 导出）

```bash
python -m harness -p "在 crunchbase.com/lists/unicorn-companies 提取 2020 年后成立的所有公司的名称、估值、国家，导出 CSV" --output-dir ./output/
```

**行为轨迹：**
- Step 1（计划）：
  ```
  [>] 导航到目标页面并应用筛选
  [ ] 逐页提取表格数据
  [ ] 去重并导出 CSV
  ```
- Step 2（导航）：打开目标 URL，等待表格渲染
- Step 3（筛选操作）：在 DOM 快照中识别筛选控件区域，点击"Founded Date"筛选器（index 15），等待筛选面板展开
- Step 4（设置筛选）：在年份输入框中填入"2021"作为最小值，点击"Apply"按钮，等待表格刷新（通过 DOM 变化检测——行数从 1200+ 变为新值）
- Step 5（首页提取）：解析 DOM 快照中表格行的重复模式——每行包含：
  - 公司名（链接文本）
  - 估值（数字+单位）
  - 国家（文本）
  - 成立年份（数字）
  - 提取当前可见的 25 行数据
- Step 6（分页循环开始）：
  - 识别分页控件：index 47 为"下一页"按钮（`<button aria-label="Next page">`）
  - 检查按钮状态：enabled → 点击
  - 等待表格内容更新（DOM 指纹变化）
  - 提取第 2 页 25 行
  - 记忆更新："已提取 50 行，共 N 页"
- Step 7-18（循环继续）：
  - 每步：click(next_page) → wait(DOM change) → extract(rows)
  - 步数到达 75% 预算警告：注入"优先保存已有数据"
  - 循环终止条件：下一页按钮变为 disabled（`aria-disabled="true"`）
  - 页面停滞检测：如连续 2 次点击后 DOM 无变化 → 尝试滚动到底部再检查 → 确认是最后一页
- Step 19（数据处理+输出）：
  - 汇总所有页数据（6 页 × 25 行 = 148 行）
  - 去重：按公司名去重，发现 2 条重复（跨页边界重复），最终 146 条
  - 写入 CSV：columns = [name, valuation, country, founded_year]

**产物：** `unicorns_post2020.csv`（146 行数据），`result.json`（`{status: "success", rows: 146, pages_scraped: 6}`），`trajectory.jsonl`（19 步），每页首次加载的截图

---

### Case 4：带条件分支的多步工作流（动态决策 + 计划修改）

```bash
python -m harness -p "在 github.com 检查 anthropics/claude-code 仓库是否有标签为 bug 且评论超过 10 条的 open issue。如有则收集标题和 URL；如没有则改为搜索全站 'browser automation bug' issues" --output-dir ./output/
```

**行为轨迹：**
- Step 1（计划——含条件分支）：
  ```
  [>] 导航到目标仓库 issues 页并应用筛选
  [ ] 检查是否存在评论>10的 bug issue
  [ ] 分支A: 收集匹配 issues  |  分支B: 全站搜索替代
  [ ] 格式化输出
  ```
- Step 2（导航）：navigate("https://github.com/anthropics/claude-code/issues?q=is:open+label:bug")，等待 issue 列表渲染
- Step 3（列表分析）：解析 DOM 快照中 issue 列表——每个 issue 行包含标题、标签、评论数。扫描可见 issues 的评论数元数据：
  - "Fix WebSocket reconnection" — 3 comments
  - "Memory leak in long sessions" — 7 comments
  - "Browser detection fails on Firefox" — 2 comments
  - 无评论 > 10 的 issue
- Step 4（翻页确认）：检查是否有更多页——如有下一页按钮，继续翻页检查；如只有 1 页结果，确认无匹配
- Step 5（条件判断——触发分支 B）：
  - 自评估："无评论>10的 bug issue，触发备选路径"
  - 计划更新：
    ```
    [x] 导航到目标仓库 issues 页并应用筛选
    [x] 检查是否存在评论>10的 bug issue — 结果:无
    [-] 分支A: 收集匹配 issues (跳过)
    [>] 分支B: 全站搜索 'browser automation bug'
    [ ] 格式化输出
    ```
- Step 6（全站搜索）：navigate("https://github.com/search?q=browser+automation+bug&type=issues&state=open")，等待搜索结果
- Step 7（提取 Top-10）：从搜索结果列表提取前 10 条 issue 的标题和 URL：
  - 每条记录：{title, url, repo, comments_count}
  - 按 comments_count 降序排列
- Step 8（done）：输出结构化结果
  ```json
  {
    "source": "github_global_search",
    "reason": "No bug issues with >10 comments found in anthropics/claude-code",
    "issues": [
      {"title": "Puppeteer automation breaks on SPA navigation", "url": "https://github.com/user/repo/issues/234", "repo": "user/repo", "comments": 45},
      ...
    ]
  }
  ```

**产物：** `result.json`（搜索结果 JSON，含来源说明和条件分支理由），`trajectory.jsonl`（8 步，含分支决策点标注），关键页面截图

---

### Case 5：复杂 SPA 交互——电商下单流程（Shadow DOM + 动态加载 + 多步确认）

```bash
python -m harness -p "在 shop.example.com 搜索 'mechanical keyboard'，筛选价格 $50-$100 且评分 4+ 星，将第一个结果加入购物车，进入结账页面但不提交支付，截图结账摘要" --output-dir ./output/
```

**行为轨迹：**
- Step 1（计划）：
  ```
  [>] 搜索产品并应用筛选
  [ ] 选择第一个匹配结果加入购物车
  [ ] 进入结账页面
  [ ] 截图结账摘要（不提交）
  ```
- Step 2（搜索）：导航到 shop.example.com，在搜索框输入 "mechanical keyboard"，提交搜索
- Step 3（筛选——Shadow DOM 场景）：
  - DOM 快照显示筛选面板使用了 Web Components（Shadow DOM）
  - 可访问性树穿透 Shadow DOM，为内部的价格滑块和评分选择器分配索引
  - 填写价格范围：min=50(index 33), max=100(index 34)
  - 点击 4+ 星筛选按钮(index 37)
  - 等待产品列表刷新（DOM 内容变化检测）
- Step 4（选择产品）：新出现的产品卡片标记为 `*[index 41-55]`（新元素标记），点击第一个产品卡片的"Add to Cart"按钮
- Step 5（购物车确认）：
  - 检测到悬浮购物车弹窗出现（DOM mutation）
  - 等待弹窗渲染完成
  - 验证产品已在购物车中（弹窗内显示产品名和数量）
  - 点击"Proceed to Checkout"
- Step 6（结账页面）：等待结账表单渲染，确认页面 URL 包含 `/checkout`
  - 不填写任何支付信息（按任务要求"不提交支付"）
- Step 7（截图）：对结账摘要区域执行 screenshot，保存为 `checkout_summary.png`
  - done(result="结账摘要已截图，产品：Keychron K6 $79.99，含运费和税")

**产物：** `result.json`（`{status: "success", product: "Keychron K6", price: "$79.99"}`），`checkout_summary.png`，`trajectory.jsonl`（7 步），关键状态截图序列

---

## 四、技术栈

- Python 3.11+，type hints
- LLM 调用：`openai` SDK，OpenAI 兼容接口。环境变量：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`
- 浏览器自动化：Playwright（推荐 async API）
- 禁止：LangChain / LlamaIndex / AutoGen / anthropic SDK

---

## 五、环境打包

必须提供 `Dockerfile`，确保 harness 在任意环境中可一键运行：

- 基于 `python:3.11-slim` 或同级官方镜像
- 安装所有 Python 依赖（推荐同时生成 `requirements.txt`）
- 安装 Playwright 及其浏览器依赖（`playwright install --with-deps chromium`）
- LLM 相关配置通过环境变量注入（`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`MODEL_NAME`），不硬编码在镜像中
- 容器启动后可直接执行 `python -m harness -p "..." --output-dir /output/`
