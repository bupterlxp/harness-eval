import json
import os
from datetime import datetime
from typing import Dict, Any, Optional


class EvaluationLogger:
    """Logs execution trajectory in JSONL format"""

    def __init__(self, trajectory_file: str):
        self.trajectory_file = trajectory_file
        self.file_handle = None
        self._open_file()

    def _open_file(self):
        """Open the trajectory file for appending"""
        self.file_handle = open(self.trajectory_file, 'a', encoding='utf-8')

    async def log_step(self,
                      step: int,
                      url: str,
                      action: str,
                      target: str,
                      result: str,
                      screenshot_path: Optional[str] = None,
                      error: Optional[str] = None):
        """Log a single step in the trajectory"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "url": url,
            "action": action,
            "target": target,
            "result": result,
            "screenshot_path": screenshot_path,
            "error": error
        }

        if self.file_handle:
            self.file_handle.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            self.file_handle.flush()

    async def log_screenshot(self, step: int, page, screenshot_name: str) -> str:
        """Take screenshot and log it"""
        os.makedirs(os.path.dirname(self.trajectory_file), exist_ok=True)
        screenshot_path = os.path.join(
            os.path.dirname(self.trajectory_file),
            screenshot_name
        )
        await page.screenshot(path=screenshot_path)

        await self.log_step(
            step=step,
            url=page.url,
            action="screenshot",
            target="current_page",
            result="success",
            screenshot_path=screenshot_path
        )

        return screenshot_path

    def close(self):
        """Close the trajectory file"""
        if self.file_handle:
            self.file_handle.close()

    def __del__(self):
        """Destructor to ensure file is closed"""
        self.close()