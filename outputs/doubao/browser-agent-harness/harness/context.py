import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import asdict, dataclass

from .schemas import TaskContext, PageState, StepResult


class ContextManager:
    """Manages page and task context across navigation"""

    def __init__(self, config: Dict):
        self.config = config
        self.task_context: Optional[TaskContext] = None
        self.current_page_state: Optional[PageState] = None
        self.navigation_history: List[str] = []
        self.screenshot_dir = config.get("screenshot_dir", "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def initialize_task(self, task_id: str) -> None:
        """Initialize new task context"""
        self.task_context = TaskContext(
            task_id=task_id,
            status="pending",
            current_step=0,
            completed_steps=[],
            extracted_data={},
            screenshots=[],
            navigation_history=[],
            session_cookies={}
        )

    def update_page_state(self, page_state: PageState) -> None:
        """Update current page state"""
        self.current_page_state = page_state
        if page_state.url:
            self.navigation_history.append(page_state.url)
            if self.task_context:
                self.task_context.navigation_history = self.navigation_history

    def add_screenshot(self, screenshot_path: str) -> None:
        """Add screenshot path to context"""
        if self.task_context and screenshot_path:
            self.task_context.screenshots.append(screenshot_path)

    def save_extracted_data(self, data: Dict[str, Any], namespace: Optional[str] = None) -> None:
        """Save extracted data to context"""
        if not self.task_context:
            return

        if namespace:
            if namespace not in self.task_context.extracted_data:
                self.task_context.extracted_data[namespace] = {}
            self.task_context.extracted_data[namespace].update(data)
        else:
            self.task_context.extracted_data.update(data)

    def get_extracted_data(self, namespace: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve extracted data"""
        if not self.task_context:
            return {}

        if namespace:
            return self.task_context.extracted_data.get(namespace, {})
        return self.task_context.extracted_data

    def mark_step_completed(self, step_id: int, result: StepResult) -> None:
        """Mark task step as completed"""
        if not self.task_context:
            return

        self.task_context.completed_steps.append(step_id)
        self.task_context.current_step = step_id + 1

        # Save data from step result
        if result.data:
            self.save_extracted_data(result.data)

        # Save screenshot if available
        if result.screenshot_path:
            self.add_screenshot(result.screenshot_path)

    def update_session_cookies(self, cookies: Dict[str, str]) -> None:
        """Update session cookies"""
        if self.task_context:
            self.task_context.session_cookies.update(cookies)

    def save_context(self, path: Optional[str] = None) -> str:
        """Save context to JSON file"""
        if not self.task_context:
            raise ValueError("No task context initialized")

        context_data = asdict(self.task_context)
        if not path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.screenshot_dir, f"task_context_{timestamp}.json")

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(context_data, f, indent=2, ensure_ascii=False)

        return path

    def load_context(self, path: str) -> None:
        """Load context from JSON file"""
        with open(path, "r", encoding="utf-8") as f:
            context_data = json.load(f)

        self.task_context = TaskContext(**context_data)
        self.navigation_history = self.task_context.navigation_history

    def get_current_status(self) -> Dict[str, Any]:
        """Get current task status"""
        if not self.task_context:
            return {"status": "no_task", "progress": 0}

        total_steps = 12  # Based on scenario
        progress = len(self.task_context.completed_steps) / total_steps * 100

        return {
            "task_id": self.task_context.task_id,
            "status": self.task_context.status,
            "current_step": self.task_context.current_step,
            "completed_steps": self.task_context.completed_steps,
            "progress": progress,
            "extracted_data_count": len(self.task_context.extracted_data),
            "screenshots_count": len(self.task_context.screenshots),
            "navigation_history_length": len(self.navigation_history)
        }