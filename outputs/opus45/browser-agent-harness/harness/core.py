"""
core.py - Core harness aggregating all six components.

H = (E, T, C, S, L, V)
- E: ExecutionEngine (dual-layer state machine)
- T: ToolRegistry (browser operation tools)
- C: ContextManager (page, task, navigation contexts)
- S: TaskGraph + CrossPageDataStore (state management)
- L: LifecycleManager (hooks)
- V: TrajectoryLogger (evaluation interface)
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine

from harness.context import ContextManager
from harness.evaluation import TrajectoryLogger
from harness.execution import ExecutionEngine
from harness.lifecycle import LifecycleManager, create_default_lifecycle_manager
from harness.schemas import (
    AttendanceReport,
    DashboardStats,
    EmployeeInfo,
    LeaveRequest,
    PageState,
    Screenshot,
    StepStatus,
    TaskResult,
    TaskStep,
)
from harness.state import CheckpointManager, CrossPageDataStore, TaskGraph
from harness.tools import ToolRegistry


class BrowserAgentHarness:
    """
    Main harness class aggregating all six components.

    Usage:
        harness = BrowserAgentHarness()
        harness.load_scenario("samples/task_scenarios.json")
        harness.set_browser(browser_adapter)
        result = await harness.run()
    """

    def __init__(
        self,
        output_dir: str = "output",
        checkpoint_dir: str = ".checkpoints",
        session_id: str | None = None,
    ) -> None:
        self._session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()
        self._task_graph = TaskGraph()
        self._data_store = CrossPageDataStore()
        self._context = ContextManager()
        self._lifecycle = create_default_lifecycle_manager()
        self._logger = TrajectoryLogger(
            output_dir=str(self._output_dir / "trajectories"),
            session_id=self._session_id,
        )
        self._checkpoint = CheckpointManager(checkpoint_dir)

        self._engine: ExecutionEngine | None = None
        self._browser: Any = None
        self._page: Any = None
        self._llm_client: Any = None
        self._model_name: str | None = None

        self._approval_callback: Callable[[str], Coroutine[Any, Any, bool]] | None = None
        self._log_callback: Callable[[str], None] | None = None

    @property
    def tool_registry(self) -> ToolRegistry:
        """Get the tool registry."""
        return self._tool_registry

    @property
    def task_graph(self) -> TaskGraph:
        """Get the task graph."""
        return self._task_graph

    @property
    def data_store(self) -> CrossPageDataStore:
        """Get the cross-page data store."""
        return self._data_store

    @property
    def context(self) -> ContextManager:
        """Get the context manager."""
        return self._context

    @property
    def lifecycle(self) -> LifecycleManager:
        """Get the lifecycle manager."""
        return self._lifecycle

    @property
    def logger(self) -> TrajectoryLogger:
        """Get the trajectory logger."""
        return self._logger

    def set_approval_callback(
        self,
        callback: Callable[[str], Coroutine[Any, Any, bool]],
    ) -> None:
        """Set callback for user approval requests."""
        self._approval_callback = callback
        self._lifecycle.set_approval_callback(callback)

    def set_log_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for logging messages."""
        self._log_callback = callback
        self._lifecycle.set_log_callback(callback)

    def _log(self, message: str) -> None:
        """Log a message."""
        if self._log_callback:
            self._log_callback(message)

    def load_scenario(self, scenario_path: str) -> None:
        """Load task scenario from JSON file."""
        with open(scenario_path, encoding="utf-8") as f:
            data = json.load(f)

        scenario = data.get("scenario", data)
        steps = scenario.get("steps", [])

        for step_data in steps:
            step = TaskStep(
                step_id=step_data["id"],
                action=step_data["action"],
                description=step_data["description"],
                expected_state=step_data.get("expected_state"),
                challenge=step_data.get("challenge"),
                extract_fields=step_data.get("extract_fields", []),
                requires_approval=step_data.get("id") in [7, 8, 9],
            )

            dependencies = []
            if step.step_id > 1:
                dependencies.append(step.step_id - 1)

            self._task_graph.add_step(step, dependencies)
            self._context.task.add_step(step)

        self._log(f"Loaded {len(steps)} steps from scenario")

    def set_llm_client(self, client: Any, model_name: str) -> None:
        """Set the OpenAI-compatible LLM client."""
        self._llm_client = client
        self._model_name = model_name

    def set_browser(self, browser: Any, page: Any) -> None:
        """Set the browser and page instances."""
        self._browser = browser
        self._page = page

    async def run(self) -> TaskResult:
        """Execute all task steps."""
        if not self._page:
            raise RuntimeError("Browser not set. Call set_browser() first.")

        self._engine = ExecutionEngine(
            task_graph=self._task_graph,
            data_store=self._data_store,
            context_manager=self._context,
            lifecycle_manager=self._lifecycle,
            trajectory_logger=self._logger,
            checkpoint_manager=self._checkpoint,
        )

        self._register_browser_tools()
        self._register_step_handlers()

        self._log("Starting task execution...")
        result = await self._engine.run()

        report_path = self._output_dir / f"report_{self._session_id}.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result.to_report())

        json_path = self._output_dir / f"result_{self._session_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

        self._logger.export_readable(str(self._output_dir / f"trajectory_{self._session_id}.txt"))

        self._log(f"Execution complete. Report: {report_path}")
        return result

    def _register_browser_tools(self) -> None:
        """Register browser tool handlers with the execution engine."""
        if not self._engine or not self._page:
            return

        async def navigate(url: str) -> PageState:
            await self._page.goto(url, wait_until="networkidle")
            return await self._get_page_state()

        async def click(selector: str, wait_navigation: bool = False) -> bool:
            await self._page.wait_for_selector(selector, state="visible", timeout=10000)
            if wait_navigation:
                async with self._page.expect_navigation():
                    await self._page.click(selector)
            else:
                await self._page.click(selector)
            return True

        async def fill(selector: str, value: str, clear_first: bool = True) -> bool:
            await self._page.wait_for_selector(selector, state="visible", timeout=10000)
            if clear_first:
                await self._page.fill(selector, "")
            await self._page.fill(selector, value)
            return True

        async def select(selector: str, value: str) -> bool:
            await self._page.wait_for_selector(selector, state="visible", timeout=10000)
            await self._page.select_option(selector, value)
            return True

        async def set_date(selector: str, date: str) -> bool:
            await self._page.wait_for_selector(selector, state="visible", timeout=10000)
            await self._page.fill(selector, date)
            return True

        async def extract_text(selector: str) -> str:
            await self._page.wait_for_selector(selector, timeout=10000)
            return await self._page.inner_text(selector)

        async def extract_attribute(selector: str, attribute: str) -> str | None:
            await self._page.wait_for_selector(selector, timeout=10000)
            return await self._page.get_attribute(selector, attribute)

        async def extract_all(selector: str) -> list[str]:
            elements = await self._page.query_selector_all(selector)
            return [await el.inner_text() for el in elements]

        async def wait_for_element(
            selector: str,
            timeout_ms: int = 10000,
            visible: bool = True,
        ) -> bool:
            state = "visible" if visible else "attached"
            await self._page.wait_for_selector(selector, state=state, timeout=timeout_ms)
            return True

        async def wait_for_load(timeout_ms: int = 30000) -> bool:
            await self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return True

        async def screenshot(
            path: str,
            selector: str | None = None,
            full_page: bool = False,
        ) -> str:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if selector:
                element = await self._page.wait_for_selector(selector)
                if element:
                    await element.screenshot(path=path)
            else:
                await self._page.screenshot(path=path, full_page=full_page)
            return path

        async def close_popup(popup_type: str, selector: str | None = None) -> bool:
            if popup_type == "cookie_banner":
                selectors = [
                    "button:has-text('接受所有 Cookie')",
                    "button.accept",
                    "#cookie-banner button.btn-primary",
                ]
                for sel in ([selector] if selector else selectors):
                    try:
                        await self._page.click(sel, timeout=2000)
                        return True
                    except Exception:
                        continue
            elif popup_type == "modal":
                close_selectors = [
                    selector,
                    ".modal .btn-primary",
                    ".modal-close",
                    "button:has-text('确定')",
                    "button:has-text('关闭')",
                ]
                for sel in [s for s in close_selectors if s]:
                    try:
                        await self._page.click(sel, timeout=2000)
                        return True
                    except Exception:
                        continue
            return False

        async def detect_popup() -> str | None:
            checks = [
                ("#cookie-banner.active", "cookie_banner"),
                (".cookie-banner.active", "cookie_banner"),
                (".modal-overlay.active", "modal"),
                ("#reject-modal.active", "reject_modal"),
                ("#success-modal.active", "success_modal"),
            ]
            for selector, popup_type in checks:
                try:
                    visible = await self._page.is_visible(selector)
                    if visible:
                        return popup_type
                except Exception:
                    continue
            return None

        async def get_page_info() -> PageState:
            return await self._get_page_state()

        async def download_file(
            trigger_selector: str,
            save_path: str,
            timeout_ms: int = 30000,
        ) -> str:
            async with self._page.expect_download(timeout=timeout_ms) as download_info:
                await self._page.click(trigger_selector)
            download = await download_info.value
            await download.save_as(save_path)
            return save_path

        self._engine.set_browser_tool("navigate", navigate)
        self._engine.set_browser_tool("click", click)
        self._engine.set_browser_tool("fill", fill)
        self._engine.set_browser_tool("select", select)
        self._engine.set_browser_tool("set_date", set_date)
        self._engine.set_browser_tool("extract_text", extract_text)
        self._engine.set_browser_tool("extract_attribute", extract_attribute)
        self._engine.set_browser_tool("extract_all", extract_all)
        self._engine.set_browser_tool("wait_for_element", wait_for_element)
        self._engine.set_browser_tool("wait_for_load", wait_for_load)
        self._engine.set_browser_tool("screenshot", screenshot)
        self._engine.set_browser_tool("close_popup", close_popup)
        self._engine.set_browser_tool("detect_popup", detect_popup)
        self._engine.set_browser_tool("get_page_info", get_page_info)
        self._engine.set_browser_tool("download_file", download_file)

    async def _get_page_state(self) -> PageState:
        """Extract current page state."""
        from harness.schemas import InteractableElement

        url = self._page.url
        title = await self._page.title()

        elements = []
        interactable_selectors = [
            ("input", "input:visible"),
            ("button", "button:visible"),
            ("a", "a[href]:visible"),
            ("select", "select:visible"),
            ("textarea", "textarea:visible"),
        ]

        for tag, selector in interactable_selectors:
            try:
                els = await self._page.query_selector_all(selector)
                for i, el in enumerate(els[:10]):
                    try:
                        el_type = await el.get_attribute("type")
                        text = await el.inner_text() if tag not in ("input", "select") else None
                        placeholder = await el.get_attribute("placeholder")
                        aria_label = await el.get_attribute("aria-label")
                        name = await el.get_attribute("name")
                        el_id = await el.get_attribute("id")
                        is_visible = await el.is_visible()
                        is_enabled = await el.is_enabled()

                        css_selector = f"{tag}"
                        if el_id:
                            css_selector = f"#{el_id}"
                        elif name:
                            css_selector = f"{tag}[name='{name}']"
                        elif placeholder:
                            css_selector = f"{tag}[placeholder*='{placeholder[:20]}']"
                        elif text and tag in ("button", "a"):
                            css_selector = f"{tag}:has-text('{text[:20]}')"

                        elements.append(InteractableElement(
                            tag=tag,
                            element_type=el_type,
                            selector=css_selector,
                            text=text[:50] if text else None,
                            placeholder=placeholder,
                            aria_label=aria_label,
                            name=name,
                            element_id=el_id,
                            is_visible=is_visible,
                            is_enabled=is_enabled,
                        ))
                    except Exception:
                        continue
            except Exception:
                continue

        popup_type = None
        has_popup = False
        popup_checks = [
            ("#cookie-banner.active", "cookie_banner"),
            (".cookie-banner.active", "cookie_banner"),
            (".modal-overlay.active", "modal"),
        ]
        for selector, ptype in popup_checks:
            try:
                if await self._page.is_visible(selector):
                    has_popup = True
                    popup_type = ptype
                    break
            except Exception:
                continue

        key_content = {}
        content_selectors = {
            "welcome": "h2:has-text('欢迎')",
            "stats": ".stat-cards",
            "table": "table",
        }
        for key, selector in content_selectors.items():
            try:
                if await self._page.is_visible(selector):
                    text = await self._page.inner_text(selector)
                    key_content[key] = text[:200]
            except Exception:
                continue

        state = PageState(
            url=url,
            title=title,
            interactable_elements=elements,
            key_text_content=key_content,
            has_popup=has_popup,
            popup_type=popup_type,
        )

        self._context.on_page_load(state, self._engine._current_step.step_id if self._engine and self._engine._current_step else None)

        return state

    def _register_step_handlers(self) -> None:
        """Register custom handlers for each task step."""
        if not self._engine:
            return

        self._engine.set_step_handler(1, self._handle_step_1_init)
        self._engine.set_step_handler(2, self._handle_step_2_login_page)
        self._engine.set_step_handler(3, self._handle_step_3_login)
        self._engine.set_step_handler(4, self._handle_step_4_dashboard)
        self._engine.set_step_handler(5, self._handle_step_5_search_employees)
        self._engine.set_step_handler(6, self._handle_step_6_employee_detail)
        self._engine.set_step_handler(7, self._handle_step_7_approve_leave)
        self._engine.set_step_handler(8, self._handle_step_8_reject_leave)
        self._engine.set_step_handler(9, self._handle_step_9_submit_leave)
        self._engine.set_step_handler(10, self._handle_step_10_view_reports)
        self._engine.set_step_handler(11, self._handle_step_11_export_csv)
        self._engine.set_step_handler(12, self._handle_step_12_generate_report)

    async def _handle_step_1_init(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 1: Initialize (mock server should already be running)."""
        self._log("Step 1: Environment initialized")
        step.extracted_data["server_ready"] = True
        return True

    async def _handle_step_2_login_page(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 2: Open login page and handle cookie banner."""
        await engine._call_tool("navigate", url="http://localhost:5000/login")
        await asyncio.sleep(1)

        popup = await engine._call_tool("detect_popup")
        if popup == "cookie_banner":
            self._log("Closing cookie consent banner...")
            await engine._call_tool("close_popup", popup_type="cookie_banner")
            await asyncio.sleep(0.5)

        step.extracted_data["cookie_handled"] = True
        return True

    async def _handle_step_3_login(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 3: Login with admin credentials."""
        await engine._call_tool("fill", selector="#username", value="admin")
        await engine._call_tool("fill", selector="#password", value="admin123")

        if self._approval_callback:
            approved = await self._approval_callback("Login as admin user")
            if not approved:
                return False

        await engine._call_tool("click", selector="#login-btn", wait_navigation=True)
        await engine._call_tool("wait_for_load")

        current_url = self._page.url
        if "/dashboard" in current_url:
            step.extracted_data["login_success"] = True
            self._log("Login successful, redirected to dashboard")
            return True
        else:
            step.error_message = f"Login failed, still at {current_url}"
            return False

    async def _handle_step_4_dashboard(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 4: Extract dashboard statistics."""
        await engine._call_tool("wait_for_element", selector=".stat-cards")
        await asyncio.sleep(1)

        stat_cards = await self._page.query_selector_all(".stat-card")
        stats = {}

        for card in stat_cards:
            try:
                number = await card.query_selector(".number")
                label = await card.query_selector(".label")
                if number and label:
                    num_text = await number.inner_text()
                    label_text = await label.inner_text()

                    if "在职员工" in label_text:
                        stats["total_employees"] = int(num_text)
                    elif "待审批" in label_text:
                        stats["pending_leaves"] = int(num_text)
                    elif "新入职" in label_text:
                        stats["new_hires"] = int(num_text)
                    elif "到期" in label_text:
                        stats["contract_expiring"] = int(num_text)
            except Exception:
                continue

        step.extracted_data.update(stats)
        self._data_store.set_dashboard_stats(DashboardStats(**stats))
        self._log(f"Extracted dashboard stats: {stats}")
        return True

    async def _handle_step_5_search_employees(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 5: Search for employees with surname '张'."""
        await engine._call_tool("navigate", url="http://localhost:5000/employees")
        await engine._call_tool("wait_for_element", selector="#search-input")
        await asyncio.sleep(1)

        await engine._call_tool("fill", selector="#search-input", value="张")
        await engine._call_tool("click", selector="button:has-text('搜索')")
        await asyncio.sleep(1)

        result_text = await engine._call_tool("extract_text", selector="#result-count")
        count_match = result_text.split()[1] if "共" in result_text else "0"
        search_count = int(count_match) if count_match.isdigit() else 0

        first_name = None
        try:
            rows = await self._page.query_selector_all("table tbody tr")
            if rows:
                first_row = rows[0]
                name_cell = await first_row.query_selector("td:nth-child(2)")
                if name_cell:
                    first_name = await name_cell.inner_text()
        except Exception:
            pass

        step.extracted_data["search_result_count"] = search_count
        step.extracted_data["first_employee_name"] = first_name
        self._data_store.set("search_results", {"count": search_count, "first_name": first_name})
        self._log(f"Search found {search_count} employees, first: {first_name}")
        return True

    async def _handle_step_6_employee_detail(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 6: View first employee's details."""
        await engine._call_tool("click", selector="table tbody tr:first-child a:has-text('查看详情')", wait_navigation=True)
        await engine._call_tool("wait_for_element", selector="#emp-info")
        await asyncio.sleep(1)

        info = {}
        try:
            info_div = await self._page.query_selector("#emp-info")
            if info_div:
                text = await info_div.inner_text()

                for line in text.split("\n"):
                    if "姓名：" in line:
                        info["name"] = line.split("：")[1].strip()
                    elif "部门：" in line:
                        info["department"] = line.split("：")[1].strip()
                    elif "职位：" in line:
                        info["position"] = line.split("：")[1].strip()
                    elif "入职日期：" in line:
                        info["hire_date"] = line.split("：")[1].strip()
                    elif "年假余额：" in line:
                        balance_text = line.split("：")[1].strip().replace(" 天", "")
                        info["annual_leave_balance"] = float(balance_text)
                    elif "绩效评分：" in line:
                        info["performance_score"] = float(line.split("：")[1].strip())
        except Exception as e:
            self._log(f"Error extracting employee info: {e}")

        step.extracted_data.update(info)
        if info.get("name"):
            emp = EmployeeInfo(**info)
            self._data_store.add_employee(emp)
        self._log(f"Extracted employee info: {info}")
        return True

    async def _handle_step_7_approve_leave(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 7: Approve the first pending leave request."""
        await engine._call_tool("navigate", url="http://localhost:5000/leave-requests")
        await engine._call_tool("wait_for_element", selector="#leave-table table")
        await asyncio.sleep(1)

        if self._approval_callback:
            approved = await self._approval_callback("Approve the first pending leave request")
            if not approved:
                return False

        await engine._call_tool("click", selector="table tbody tr:first-child button:has-text('通过')")
        await asyncio.sleep(1)

        step.extracted_data["approved_leave"] = True
        self._log("Approved first leave request")
        return True

    async def _handle_step_8_reject_leave(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 8: Reject the next pending leave request with reason."""
        await asyncio.sleep(0.5)

        if self._approval_callback:
            approved = await self._approval_callback("Reject a pending leave request")
            if not approved:
                return False

        reject_buttons = await self._page.query_selector_all("button:has-text('拒绝')")
        if reject_buttons:
            await reject_buttons[0].click()
            await asyncio.sleep(0.5)

            await engine._call_tool("wait_for_element", selector="#reject-modal.active")
            await engine._call_tool("fill", selector="#reject-comment", value="当前项目进度紧张，建议另选时间")
            await engine._call_tool("click", selector="button:has-text('确认拒绝')")
            await asyncio.sleep(1)

            step.extracted_data["rejected_leave"] = True
            step.extracted_data["reject_reason"] = "当前项目进度紧张，建议另选时间"
            self._log("Rejected leave request with reason")
            return True

        step.error_message = "No reject button found"
        return False

    async def _handle_step_9_submit_leave(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 9: Submit a new leave request."""
        await engine._call_tool("click", selector="a:has-text('提交请假申请')", wait_navigation=True)
        await engine._call_tool("wait_for_element", selector="#leave-form")

        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

        await engine._call_tool("select", selector="#leave-type", value="年假")
        await engine._call_tool("set_date", selector="#start-date", date=tomorrow)
        await engine._call_tool("set_date", selector="#end-date", date=day_after)
        await engine._call_tool("fill", selector="#reason", value="家庭原因")
        await engine._call_tool("fill", selector="#emergency", value="张三: 13800138000")

        if self._approval_callback:
            approved = await self._approval_callback("Submit new leave request (年假, 2 days)")
            if not approved:
                return False

        await engine._call_tool("click", selector="#submit-btn")
        await asyncio.sleep(1)

        try:
            await engine._call_tool("wait_for_element", selector="#success-modal.active", timeout_ms=5000)
            step.extracted_data["leave_submitted"] = True
            step.extracted_data["leave_type"] = "年假"
            step.extracted_data["leave_dates"] = f"{tomorrow} to {day_after}"
            self._log("Leave request submitted successfully")
            return True
        except Exception:
            step.error_message = "Success modal not shown"
            return False

    async def _handle_step_10_view_reports(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 10: View attendance reports and extract tech dept Jan rate."""
        await engine._call_tool("navigate", url="http://localhost:5000/reports")
        await engine._call_tool("wait_for_element", selector="#report-table table")
        await asyncio.sleep(1)

        tech_jan_rate = None
        try:
            rows = await self._page.query_selector_all("#report-table table tbody tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 4:
                    dept = await cells[0].inner_text()
                    month = await cells[1].inner_text()
                    if "技术部" in dept and "2024-01" in month:
                        rate_text = await cells[3].inner_text()
                        tech_jan_rate = float(rate_text.replace("%", ""))
                        break
        except Exception as e:
            self._log(f"Error extracting attendance: {e}")

        step.extracted_data["tech_dept_jan_attendance_rate"] = tech_jan_rate
        self._data_store.set("tech_jan_attendance", tech_jan_rate)
        self._log(f"Tech dept Jan 2024 attendance rate: {tech_jan_rate}%")
        return True

    async def _handle_step_11_export_csv(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 11: Export CSV report."""
        export_path = str(self._output_dir / "attendance_report.csv")

        try:
            await engine._call_tool(
                "download_file",
                trigger_selector="#export-btn",
                save_path=export_path,
                timeout_ms=10000,
            )
            step.extracted_data["csv_exported"] = True
            step.extracted_data["csv_path"] = export_path
            self._log(f"CSV exported to {export_path}")
            return True
        except Exception as e:
            step.error_message = f"CSV export failed: {e}"
            return False

    async def _handle_step_12_generate_report(self, step: TaskStep, engine: ExecutionEngine) -> bool:
        """Step 12: Generate final operation report."""
        all_data = self._data_store.get_all_extracted_data()
        screenshots = self._data_store.get_screenshots()

        step.extracted_data["report_generated"] = True
        step.extracted_data["total_data_points"] = len(all_data)
        step.extracted_data["total_screenshots"] = len(screenshots)

        self._log("Final report generated")
        return True

    def pause(self) -> None:
        """Pause execution after current step."""
        if self._engine:
            self._engine.pause()

    def resume(self) -> None:
        """Resume paused execution."""
        if self._engine:
            self._engine.resume()

    def skip_step(self, step_id: int) -> None:
        """Skip a specific step."""
        if self._engine:
            self._engine.skip_step(step_id)

    def retry_step(self, step_id: int) -> None:
        """Retry a failed/skipped step."""
        if self._engine:
            self._engine.retry_step(step_id)

    def get_state(self) -> dict[str, Any]:
        """Get current harness state."""
        return {
            "extracted_data": self._data_store.get_all_extracted_data(),
            "progress": self._engine.get_progress() if self._engine else None,
            "context": self._context.to_dict(),
        }

    async def resume_from_checkpoint(self, checkpoint_path: str | None = None) -> TaskResult:
        """Resume execution from a checkpoint."""
        path = checkpoint_path or self._checkpoint.get_latest()
        if not path:
            raise RuntimeError("No checkpoint found")

        self._task_graph, self._data_store, phase = self._checkpoint.load(path)
        self._log(f"Resumed from checkpoint: {path}, phase: {phase}")

        return await self.run()
