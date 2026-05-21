"""Evaluation (V) - Operation trajectory recording.

Records each step in JSONL format including URL, action type, target element,
result, and screenshot path.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """A single entry in the operation trajectory."""
    step_id: int
    timestamp: str
    url: str
    action_type: str
    action_params: dict[str, Any]
    target_element: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None
    screenshot_path: str | None = None
    page_context_summary: str | None = None
    llm_reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class TrajectoryRecorder:
    """Records operation trajectories in JSONL format.

    Each step records:
    - URL at time of action
    - Action type and parameters
    - Target element (if any)
    - Result of the action
    - Screenshot path (if captured)
    """

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory_file = self.output_dir / "trajectory.jsonl"
        self._entries: list[TrajectoryEntry] = []
        self._step_counter = 0

    def record(
        self,
        url: str,
        action_type: str,
        action_params: dict[str, Any],
        target_element: str | None = None,
        result: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        screenshot_path: str | None = None,
        page_context_summary: str | None = None,
        llm_reasoning: str | None = None,
    ) -> TrajectoryEntry:
        """Record a single trajectory entry."""
        self._step_counter += 1

        entry = TrajectoryEntry(
            step_id=self._step_counter,
            timestamp=datetime.utcnow().isoformat(),
            url=url,
            action_type=action_type,
            action_params=action_params,
            target_element=target_element,
            result=result or {},
            success=success,
            error=error,
            screenshot_path=screenshot_path,
            page_context_summary=page_context_summary,
            llm_reasoning=llm_reasoning,
        )

        self._entries.append(entry)
        self._append_to_file(entry)

        return entry

    def _append_to_file(self, entry: TrajectoryEntry) -> None:
        """Append entry to JSONL file."""
        with open(self.trajectory_file, "a") as f:
            f.write(entry.to_jsonl() + "\n")

    def record_navigation(
        self,
        url: str,
        target_url: str,
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record a navigation action."""
        return self.record(
            url=url,
            action_type="navigate",
            action_params={"target_url": target_url},
            success=success,
            error=error,
        )

    def record_click(
        self,
        url: str,
        selector: str,
        element_description: str | None = None,
        success: bool = True,
        error: str | None = None,
        screenshot_path: str | None = None,
    ) -> TrajectoryEntry:
        """Record a click action."""
        return self.record(
            url=url,
            action_type="click",
            action_params={"selector": selector},
            target_element=element_description or selector,
            success=success,
            error=error,
            screenshot_path=screenshot_path,
        )

    def record_type(
        self,
        url: str,
        selector: str,
        text: str,
        element_description: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record a text input action."""
        return self.record(
            url=url,
            action_type="type_text",
            action_params={"selector": selector, "text": text[:50] + "..." if len(text) > 50 else text},
            target_element=element_description or selector,
            success=success,
            error=error,
        )

    def record_extraction(
        self,
        url: str,
        extraction_type: str,
        selector: str | None,
        data: dict[str, Any],
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record a data extraction action."""
        return self.record(
            url=url,
            action_type=f"extract_{extraction_type}",
            action_params={"selector": selector} if selector else {},
            result=data,
            success=success,
            error=error,
        )

    def record_screenshot(
        self,
        url: str,
        screenshot_path: str,
        reason: str = "manual",
    ) -> TrajectoryEntry:
        """Record a screenshot capture."""
        return self.record(
            url=url,
            action_type="screenshot",
            action_params={"reason": reason},
            screenshot_path=screenshot_path,
        )

    def record_error(
        self,
        url: str,
        action_type: str,
        action_params: dict[str, Any],
        error: str,
        recovery_action: str,
        screenshot_path: str | None = None,
    ) -> TrajectoryEntry:
        """Record an error and recovery attempt."""
        return self.record(
            url=url,
            action_type=action_type,
            action_params=action_params,
            success=False,
            error=error,
            result={"recovery": recovery_action},
            screenshot_path=screenshot_path,
        )

    def record_llm_decision(
        self,
        url: str,
        reasoning: str,
        decided_action: str,
        action_params: dict[str, Any],
        page_context_summary: str | None = None,
    ) -> TrajectoryEntry:
        """Record an LLM decision step."""
        return self.record(
            url=url,
            action_type="llm_decision",
            action_params={"decided_action": decided_action, **action_params},
            llm_reasoning=reasoning,
            page_context_summary=page_context_summary,
        )

    def record_task_event(
        self,
        url: str,
        event_type: str,
        details: dict[str, Any],
    ) -> TrajectoryEntry:
        """Record a task-level event (start, complete, fail)."""
        return self.record(
            url=url,
            action_type=f"task_{event_type}",
            action_params=details,
        )

    def get_entries(self) -> list[TrajectoryEntry]:
        """Get all recorded entries."""
        return self._entries.copy()

    def get_trajectory_path(self) -> str:
        """Get the path to the trajectory file."""
        return str(self.trajectory_file)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the trajectory."""
        if not self._entries:
            return {
                "total_steps": 0,
                "successful_steps": 0,
                "failed_steps": 0,
                "action_types": {},
            }

        action_counts: dict[str, int] = {}
        success_count = 0
        fail_count = 0

        for entry in self._entries:
            action_counts[entry.action_type] = action_counts.get(entry.action_type, 0) + 1
            if entry.success:
                success_count += 1
            else:
                fail_count += 1

        return {
            "total_steps": len(self._entries),
            "successful_steps": success_count,
            "failed_steps": fail_count,
            "action_types": action_counts,
            "first_url": self._entries[0].url if self._entries else None,
            "last_url": self._entries[-1].url if self._entries else None,
        }

    def load_from_file(self) -> list[TrajectoryEntry]:
        """Load entries from the trajectory file."""
        entries = []
        if self.trajectory_file.exists():
            with open(self.trajectory_file, "r") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        entries.append(TrajectoryEntry(**data))
        self._entries = entries
        if entries:
            self._step_counter = max(e.step_id for e in entries)
        return entries

    def clear(self) -> None:
        """Clear all entries and reset the file."""
        self._entries.clear()
        self._step_counter = 0
        if self.trajectory_file.exists():
            self.trajectory_file.unlink()
