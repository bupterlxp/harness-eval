import os
import time
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from dataclasses import asdict

from .schemas import TaskStatus, StepResult, PageState
from .tools import BrowserTools
from .context import ContextManager
from .lifecycle import LifecycleHooks
from .evaluation import EvaluationRecorder


class ExecutionEngine:
    """Double state machine execution engine"""

    def __init__(self, config: Dict):
        self.config = config
        self.tools = BrowserTools(config)
        self.context = ContextManager(config)
        self.lifecycle = LifecycleHooks(self.tools, self.context, config)
        self.evaluator = EvaluationRecorder()
        self.current_step = 0
        self.task_running = False

        # Create required directories
        for dir_name in ["screenshots", "downloads", "reports", "evaluation"]:
            os.makedirs(dir_name, exist_ok=True)

    def start_task(self, task_id: str = "default_task") -> None:
        """Start a new task"""
        self.context.initialize_task(task_id)
        self.lifecycle.reset_retry_count()
        self.evaluator = EvaluationRecorder()
        self.task_running = True
        print(f"Task {task_id} started")

    def stop_task(self) -> None:
        """Stop current task"""
        self.task_running = False
        print("Task stopped")

    def execute_step(self, step_func: Callable, step_id: int, **kwargs) -> StepResult:
        """Execute a single step with retry logic"""
        self.current_step = step_id
        self.lifecycle.reset_retry_count()

        while self.lifecycle.retry_count < self.config.get("max_retries", 3):
            try:
                result = step_func(**kwargs)
                result.step_id = step_id

                if result.status == TaskStatus.COMPLETED:
                    self.context.mark_step_completed(step_id, result)
                    self.evaluator.record_step(result, {
                        "step_description": kwargs.get("description", ""),
                        "step_data": kwargs
                    })
                    return result

                elif result.status == TaskStatus.FAILED:
                    print(f"Step {step_id} failed: {result.error_message}")
                    self.lifecycle.retry_count += 1
                    if self.lifecycle.retry_count < self.config.get("max_retries", 3):
                        print(f"Retrying step {step_id} ({self.lifecycle.retry_count}/{self.config.get('max_retries', 3)})")
                        time.sleep(1)

            except Exception as e:
                error_result = StepResult(
                    step_id=step_id,
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url if self.tools.page else "",
                    error_message=str(e)
                )
                self.evaluator.record_step(error_result)
                return error_result

        # If all retries failed
        final_result = StepResult(
            step_id=step_id,
            status=TaskStatus.FAILED,
            url=self.tools.page.url if self.tools.page else "",
            error_message=f"Max retries ({self.config.get('max_retries', 3)}) exceeded"
        )
        self.evaluator.record_step(final_result)
        return final_result

    def run_task_sequence(self, steps: List[Dict]) -> Dict[str, Any]:
        """Run a sequence of task steps"""
        self.start_task()

        for step_def in steps:
            if not self.task_running:
                break

            step_id = step_def["id"]
            print(f"\nExecuting step {step_id}: {step_def['action']}")

            # Execute based on action type
            if step_def["action"] == "启动Mock服务":
                result = self._start_mock_service(step_def)
            elif step_def["action"] == "打开登录页并处理弹窗":
                result = self._handle_login_page(step_def)
            elif step_def["action"] == "登录系统":
                result = self._perform_login(step_def)
            elif step_def["action"] == "查看仪表盘待办":
                result = self._extract_dashboard_data(step_def)
            elif step_def["action"] == "搜索员工":
                result = self._search_employees(step_def)
            elif step_def["action"] == "查看员工详情":
                result = self._view_employee_detail(step_def)
            elif step_def["action"] == "审批请假-通过":
                result = self._approve_leave(step_def, approve=True)
            elif step_def["action"] == "审批请假-拒绝":
                result = self._approve_leave(step_def, approve=False)
            elif step_def["action"] == "提交请假申请":
                result = self._submit_leave_request(step_def)
            elif step_def["action"] == "查看考勤报表":
                result = self._view_attendance_report(step_def)
            elif step_def["action"] == "导出CSV报表":
                result = self._export_csv_report(step_def)
            elif step_def["action"] == "生成操作报告":
                result = self._generate_final_report(step_def)
            else:
                result = StepResult(
                    step_id=step_id,
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url if self.tools.page else "",
                    error_message=f"Unknown action: {step_def['action']}"
                )

            # Take screenshot after each step
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(
                self.config.get("screenshot_dir", "screenshots"),
                f"step_{step_id}_{timestamp}.png"
            )
            if self.tools.screenshot(screenshot_path):
                result.screenshot_path = screenshot_path
                self.context.add_screenshot(screenshot_path)

            # Record and update
            self.evaluator.record_step(result, {
                "action": step_def["action"],
                "description": step_def["description"]
            })

            if result.status != TaskStatus.COMPLETED:
                print(f"Step {step_id} failed after retries: {result.error_message}")
                break

        # Final cleanup
        self.tools.close_browser()
        self.context.save_context()

        # Generate final report
        final_report = self.evaluator.generate_report()
        self.evaluator.save_report(final_report)
        trajectory_file = self.evaluator.save_trajectory()

        final_report["trajectory_file"] = trajectory_file
        final_report["context_file"] = self.context.save_context()

        return final_report

    def _start_mock_service(self, step_def: Dict) -> StepResult:
        """Mock service startup (placeholder)"""
        # This would start the Flask server in a real scenario
        return StepResult(
            step_id=step_def["id"],
            status=TaskStatus.COMPLETED,
            url="",
            data={"message": "Mock service started (simulated)"}
        )

    def _handle_login_page(self, step_def: Dict) -> StepResult:
        """Handle login page with popup handling"""
        try:
            # Navigate to login page
            url = f"{self.config.get('base_url')}/login"
            pre_info = self.lifecycle.pre_navigate(url)
            self.tools.navigate(url)
            post_info = self.lifecycle.post_navigate(url)

            # Take screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(
                self.config.get("screenshot_dir", "screenshots"),
                f"step_{step_def['id']}_{timestamp}.png"
            )
            self.tools.screenshot(screenshot_path)

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=url,
                screenshot_path=screenshot_path,
                data={
                    **post_info.data,
                    "pre_navigate": pre_info,
                    "screenshot": screenshot_path
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _perform_login(self, step_def: Dict) -> StepResult:
        """Perform login action"""
        try:
            # Wait for login form
            if not self.tools.wait_for_element("input[name='username']"):
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url,
                    error_message="Login form not found"
                )

            # Fill credentials
            self.tools.fill("input[name='username']", "admin")
            self.tools.fill("input[name='password']", "admin123")

            # Click login button
            result = self.tools.click("button[type='submit']", wait_for_navigation=True)

            # Verify login success
            if "/dashboard" in self.tools.page.url:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.COMPLETED,
                    url=self.tools.page.url,
                    data={
                        **result.data,
                        "login_success": True,
                        "redirected_to_dashboard": True
                    }
                )
            else:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url,
                    error_message="Login failed - not redirected to dashboard"
                )

        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _extract_dashboard_data(self, step_def: Dict) -> StepResult:
        """Extract dashboard statistics"""
        try:
            # Wait for dashboard to load
            self.tools.wait_for_load()

            # Extract statistics - these selectors match the mock HTML
            stats = {}
            stat_selectors = {
                "total_employees": ".stat.total-employees",
                "pending_leaves": ".stat.pending-leaves",
                "new_hires": ".stat.new-hires",
                "contract_expiring": ".stat.contract-expiring"
            }

            for key, selector in stat_selectors.items():
                text = self.tools.extract_text(selector)
                if text:
                    stats[key] = int(''.join(filter(str.isdigit, text)))

            # Save to context
            self.context.save_extracted_data(stats, "dashboard")

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=self.tools.page.url,
                data={
                    "extracted_stats": stats,
                    "dashboard_data_loaded": True
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url,
                error_message=str(e)
            )

    def _search_employees(self, step_def: Dict) -> StepResult:
        """Search employees by name"""
        try:
            # Navigate to employees page
            url = f"{self.config.get('base_url')}/employees"
            self.tools.navigate(url)
            self.tools.wait_for_load()

            # Wait for search input
            if not self.tools.wait_for_element("input[name='search']"):
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=url,
                    error_message="Search input not found"
                )

            # Fill search term
            self.tools.fill("input[name='search']", "张")

            # Click search button
            self.tools.click("button.search-btn")

            # Wait for results
            time.sleep(1)

            # Extract first employee name
            first_employee = self.tools.extract_text(".employee-item:first-child .name")
            result_count = self.tools.extract_text(".result-count")

            data = {}
            if first_employee:
                data["first_employee_name"] = first_employee
            if result_count:
                data["search_result_count"] = int(''.join(filter(str.isdigit, result_count)))

            # Save to context
            self.context.save_extracted_data(data, "employees_search")

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=url,
                data=data
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _view_employee_detail(self, step_def: Dict) -> StepResult:
        """View employee detail page"""
        try:
            # Click first employee detail link
            detail_link = self.tools.page.query_selector(".employee-item:first-child .detail-link")
            if not detail_link:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url,
                    error_message="Employee detail link not found"
                )

            # Get employee ID from link
            employee_id = detail_link.get_attribute("data-eid") or "1"

            # Click detail link
            result = self.tools.click(".employee-item:first-child .detail-link", wait_for_navigation=True)

            # Wait for detail page
            self.tools.wait_for_load()

            # Extract employee data
            data = {}
            detail_selectors = {
                "name": ".employee-name",
                "department": ".employee-department",
                "position": ".employee-position",
                "hire_date": ".employee-hire-date",
                "annual_leave_balance": ".leave-balance",
                "performance_score": ".performance-score"
            }

            for key, selector in detail_selectors.items():
                text = self.tools.extract_text(selector)
                if text:
                    if key in ["annual_leave_balance", "performance_score"]:
                        try:
                            data[key] = float(text)
                        except:
                            data[key] = text
                    else:
                        data[key] = text

            # Save to context
            self.context.save_extracted_data(data, "employee_detail")

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=self.tools.page.url,
                data={
                    **data,
                    "employee_id": employee_id
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _approve_leave(self, step_def: Dict, approve: bool = True) -> StepResult:
        """Approve or reject leave request"""
        try:
            # Navigate to leave requests page
            url = f"{self.config.get('base_url')}/leave-requests"
            self.tools.navigate(url)
            self.tools.wait_for_load()

            # Find first pending leave request
            leave_item = self.tools.page.query_selector(".leave-item.pending:first-child")
            if not leave_item:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=url,
                    error_message="No pending leave requests found"
                )

            # Get leave ID
            leave_id = leave_item.get_attribute("data-lid") or "1"

            # Click action button
            if approve:
                result = self.tools.click(f".leave-item[data-lid='{leave_id}'] .approve-btn", wait_for_navigation=True)
                action = "approved"
            else:
                # Click reject button
                result = self.tools.click(f".leave-item[data-lid='{leave_id}'] .reject-btn")

                # Handle rejection modal
                if self.tools.wait_for_element("#rejection-modal", timeout=5000):
                    # Fill rejection reason
                    self.tools.fill("textarea[name='reason']", "当前项目进度紧张，建议另选时间")
                    # Click confirm button
                    self.tools.click("#confirm-reject-btn", wait_for_navigation=True)

                action = "rejected"

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=self.tools.page.url,
                data={
                    "leave_id": leave_id,
                    "action": action,
                    "success": True
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _submit_leave_request(self, step_def: Dict) -> StepResult:
        """Submit a new leave request"""
        try:
            # Navigate to leave form
            url = f"{self.config.get('base_url')}/leave/new"
            self.tools.navigate(url)
            self.tools.wait_for_load()

            # Wait for form elements
            if not all([
                self.tools.wait_for_element("select[name='leave_type']"),
                self.tools.wait_for_element("input[name='start_date']"),
                self.tools.wait_for_element("input[name='end_date']"),
                self.tools.wait_for_element("textarea[name='reason']")
            ]):
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=url,
                    error_message="Form elements not found"
                )

            # Fill form
            today = datetime.now()
            tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            day_after = (today + timedelta(days=2)).strftime("%Y-%m-%d")

            # Select leave type - 年假 (annual leave)
            self.tools.select("select[name='leave_type']", "年假")

            # Fill dates
            self.tools.fill("input[name='start_date']", tomorrow)
            self.tools.fill("input[name='end_date']", day_after)

            # Fill reason
            self.tools.fill("textarea[name='reason']", "家庭原因")

            # Fill emergency contact
            self.tools.fill("input[name='emergency_contact']", "张三: 13800138000")

            # Submit form
            result = self.tools.click("button[type='submit']", wait_for_navigation=True)

            # Check for success modal
            success = self.tools.wait_for_element(".success-modal", timeout=5000)

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED if success else TaskStatus.FAILED,
                url=self.tools.page.url,
                data={
                    "success_modal": success,
                    "leave_submitted": True
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _view_attendance_report(self, step_def: Dict) -> StepResult:
        """View attendance report"""
        try:
            # Navigate to reports page
            url = f"{self.config.get('base_url')}/reports"
            self.tools.navigate(url)
            self.tools.wait_for_load()

            # Extract technical department January attendance
            tech_dept_jan = self.tools.extract_text(".department-row[data-dept='技术部'] .month-2024-01 .attendance-rate")

            data = {}
            if tech_dept_jan:
                try:
                    data["tech_dept_jan_attendance_rate"] = float(tech_dept_jan)
                except:
                    data["tech_dept_jan_attendance_rate"] = tech_dept_jan

            # Save to context
            self.context.save_extracted_data(data, "attendance")

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=url,
                data=data
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _export_csv_report(self, step_def: Dict) -> StepResult:
        """Export CSV report"""
        try:
            # Click export button
            download_path = self.tools.download_file("button.export-csv")

            if download_path:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.COMPLETED,
                    url=self.tools.page.url,
                    data={
                        "downloaded_file": download_path,
                        "csv_exported": True
                    }
                )
            else:
                return StepResult(
                    step_id=step_def["id"],
                    status=TaskStatus.FAILED,
                    url=self.tools.page.url,
                    error_message="CSV download failed"
                )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )

    def _generate_final_report(self, step_def: Dict) -> StepResult:
        """Generate final operation report"""
        try:
            # Get all extracted data
            all_data = self.context.get_extracted_data()

            # Create report structure
            final_report = {
                "task_id": self.context.task_context.task_id if self.context.task_context else "",
                "timestamp": datetime.now().isoformat(),
                "extracted_data": all_data,
                "screenshots": self.context.task_context.screenshots if self.context.task_context else [],
                "navigation_history": self.context.navigation_history,
                "task_summary": self.context.get_current_status()
            }

            # Save report
            report_dir = self.config.get("report_dir", "reports")
            os.makedirs(report_dir, exist_ok=True)
            report_path = os.path.join(report_dir, f"final_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(final_report, f, indent=2, ensure_ascii=False)

            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.COMPLETED,
                url=self.tools.page.url,
                data={
                    "report_path": report_path,
                    **final_report
                }
            )
        except Exception as e:
            return StepResult(
                step_id=step_def["id"],
                status=TaskStatus.FAILED,
                url=self.tools.page.url if self.tools.page else "",
                error_message=str(e)
            )