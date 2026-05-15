"""
Execution state machine implementation.
"""

import enum
import time
from typing import Dict, List, Optional, Any, Callable

from .state import StateStore, BugReport
from .tools import ToolRegistry, ToolResult
from .context import ContextManager
from .lifecycle import LifecycleHooks
from .evaluation import TrajectoryRecorder


class AgentState(enum.Enum):
    """Enumeration of all possible agent states."""
    INIT = "INIT
    INDEX = "INDEX"
    TEST = "TEST"
    CLASSIFY = "CLASSIFY"
    PRIORITIZE = "PRIORITIZE"
    FIX_LOOP = "FIX_LOOP"
    LOCATE = "LOCATE"
    ANALYZE = "ANALYZE"
    FIX = "FIX"
    VERIFY = "VERIFY"
    COMMIT = "COMMIT"
    REGRESSION = "REGRESSION"
    REPORT = "REPORT"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ExecutionStateMachine:
    """Main execution state machine."""

    def __init__(self,
                 state_store: StateStore,
                 tool_registry: ToolRegistry,
                 context_manager: ContextManager,
                 lifecycle_hooks: LifecycleHooks,
                 trajectory_recorder: TrajectoryRecorder):
        self.state_store = state_store
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.lifecycle_hooks = lifecycle_hooks
        self.trajectory_recorder = trajectory_recorder

        self.current_state = AgentState.INIT
        self.transitions: Dict[AgentState, List[Callable[[], Optional[AgentState]]]] = {}
        self.setup_default_transitions()

        # Current bug being fixed
        self.current_bug: Optional[BugReport] = None
        self.fix_attempts: int = 0

    def setup_default_transitions(self) -> None:
        """Setup default state transitions."""

        # INIT -> INDEX
        self.add_transition(AgentState.INIT, self._transition_to_index)

        # INDEX -> TEST
        self.add_transition(AgentState.INDEX, self._transition_to_test)

        # TEST -> CLASSIFY
        self.add_transition(AgentState.TEST, self._transition_to_classify)

        # CLASSIFY -> PRIORITIZE
        self.add_transition(AgentState.CLASSIFY, self._transition_to_prioritize)

        # PRIORITIZE -> FIX_LOOP
        self.add_transition(AgentState.PRIORITIZE, self._transition_to_fix_loop)

        # FIX_LOOP steps
        self.add_transition(AgentState.FIX_LOOP, self._transition_to_locate)
        self.add_transition(AgentState.LOCATE, self._transition_to_analyze)
        self.add_transition(AgentState.ANALYZE, self._transition_to_fix)
        self.add_transition(AgentState.FIX, self._transition_to_verify)
        self.add_transition(AgentState.VERIFY, self._handle_verify_result)
        self.add_transition(AgentState.COMMIT, self._transition_to_commit)

        # After fix loop transitions
        self.add_transition(AgentState.COMMIT, self._continue_fix_loop)

        # All states -> REGRESSION when done
        self.add_transition(AgentState.FIX_LOOP, self._transition_to_regression)
        self.add_transition(AgentState.REGRESSION, self._transition_to_report)
        self.add_transition(AgentState.REPORT, self._transition_to_completed)

    def add_transition(self, from_state: AgentState, transition_func: Callable[[], Optional[AgentState]]) -> None:
        """Add a transition from one state to another."""
        if from_state not in self.transitions:
            self.transitions[from_state] = []
        self.transitions[from_state].append(transition_func)

    def run(self) -> None:
        """Run the state machine until completion."""
        while self.current_state != AgentState.COMPLETED and self.current_state != AgentState.ERROR:
            self.step()

    def step(self) -> None:
        """Execute one step of the state machine."""
        start_time = time.time()

        try:
            current_state_enum = self.current_state
            if current_state_enum not in self.transitions:
                raise ValueError(f"No transitions defined for state: {current_state_enum}")

            # Execute all transitions for current state
            for transition in self.transitions[current_state_enum]:
                next_state = transition()
                if next_state is not None:
                    self.current_state = next_state
                    break

            duration = time.time() - start_time
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action=f"Executed step in {duration:.2f}s",
                duration=duration
            )

        except Exception as e:
            duration = time.time() - start_time
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action=f"ERROR: {str(e)}",
                duration=duration
            )
            self.current_state = AgentState.ERROR

    def _transition_to_index(self) -> AgentState:
        """Transition to INDEX state - code indexing."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Indexing codebase and identifying files"
        )
        # Implement code indexing logic here
        return AgentState.TEST

    def _transition_to_test(self) -> AgentState:
        """Transition to TEST state - run initial test suite."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Running initial test suite"
        )
        # Run tests
        result = self.tool_registry.execute_tool("test_runner")
        if result.success:
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action="Tests passed successfully
            )
        else:
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action=f"Tests failed: {result.error}"
            )
        return AgentState.CLASSIFY

    def _transition_to_classify(self) -> AgentState:
        """Transition to CLASSIFY state - classify test failures."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Classifying test failures"
        )
        # Implement test failure classification
        return AgentState.PRIORITIZE
        return AgentState.PRIORITIZE

    def _transition_to_prioritize(self) -> AgentState:
        """Transition to PRIORITIZE state - prioritize bugs."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Prioritizing identified bugs"
        )
        # Implement bug prioritization logic
        return AgentState.FIX_LOOP

    def _transition_to_fix_loop(self) -> AgentState:
        """Transition to FIX_LOOP state - start fix loop."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Starting fix loop"
        )
        return AgentState.LOCATE

    def _transition_to_locate(self) -> AgentState:
        """Transition to LOCATE state - locate bugs."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Locating bugs in code"
        )
        # Implement bug location logic
        return AgentState.ANALYZE

    def _transition_to_analyze(self) -> AgentState:
        """Transition to ANALYZE state - analyze bug."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Analyzing identified bug"
        )
        # Implement bug analysis logic
        return AgentState.FIX

    def _transition_to_fix(self) -> AgentState:
        """Transition to FIX state - apply fix."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Applying fix to code"
        )
        # Implement fix application
        return AgentState.VERIFY

    def _transition_to_verify(self) -> AgentState:
        """Transition to VERIFY state - verify fix."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Verifying fix with tests"
        )
        # Implement fix verification
        return AgentState.COMMIT

    def _handle_verify_result(self) -> Optional[AgentState]:
        """Handle the result of verification."""
        # If verification failed, go back to ANALYZE
        return AgentState.COMMIT

    def _transition_to_commit(self) -> AgentState:
        """Transition to COMMIT state - commit fix."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Committing fix to version control"
        )
        # Implement commit logic
        return AgentState.FIX_LOOP

    def _continue_fix_loop(self) -> Optional[AgentState]:
        """Continue fix loop or move to regression."""
        # Check if all bugs are fixed
        bugs = self.state_store.bug_tracker.list_bugs()
        fixed_bugs = [b for b in bugs if b.status == "fixed"]
        if len(fixed_bugs) == len(bugs):
            return AgentState.REGRESSION
        return None

    def _transition_to_regression(self) -> AgentState:
        """Transition to REGRESSION state - run full regression tests."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Running full regression test suite"
        )
        # Run full regression tests
        result = self.tool_registry.execute_tool("test_runner")
        if result.success:
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action="Regression tests passed successfully"
            )
        else:
            self.trajectory_recorder.add_step(
                state=self.current_state.value,
                action=f"Regression tests failed: {result.error}"
            )
        return AgentState.REPORT

    def _transition_to_report(self) -> AgentState:
        """Transition to REPORT state - generate report."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Generating final repair report"
        )
        # Generate final report
        return AgentState.COMPLETED

    def _transition_to_completed(self) -> AgentState:
        """Transition to COMPLETED state - final cleanup."""
        self.trajectory_recorder.add_step(
            state=self.current_state.value,
            action="Execution completed successfully"
        )
        return AgentState.COMPLETED


def create_execution_state_machine(config: Dict[str, Any] = None) -> ExecutionStateMachine:
    """Create and configure an execution state machine."""
    from .state import StateStore
    from .tools import ToolRegistry
    from .context import ContextManager
    from .lifecycle import LifecycleHooks
    from .evaluation import TrajectoryRecorder

    # Create default components
    state_store = StateStore()
    tool_registry = ToolRegistry()
    context_manager = ContextManager()
    lifecycle_hooks = LifecycleHooks(state_store)
    trajectory_recorder = TrajectoryRecorder()

    # Configure tools
    from .tools import FileSearchTool, FileEditorTool, TestRunnerTool, GitTool, StaticAnalysisTool
    tool_registry.register_tool(FileSearchTool())
    tool_registry.register_tool(FileEditorTool())
    tool_registry.register_tool(TestRunnerTool())
    tool_registry.register_tool(GitTool())
    tool_registry.register_tool(StaticAnalysisTool())

    # Configure lifecycle hooks
    lifecycle_hooks.setup_default_hooks()

    return ExecutionStateMachine(
        state_store=state_store,
        tool_registry=tool_registry,
        context_manager=context_manager,
        lifecycle_hooks=lifecycle_hooks,
        trajectory_recorder=trajectory_recorder
    )