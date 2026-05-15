"""
context.py - Context management for the browser agent harness.

Implements three-layer context:
- PageContext: Current page URL, DOM summary, interactable elements
- TaskContext: Completed steps, extracted data, pending steps
- NavigationHistory: Page visit history for back navigation decisions
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from harness.schemas import InteractableElement, PageState, StepStatus, TaskStep


@dataclass
class NavigationEntry:
    """Single navigation history entry."""
    url: str
    title: str
    timestamp: datetime = field(default_factory=datetime.now)
    step_id: int | None = None


class PageContext:
    """
    Manages current page state and DOM summary.

    Never stores full DOM - only extracts relevant interactable elements
    and key text content for LLM context efficiency.
    """

    def __init__(self) -> None:
        self._current_state: PageState | None = None
        self._popup_visible: bool = False
        self._popup_type: str | None = None

    def update(self, state: PageState) -> None:
        """Update current page state."""
        self._current_state = state
        self._popup_visible = state.has_popup
        self._popup_type = state.popup_type

    @property
    def current_url(self) -> str | None:
        """Get current page URL."""
        return self._current_state.url if self._current_state else None

    @property
    def current_title(self) -> str | None:
        """Get current page title."""
        return self._current_state.title if self._current_state else None

    @property
    def has_popup(self) -> bool:
        """Check if popup is visible."""
        return self._popup_visible

    @property
    def popup_type(self) -> str | None:
        """Get popup type if visible."""
        return self._popup_type if self._popup_visible else None

    def set_popup_state(self, visible: bool, popup_type: str | None = None) -> None:
        """Update popup visibility state."""
        self._popup_visible = visible
        self._popup_type = popup_type if visible else None
        if self._current_state:
            self._current_state.has_popup = visible
            self._current_state.popup_type = popup_type

    def get_elements(self) -> list[InteractableElement]:
        """Get interactable elements on current page."""
        if not self._current_state:
            return []
        return self._current_state.interactable_elements

    def find_element_by_text(self, text: str) -> InteractableElement | None:
        """Find element by text content."""
        for el in self.get_elements():
            if el.text and text in el.text:
                return el
        return None

    def find_element_by_placeholder(self, placeholder: str) -> InteractableElement | None:
        """Find element by placeholder."""
        for el in self.get_elements():
            if el.placeholder and placeholder in el.placeholder:
                return el
        return None

    def find_element_by_id(self, element_id: str) -> InteractableElement | None:
        """Find element by ID."""
        for el in self.get_elements():
            if el.element_id == element_id:
                return el
        return None

    def find_element_by_selector(self, selector: str) -> InteractableElement | None:
        """Find element by CSS selector."""
        for el in self.get_elements():
            if el.selector == selector:
                return el
        return None

    def get_key_content(self, key: str) -> str | None:
        """Get specific key content from page."""
        if not self._current_state:
            return None
        return self._current_state.key_text_content.get(key)

    def get_summary(self) -> str:
        """Get page summary for LLM context."""
        if not self._current_state:
            return "No page loaded"
        return self._current_state.to_summary()

    def to_dict(self) -> dict[str, Any]:
        """Serialize current state."""
        if not self._current_state:
            return {}
        return self._current_state.to_dict()


class TaskContext:
    """
    Manages task execution context.

    Tracks completed steps, pending steps, and extracted data
    across the entire task execution.
    """

    def __init__(self) -> None:
        self._steps: dict[int, TaskStep] = {}
        self._extracted_data: dict[str, Any] = {}
        self._current_step_id: int | None = None

    def add_step(self, step: TaskStep) -> None:
        """Add a step to context."""
        self._steps[step.step_id] = step

    def get_step(self, step_id: int) -> TaskStep | None:
        """Get step by ID."""
        return self._steps.get(step_id)

    def set_current_step(self, step_id: int | None) -> None:
        """Set currently executing step."""
        self._current_step_id = step_id

    @property
    def current_step(self) -> TaskStep | None:
        """Get currently executing step."""
        if self._current_step_id is None:
            return None
        return self._steps.get(self._current_step_id)

    def get_completed_steps(self) -> list[TaskStep]:
        """Get all completed steps."""
        return [s for s in self._steps.values() if s.status == StepStatus.COMPLETED]

    def get_pending_steps(self) -> list[TaskStep]:
        """Get all pending steps."""
        return [s for s in self._steps.values() if s.status == StepStatus.PENDING]

    def get_failed_steps(self) -> list[TaskStep]:
        """Get all failed steps."""
        return [s for s in self._steps.values() if s.status == StepStatus.FAILED]

    def store_extracted_data(self, key: str, value: Any) -> None:
        """Store extracted data."""
        self._extracted_data[key] = value

    def get_extracted_data(self, key: str) -> Any | None:
        """Get extracted data by key."""
        return self._extracted_data.get(key)

    def get_all_extracted_data(self) -> dict[str, Any]:
        """Get all extracted data."""
        return dict(self._extracted_data)

    def get_summary(self) -> str:
        """Get task context summary for LLM."""
        completed = len(self.get_completed_steps())
        pending = len(self.get_pending_steps())
        failed = len(self.get_failed_steps())
        current = self.current_step

        lines = [
            f"Task Progress: {completed} completed, {pending} pending, {failed} failed",
        ]

        if current:
            lines.append(f"Current Step: {current.step_id} - {current.action}")

        if self._extracted_data:
            lines.append("Extracted Data Keys: " + ", ".join(self._extracted_data.keys()))

        return "\n".join(lines)


class NavigationHistory:
    """
    Tracks page navigation history for back navigation decisions.
    """

    def __init__(self, max_entries: int = 50) -> None:
        self._history: list[NavigationEntry] = []
        self._max_entries = max_entries

    def push(
        self,
        url: str,
        title: str,
        step_id: int | None = None,
    ) -> None:
        """Record a navigation event."""
        entry = NavigationEntry(url=url, title=title, step_id=step_id)
        self._history.append(entry)

        # Trim history if needed
        if len(self._history) > self._max_entries:
            self._history = self._history[-self._max_entries:]

    def get_previous(self) -> NavigationEntry | None:
        """Get previous navigation entry."""
        if len(self._history) < 2:
            return None
        return self._history[-2]

    def get_current(self) -> NavigationEntry | None:
        """Get current navigation entry."""
        if not self._history:
            return None
        return self._history[-1]

    def can_go_back(self) -> bool:
        """Check if back navigation is possible."""
        return len(self._history) >= 2

    def get_history(self, limit: int = 10) -> list[NavigationEntry]:
        """Get recent navigation history."""
        return self._history[-limit:]

    def find_by_url(self, url: str) -> NavigationEntry | None:
        """Find most recent entry for a URL."""
        for entry in reversed(self._history):
            if entry.url == url:
                return entry
        return None

    def clear(self) -> None:
        """Clear navigation history."""
        self._history.clear()

    def to_summary(self) -> str:
        """Get navigation summary for context."""
        if not self._history:
            return "No navigation history"

        lines = ["Recent Navigation:"]
        for entry in self._history[-5:]:
            step_info = f" (Step {entry.step_id})" if entry.step_id else ""
            lines.append(f"  - {entry.url} '{entry.title}'{step_info}")

        return "\n".join(lines)


class ContextManager:
    """
    Unified context manager combining all three context layers.
    """

    def __init__(self) -> None:
        self.page = PageContext()
        self.task = TaskContext()
        self.navigation = NavigationHistory()

    def on_page_load(
        self,
        state: PageState,
        step_id: int | None = None,
    ) -> None:
        """Handle page load event."""
        self.page.update(state)
        self.navigation.push(
            url=state.url,
            title=state.title,
            step_id=step_id,
        )

    def get_full_context(self) -> str:
        """Get full context summary for LLM."""
        return "\n\n".join([
            "=== Page Context ===",
            self.page.get_summary(),
            "",
            "=== Task Context ===",
            self.task.get_summary(),
            "",
            "=== Navigation History ===",
            self.navigation.to_summary(),
        ])

    def to_dict(self) -> dict[str, Any]:
        """Serialize all contexts."""
        return {
            "page": self.page.to_dict(),
            "task": self.task.get_all_extracted_data(),
            "navigation": [
                {
                    "url": e.url,
                    "title": e.title,
                    "step_id": e.step_id,
                }
                for e in self.navigation.get_history()
            ],
        }
