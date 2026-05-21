import asyncio
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from playwright.async_api import Page, BrowserContext
from ..context import ContextManager
from ..state import StateStore
from ..tools import ToolRegistry
from ..lifecycle import LifecycleHooks
from ..evaluation import EvaluationLogger
from . import TaskSpec, Result

class ExecutionLoop:
    """Main execution loop driving browser operations"""

    def __init__(self, task_spec: TaskSpec):
        self.task_spec = task_spec
        self.context_manager: Optional[ContextManager] = None
        self.state_store: Optional[StateStore] = None
        self.tool_registry: Optional[ToolRegistry] = None
        self.lifecycle_hooks: Optional[LifecycleHooks] = None
        self.evaluation_logger: Optional[EvaluationLogger] = None
        self.current_step = 0
        self.extracted_data: Dict[str, Any] = {}
        self.screenshots: List[str] = []
        self.downloads: List[str] = []
        self.errors: List[Dict[str, Any]] = []
        self.trajectory_file = ""

    async def initialize(self, browser_context: BrowserContext):
        """Initialize all components"""
        os.makedirs(self.task_spec.output_dir, exist_ok=True)

        self.context_manager = ContextManager(browser_context)
        await self.context_manager.initialize()

        self.state_store = StateStore(self.task_spec.output_dir)
        await self.state_store.initialize()

        self.tool_registry = ToolRegistry(self.context_manager, self.state_store)

        self.lifecycle_hooks = LifecycleHooks(self.context_manager, self.tool_registry)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.trajectory_file = os.path.join(self.task_spec.output_dir, f"trajectory_{timestamp}.jsonl")
        self.evaluation_logger = EvaluationLogger(self.trajectory_file)

    async def run(self) -> Result:
        """Main execution loop"""
        result = Result()

        try:
            # Navigate to initial URL
            page = await self.context_manager.new_page()
            await self.tool_registry.navigate(page, self.task_spec.target_url)

            # Main execution loop
            while self.current_step < self.task_spec.max_steps:
                self.current_step += 1

                try:
                    # Check for lifecycle events
                    await self.lifecycle_hooks.handle_page_events(page)

                    # Get current page state
                    page_state = await self.context_manager.get_page_state(page)

                    # Here we would normally call LLM to plan next step
                    # For now, simple example: just extract page content
                    extracted = await self.tool_registry.extract_data(page)
                    if extracted:
                        self.extracted_data[f"step_{self.current_step}"] = extracted

                    # Log step
                    await self.evaluation_logger.log_step(
                        step=self.current_step,
                        url=page.url,
                        action="extract_data",
                        target="page_content",
                        result="success",
                        screenshot_path=None
                    )

                    # Check if task is complete
                    if await self._is_task_complete(page):
                        result.status = "success"
                        break

                except Exception as e:
                    error_info = {
                        "step": self.current_step,
                        "error": str(e),
                        "recovery": "retrying"
                    }
                    self.errors.append(error_info)

                    # Take screenshot on error
                    screenshot_path = os.path.join(
                        self.task_spec.output_dir,
                        f"error_step_{self.current_step}.png"
                    )
                    await page.screenshot(path=screenshot_path)
                    self.screenshots.append(screenshot_path)

                    await self.evaluation_logger.log_step(
                        step=self.current_step,
                        url=page.url,
                        action="error",
                        target="unknown",
                        result=str(e),
                        screenshot_path=screenshot_path
                    )

                    # Recovery: reload page
                    await page.reload()
                    await self.lifecycle_hooks.wait_for_page_load(page)

            result.status = "partial" if self.current_step >= self.task_spec.max_steps else result.status

        except Exception as e:
            error_info = {
                "step": self.current_step,
                "error": f"Fatal error: {str(e)}",
                "recovery": "failed"
            }
            self.errors.append(error_info)
            result.status = "failed"

        finally:
            # Finalize results
            result.extracted_data = self.extracted_data
            result.screenshots = self.screenshots
            result.downloads = self.downloads
            result.errors = self.errors
            result.trajectory = self.trajectory_file

            # Cleanup
            if self.context_manager:
                await self.context_manager.cleanup()

        return result

    async def _is_task_complete(self, page: Page) -> bool:
        """Simple check if task is complete - override for specific tasks"""
        # This would normally be determined by LLM based on task description
        # For now, just return True after 5 steps
        return self.current_step >= 5