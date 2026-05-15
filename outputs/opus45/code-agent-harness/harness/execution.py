"""
E component - Execution Loop with explicit state machine.

States:
- INDEX: Scan project structure
- TEST: Run initial tests
- CLASSIFY: Classify failures by root cause
- PRIORITIZE: Order bugs by severity
- FIX_LOOP: Nested state machine for fixing each bug
  - LOCATE: Find bug location
  - ANALYZE: Understand root cause
  - FIX: Apply fix
  - VERIFY: Run tests to verify
  - COMMIT: Commit the fix
- REGRESSION: Run full test suite
- REPORT: Generate final report

Transition function δ covers all events including exceptions.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional, Protocol
from pathlib import Path

from harness.schemas import BugReport, BugStatus, TestResult


class MainState(Enum):
    """Main execution states."""
    IDLE = auto()
    INDEX = auto()
    TEST = auto()
    CLASSIFY = auto()
    PRIORITIZE = auto()
    FIX_LOOP = auto()
    REGRESSION = auto()
    REPORT = auto()
    COMPLETED = auto()
    FAILED = auto()


class FixState(Enum):
    """Nested fix loop states."""
    LOCATE = auto()
    ANALYZE = auto()
    FIX = auto()
    VERIFY = auto()
    COMMIT = auto()
    DONE = auto()
    BLOCKED = auto()


class Event(Enum):
    """Events that trigger state transitions."""
    START = auto()
    INDEX_COMPLETE = auto()
    TEST_COMPLETE = auto()
    CLASSIFY_COMPLETE = auto()
    PRIORITIZE_COMPLETE = auto()
    BUG_SELECTED = auto()
    LOCATE_COMPLETE = auto()
    ANALYZE_COMPLETE = auto()
    FIX_APPLIED = auto()
    VERIFY_PASSED = auto()
    VERIFY_FAILED = auto()
    COMMIT_COMPLETE = auto()
    ALL_BUGS_FIXED = auto()
    REGRESSION_PASSED = auto()
    REGRESSION_FAILED = auto()
    REPORT_COMPLETE = auto()
    ERROR = auto()
    ABORT = auto()
    RETRY = auto()


@dataclass
class ExecutionContext:
    """Context passed through state machine."""
    work_dir: Path
    target_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    current_bug: Optional[BugReport] = None
    bugs: list[BugReport] = field(default_factory=list)
    test_result: Optional[TestResult] = None
    error: Optional[Exception] = None
    metadata: dict = field(default_factory=dict)


class StateHandler(Protocol):
    """Protocol for state handlers."""
    def __call__(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        ...


@dataclass
class Transition:
    """Represents a state transition."""
    from_state: MainState | FixState
    event: Event
    to_state: MainState | FixState
    action: Optional[Callable[[ExecutionContext], ExecutionContext]] = None


class FixLoopStateMachine:
    """
    Nested state machine for the fix loop.

    LOCATE → ANALYZE → FIX → VERIFY → COMMIT
                ↑         ↓
                └─────────┘ (on VERIFY_FAILED)
    """

    def __init__(self) -> None:
        self.state = FixState.LOCATE
        self._attempt_count = 0
        self._max_attempts = 3

    def reset(self) -> None:
        """Reset for a new bug."""
        self.state = FixState.LOCATE
        self._attempt_count = 0

    def step(self, event: Event) -> FixState:
        """Execute state transition."""
        match (self.state, event):
            case (FixState.LOCATE, Event.LOCATE_COMPLETE):
                self.state = FixState.ANALYZE
            case (FixState.ANALYZE, Event.ANALYZE_COMPLETE):
                self.state = FixState.FIX
            case (FixState.FIX, Event.FIX_APPLIED):
                self.state = FixState.VERIFY
            case (FixState.VERIFY, Event.VERIFY_PASSED):
                self.state = FixState.COMMIT
            case (FixState.VERIFY, Event.VERIFY_FAILED):
                self._attempt_count += 1
                if self._attempt_count >= self._max_attempts:
                    self.state = FixState.BLOCKED
                else:
                    self.state = FixState.ANALYZE
            case (FixState.COMMIT, Event.COMMIT_COMPLETE):
                self.state = FixState.DONE
            case (_, Event.ERROR):
                self.state = FixState.BLOCKED
            case (_, Event.ABORT):
                self.state = FixState.BLOCKED
            case _:
                pass
        return self.state

    @property
    def is_done(self) -> bool:
        return self.state == FixState.DONE

    @property
    def is_blocked(self) -> bool:
        return self.state == FixState.BLOCKED


class ExecutionStateMachine:
    """
    E component - Main execution state machine.

    Explicit state transitions via match/case.
    Nested fix loop for individual bug fixes.
    """

    def __init__(self) -> None:
        self.state = MainState.IDLE
        self.fix_loop = FixLoopStateMachine()
        self._handlers: dict[MainState, StateHandler] = {}
        self._context = ExecutionContext(work_dir=Path.cwd())

    def register_handler(self, state: MainState, handler: StateHandler) -> None:
        """Register a handler for a state."""
        self._handlers[state] = handler

    def set_context(self, ctx: ExecutionContext) -> None:
        """Set execution context."""
        self._context = ctx

    def step(self, event: Event) -> MainState:
        """
        Execute one state transition.

        Uses explicit match/case - NO while True + if chains.
        """
        match (self.state, event):
            case (MainState.IDLE, Event.START):
                self.state = MainState.INDEX

            case (MainState.INDEX, Event.INDEX_COMPLETE):
                self.state = MainState.TEST

            case (MainState.INDEX, Event.ERROR):
                self.state = MainState.FAILED

            case (MainState.TEST, Event.TEST_COMPLETE):
                self.state = MainState.CLASSIFY

            case (MainState.TEST, Event.ERROR):
                self.state = MainState.FAILED

            case (MainState.CLASSIFY, Event.CLASSIFY_COMPLETE):
                self.state = MainState.PRIORITIZE

            case (MainState.PRIORITIZE, Event.PRIORITIZE_COMPLETE):
                self.state = MainState.FIX_LOOP
                self.fix_loop.reset()

            case (MainState.FIX_LOOP, Event.BUG_SELECTED):
                self.fix_loop.reset()

            case (MainState.FIX_LOOP, event) if self._is_fix_event(event):
                fix_state = self.fix_loop.step(event)
                if self.fix_loop.is_done:
                    pass
                elif self.fix_loop.is_blocked:
                    pass

            case (MainState.FIX_LOOP, Event.ALL_BUGS_FIXED):
                self.state = MainState.REGRESSION

            case (MainState.FIX_LOOP, Event.ERROR):
                pass

            case (MainState.REGRESSION, Event.REGRESSION_PASSED):
                self.state = MainState.REPORT

            case (MainState.REGRESSION, Event.REGRESSION_FAILED):
                self.state = MainState.FIX_LOOP
                self.fix_loop.reset()

            case (MainState.REPORT, Event.REPORT_COMPLETE):
                self.state = MainState.COMPLETED

            case (_, Event.ABORT):
                self.state = MainState.FAILED

            case (_, Event.ERROR):
                self.state = MainState.FAILED

            case _:
                pass

        return self.state

    def _is_fix_event(self, event: Event) -> bool:
        """Check if event belongs to fix loop."""
        return event in {
            Event.LOCATE_COMPLETE,
            Event.ANALYZE_COMPLETE,
            Event.FIX_APPLIED,
            Event.VERIFY_PASSED,
            Event.VERIFY_FAILED,
            Event.COMMIT_COMPLETE,
            Event.RETRY,
        }

    def run_current_state(self) -> tuple[Event, ExecutionContext]:
        """Run the handler for the current state."""
        if self.state == MainState.FIX_LOOP:
            return self._run_fix_state()

        handler = self._handlers.get(self.state)
        if handler:
            try:
                event, self._context = handler(self._context)
                return event, self._context
            except Exception as e:
                self._context.error = e
                return Event.ERROR, self._context
        return Event.ERROR, self._context

    def _run_fix_state(self) -> tuple[Event, ExecutionContext]:
        """Run the appropriate fix loop state handler."""
        fix_state = self.fix_loop.state
        state_name = f"FIX_{fix_state.name}"
        handler = self._handlers.get(state_name)

        if handler:
            try:
                event, self._context = handler(self._context)
                return event, self._context
            except Exception as e:
                self._context.error = e
                return Event.ERROR, self._context

        return Event.ERROR, self._context

    @property
    def is_terminal(self) -> bool:
        """Check if in terminal state."""
        return self.state in {MainState.COMPLETED, MainState.FAILED}

    @property
    def current_fix_state(self) -> Optional[FixState]:
        """Get current fix loop state if in FIX_LOOP."""
        if self.state == MainState.FIX_LOOP:
            return self.fix_loop.state
        return None

    def get_state_info(self) -> dict:
        """Get current state information."""
        info = {
            "main_state": self.state.name,
            "is_terminal": self.is_terminal,
        }
        if self.state == MainState.FIX_LOOP:
            info["fix_state"] = self.fix_loop.state.name
            info["fix_attempts"] = self.fix_loop._attempt_count
        return info


class ExecutionLoop:
    """
    High-level execution loop that drives the state machine.

    Provides run() method that executes until terminal state.
    """

    def __init__(self, state_machine: ExecutionStateMachine) -> None:
        self._sm = state_machine
        self._running = False
        self._step_callback: Optional[Callable[[MainState, Event], None]] = None

    def set_step_callback(self, callback: Callable[[MainState, Event], None]) -> None:
        """Set callback to be called after each step."""
        self._step_callback = callback

    def run(self, ctx: ExecutionContext) -> ExecutionContext:
        """Run the state machine until terminal state."""
        self._sm.set_context(ctx)
        self._running = True

        event = Event.START
        while self._running and not self._sm.is_terminal:
            prev_state = self._sm.state
            self._sm.step(event)

            if self._step_callback:
                self._step_callback(self._sm.state, event)

            if self._sm.is_terminal:
                break

            event, ctx = self._sm.run_current_state()

        self._running = False
        return self._sm._context

    def stop(self) -> None:
        """Signal the loop to stop."""
        self._running = False

    def abort(self) -> None:
        """Abort execution."""
        self._sm.step(Event.ABORT)
        self._running = False
