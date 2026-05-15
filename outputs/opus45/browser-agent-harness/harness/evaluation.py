"""
evaluation.py - Evaluation interface for the browser agent harness.

Implements JSONL trajectory logging for:
- Step-by-step execution trace
- Tool calls and results
- Screenshots and extracted data
- Timing and retry information
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """Single entry in the execution trajectory."""
    timestamp: str
    entry_type: str  # "step_start", "step_end", "tool_call", "tool_result", "error", "screenshot", "extract"
    step_id: int | None
    url: str | None
    action: str | None
    selector: str | None = None
    tool_name: str | None = None
    tool_params: dict[str, Any] | None = None
    result: Any = None
    success: bool = True
    error_message: str | None = None
    screenshot_path: str | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


class TrajectoryLogger:
    """
    JSONL trajectory logger for execution traces.

    Each line is a self-contained JSON object representing
    one event in the execution timeline.
    """

    def __init__(
        self,
        output_dir: str = "trajectories",
        session_id: str | None = None,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file_path = self._output_dir / f"trajectory_{self._session_id}.jsonl"
        self._entries: list[TrajectoryEntry] = []
        self._step_start_times: dict[int, datetime] = {}

    @property
    def file_path(self) -> str:
        """Get the trajectory file path."""
        return str(self._file_path)

    def _write_entry(self, entry: TrajectoryEntry) -> None:
        """Write an entry to the JSONL file."""
        self._entries.append(entry)
        with open(self._file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def log_step_start(
        self,
        step_id: int,
        action: str,
        url: str | None = None,
    ) -> None:
        """Log the start of a task step."""
        self._step_start_times[step_id] = datetime.now()
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="step_start",
            step_id=step_id,
            url=url,
            action=action,
        )
        self._write_entry(entry)

    def log_step_end(
        self,
        step_id: int,
        success: bool,
        url: str | None = None,
        error_message: str | None = None,
        extracted_data: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> None:
        """Log the end of a task step."""
        duration_ms = None
        if step_id in self._step_start_times:
            delta = datetime.now() - self._step_start_times[step_id]
            duration_ms = int(delta.total_seconds() * 1000)
            del self._step_start_times[step_id]

        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="step_end",
            step_id=step_id,
            url=url,
            action=None,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
            retry_count=retry_count,
            extra={"extracted_data": extracted_data} if extracted_data else None,
        )
        self._write_entry(entry)

    def log_tool_call(
        self,
        step_id: int | None,
        tool_name: str,
        params: dict[str, Any],
        url: str | None = None,
    ) -> None:
        """Log a tool invocation."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="tool_call",
            step_id=step_id,
            url=url,
            action=None,
            tool_name=tool_name,
            tool_params=params,
        )
        self._write_entry(entry)

    def log_tool_result(
        self,
        step_id: int | None,
        tool_name: str,
        result: Any,
        success: bool = True,
        error_message: str | None = None,
        duration_ms: int | None = None,
        url: str | None = None,
    ) -> None:
        """Log the result of a tool invocation."""
        serializable_result = result
        if hasattr(result, "to_dict"):
            serializable_result = result.to_dict()
        elif not isinstance(result, (str, int, float, bool, list, dict, type(None))):
            serializable_result = str(result)

        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="tool_result",
            step_id=step_id,
            url=url,
            action=None,
            tool_name=tool_name,
            result=serializable_result,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        self._write_entry(entry)

    def log_screenshot(
        self,
        step_id: int | None,
        screenshot_path: str,
        url: str | None = None,
        description: str | None = None,
    ) -> None:
        """Log a screenshot capture."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="screenshot",
            step_id=step_id,
            url=url,
            action=description,
            screenshot_path=screenshot_path,
        )
        self._write_entry(entry)

    def log_extraction(
        self,
        step_id: int | None,
        data: dict[str, Any],
        selector: str | None = None,
        url: str | None = None,
    ) -> None:
        """Log data extraction."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="extract",
            step_id=step_id,
            url=url,
            action="extract_data",
            selector=selector,
            result=data,
        )
        self._write_entry(entry)

    def log_error(
        self,
        step_id: int | None,
        error_message: str,
        url: str | None = None,
        action: str | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        """Log an error."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="error",
            step_id=step_id,
            url=url,
            action=action,
            success=False,
            error_message=error_message,
            screenshot_path=screenshot_path,
        )
        self._write_entry(entry)

    def log_popup(
        self,
        step_id: int | None,
        popup_type: str,
        action: str,
        success: bool = True,
        url: str | None = None,
    ) -> None:
        """Log popup handling."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="popup",
            step_id=step_id,
            url=url,
            action=f"{action}_{popup_type}",
            success=success,
            extra={"popup_type": popup_type},
        )
        self._write_entry(entry)

    def log_retry(
        self,
        step_id: int | None,
        attempt: int,
        max_attempts: int,
        reason: str,
        url: str | None = None,
    ) -> None:
        """Log a retry attempt."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="retry",
            step_id=step_id,
            url=url,
            action="retry",
            retry_count=attempt,
            extra={"max_attempts": max_attempts, "reason": reason},
        )
        self._write_entry(entry)

    def log_navigation(
        self,
        step_id: int | None,
        from_url: str | None,
        to_url: str,
        success: bool = True,
        duration_ms: int | None = None,
    ) -> None:
        """Log a navigation event."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            entry_type="navigation",
            step_id=step_id,
            url=to_url,
            action="navigate",
            success=success,
            duration_ms=duration_ms,
            extra={"from_url": from_url},
        )
        self._write_entry(entry)

    def get_entries(self) -> list[TrajectoryEntry]:
        """Get all logged entries."""
        return list(self._entries)

    def get_entries_for_step(self, step_id: int) -> list[TrajectoryEntry]:
        """Get entries for a specific step."""
        return [e for e in self._entries if e.step_id == step_id]

    def get_errors(self) -> list[TrajectoryEntry]:
        """Get all error entries."""
        return [e for e in self._entries if e.entry_type == "error" or not e.success]

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the trajectory."""
        steps_started = len([e for e in self._entries if e.entry_type == "step_start"])
        steps_completed = len([e for e in self._entries if e.entry_type == "step_end" and e.success])
        steps_failed = len([e for e in self._entries if e.entry_type == "step_end" and not e.success])
        tool_calls = len([e for e in self._entries if e.entry_type == "tool_call"])
        errors = len(self.get_errors())
        screenshots = len([e for e in self._entries if e.entry_type == "screenshot"])
        retries = sum(e.retry_count for e in self._entries if e.retry_count)

        total_duration_ms = sum(
            e.duration_ms or 0
            for e in self._entries
            if e.entry_type == "step_end" and e.duration_ms
        )

        return {
            "session_id": self._session_id,
            "file_path": self.file_path,
            "total_entries": len(self._entries),
            "steps_started": steps_started,
            "steps_completed": steps_completed,
            "steps_failed": steps_failed,
            "tool_calls": tool_calls,
            "errors": errors,
            "screenshots": screenshots,
            "total_retries": retries,
            "total_duration_ms": total_duration_ms,
        }

    def export_readable(self, output_path: str | None = None) -> str:
        """Export trajectory as human-readable text."""
        lines = [
            "=" * 60,
            f"Execution Trajectory - Session {self._session_id}",
            "=" * 60,
            "",
        ]

        current_step = None
        for entry in self._entries:
            if entry.entry_type == "step_start":
                current_step = entry.step_id
                lines.append(f"\n--- Step {entry.step_id}: {entry.action} ---")
                lines.append(f"    URL: {entry.url}")

            elif entry.entry_type == "step_end":
                status = "SUCCESS" if entry.success else "FAILED"
                lines.append(f"    Status: {status}")
                if entry.duration_ms:
                    lines.append(f"    Duration: {entry.duration_ms}ms")
                if entry.error_message:
                    lines.append(f"    Error: {entry.error_message}")
                if entry.retry_count:
                    lines.append(f"    Retries: {entry.retry_count}")

            elif entry.entry_type == "tool_call":
                lines.append(f"    > {entry.tool_name}({entry.tool_params})")

            elif entry.entry_type == "tool_result":
                if entry.success:
                    result_preview = str(entry.result)[:100]
                    lines.append(f"      <- {result_preview}")
                else:
                    lines.append(f"      <- ERROR: {entry.error_message}")

            elif entry.entry_type == "screenshot":
                lines.append(f"    [Screenshot: {entry.screenshot_path}]")

            elif entry.entry_type == "extract":
                lines.append(f"    [Extracted: {list(entry.result.keys()) if isinstance(entry.result, dict) else entry.result}]")

            elif entry.entry_type == "error":
                lines.append(f"    ! ERROR: {entry.error_message}")

            elif entry.entry_type == "popup":
                lines.append(f"    [Popup: {entry.action}]")

            elif entry.entry_type == "retry":
                lines.append(f"    [Retry {entry.retry_count}: {entry.extra.get('reason', '')}]")

        lines.extend([
            "",
            "=" * 60,
            "Summary",
            "=" * 60,
        ])
        summary = self.get_summary()
        for key, value in summary.items():
            lines.append(f"  {key}: {value}")

        content = "\n".join(lines)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

        return content
