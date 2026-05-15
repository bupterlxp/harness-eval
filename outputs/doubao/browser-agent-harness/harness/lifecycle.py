import os
import json
from typing import List, Dict, Optional, Any, Callable
from datetime import datetime
from dataclasses import asdict

from .schemas import TaskStatus, StepResult
from .tools import BrowserTools
from .context import ContextManager
from .domain.popup import PopupHandler


class LifecycleHooks:
    """Lifecycle hooks for browser automation"""

    def __init__(self, tools: BrowserTools, context: ContextManager, config: Dict):
        self.tools = tools
        self.context = context
        self.config = config
        self.retry_count = 0
        self.max_retries = config.get("max_retries", 3)

    def pre_navigate(self, url: str) -> Dict[str, Any]:
        """Hook before navigation"""
        return {
            "timestamp": datetime.now().isoformat(),
            "from_url": self.tools.page.url if self.tools.page else "",
            "to_url": url,
            "step": self.context.task_context.current_step if self.context.task_context else 0
        }

    def post_navigate(self, url: str) -> StepResult:
        """Hook after navigation - wait for load and handle popups"""
        # Wait for page to load
        if not self.tools.wait_for_load():
            return StepResult(
                step_id=self.context.task_context.current_step if self.context.task_context else 0,
                status=TaskStatus.FAILED,
                url=url,
                error_message="Page failed to load"
            )

        # Handle popups
        popup_handler = PopupHandler(self.tools.page)
        closed = popup_handler.close_all_popups()

        # Update page state
        page_state = self.tools.get_page_state()
        self.context.update_page_state(page_state)

        return StepResult(
            step_id=self.context.task_context.current_step if self.context.task_context else 0,
            status=TaskStatus.COMPLETED,
            url=url,
            data={
                "popups_closed": closed,
                "page_state": asdict(page_state)
            }
        )

    def pre_click(self, selector: str) -> Dict[str, Any]:
        """Hook before clicking an element"""
        # Wait for element to be visible and enabled
        if not self.tools.wait_for_element(selector):
            return {
                "error": f"Element {selector} not found or not visible",
                "status": TaskStatus.FAILED
            }

        # Verify element is enabled
        try:
            element = self.tools.page.query_selector(selector)
            if not element:
                return {"error": f"Element {selector} not found"}

            disabled = element.get_attribute("disabled")
            if disabled and disabled.lower() == "true":
                return {"error": f"Element {selector} is disabled"}
        except Exception as e:
            return {"error": str(e)}

        return {
            "timestamp": datetime.now().isoformat(),
            "selector": selector,
            "step": self.context.task_context.current_step if self.context.task_context else 0
        }

    def on_timeout(self, error: Exception, context_info: Dict) -> StepResult:
        """Hook on timeout/error"""
        self.retry_count += 1

        # Take screenshot for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(
            self.config.get("screenshot_dir", "screenshots"),
            f"error_{timestamp}.png"
        )
        self.tools.screenshot(screenshot_path)

        return StepResult(
            step_id=self.context.task_context.current_step if self.context.task_context else 0,
            status=TaskStatus.FAILED if self.retry_count >= self.max_retries else TaskStatus.PENDING,
            url=self.tools.page.url if self.tools.page else "",
            error_message=str(error),
            screenshot_path=screenshot_path,
            retry_count=self.retry_count
        )

    def pre_submit(self, form_data: Dict) -> Dict[str, Any]:
        """Hook before form submission - require user confirmation for critical actions"""
        # Check if this is an admin action that needs confirmation
        critical_actions = ["approve", "reject", "delete", "submit"]

        for action in critical_actions:
            if any(action in key.lower() for key in form_data.keys()):
                return {
                    "requires_confirmation": True,
                    "action": "critical_form_submission",
                    "form_data": form_data,
                    "message": "This action requires user confirmation before proceeding"
                }

        return {
            "requires_confirmation": False,
            "form_data": form_data
        }

    def on_popup_detected(self, popup_selector: str, popup_type: str) -> Dict[str, Any]:
        """Hook when popup is detected"""
        return {
            "timestamp": datetime.now().isoformat(),
            "popup_type": popup_type,
            "selector": popup_selector,
            "action": "auto_closed"  # Default action
        }

    def reset_retry_count(self) -> None:
        """Reset retry counter"""
        self.retry_count = 0