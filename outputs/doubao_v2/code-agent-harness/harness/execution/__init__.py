"""
Execution Loop component - drives task progression with explicit state machine
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from ..tools import ToolRegistry
from ..context import ContextManager
from ..state import StateStore
from ..lifecycle import LifecycleHooks
from ..evaluation import Evaluator


class ExecutionState(Enum):
    """States for the execution state machine"""
    INITIALIZED = "initialized"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    VERIFYING = "verifying"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskStep:
    """Represents a single step in the execution trajectory"""
    state: str
    action: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    result: Optional[Dict[str, Any]] = None


class ExecutionLoop:
    """
    Explicit state machine execution loop for handling software engineering tasks
    Supports nested cycles and proper state transitions
    """

    def __init__(
        self,
        state_store: StateStore,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        lifecycle_hooks: LifecycleHooks,
        evaluator: Evaluator
    ):
        self.state_store = state_store
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.lifecycle_hooks = lifecycle_hooks
        self.evaluator = evaluator

        self.current_state = ExecutionState.INITIALIZED
        self.task_spec: Optional[Dict[str, Any]] = None
        self.trajectory: List[TaskStep] = []
        self.retry_count = 0
        self.max_retries = 5
        self.max_llm_calls = 20
        self.llm_call_count = 0

    def _add_trajectory_step(self, state: ExecutionState, action: str, details: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
        """Add a step to the execution trajectory"""
        step = TaskStep(
            state=state.value,
            action=action,
            details=details,
            result=result
        )
        self.trajectory.append(step)
        self.evaluator.log_step(step)

    def _transition_state(self, new_state: ExecutionState, action: str, details: Dict[str, Any], result: Optional[Dict[str, Any]] = None):
        """Transition between states"""
        self._add_trajectory_step(new_state, action, details, result)
        self.current_state = new_state

    def run_task(self, task_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Main entry point for executing a task"""
        self.task_spec = task_spec

        try:
            # Initialize lifecycle hooks
            self.lifecycle_hooks.on_task_start(task_spec)

            # Create snapshot before starting
            self.state_store.create_snapshot("initial_state")

            # Main execution loop
            while self.current_state not in [ExecutionState.COMPLETED, ExecutionState.FAILED]:
                self._check_budget()

                if self.current_state == ExecutionState.INITIALIZED:
                    self._transition_state(
                        ExecutionState.ANALYZING,
                        "start_analysis",
                        {"task_description": task_spec["description"]}
                    )
                    self._handle_analysis()

                elif self.current_state == ExecutionState.ANALYZING:
                    self._transition_state(
                        ExecutionState.PLANNING,
                        "create_execution_plan",
                        {}
                    )
                    self._handle_planning()

                elif self.current_state == ExecutionState.PLANNING:
                    self._transition_state(
                        ExecutionState.EXECUTING,
                        "execute_plan",
                        {"retry_count": self.retry_count}
                    )
                    self._handle_execution()

                elif self.current_state == ExecutionState.EXECUTING:
                    self._transition_state(
                        ExecutionState.TESTING,
                        "run_tests",
                        {"test_command": task_spec.get("test_command")}
                    )
                    self._handle_testing()

                elif self.current_state == ExecutionState.TESTING:
                    self._transition_state(
                        ExecutionState.VERIFYING,
                        "verify_results",
                        {}
                    )
                    self._handle_verification()

                elif self.current_state == ExecutionState.VERIFYING:
                    self._handle_verification_outcome()

                elif self.current_state == ExecutionState.ROLLING_BACK:
                    self._handle_rollback()

            # Finalize and return results
            return self._generate_result()

        except Exception as e:
            self.lifecycle_hooks.on_task_failure(str(e))
            self._transition_state(ExecutionState.FAILED, "task_failed", {"error": str(e)})
            return self._generate_result(error=str(e))
        finally:
            self.lifecycle_hooks.on_task_end()

    def _check_budget(self):
        """Check execution budget limits"""
        if self.llm_call_count >= self.max_llm_calls:
            raise RuntimeError(f"Exceeded maximum LLM calls: {self.max_llm_calls}")

        if self.retry_count >= self.max_retries:
            raise RuntimeError(f"Exceeded maximum retries: {self.max_retries}")

    def _handle_analysis(self):
        """Analyze the task and understand requirements"""
        # Implementation would call LLM to understand task
        # For now, just transition to planning
        self._transition_state(
            ExecutionState.PLANNING,
            "analysis_complete",
            {"task_type": self.task_spec["task_type"]}
        )

    def _handle_planning(self):
        """Create execution plan for the task"""
        # Implementation would generate execution plan
        self._transition_state(
            ExecutionState.EXECUTING,
            "plan_created",
            {"plan_steps": ["file_search", "code_modification", "testing"]}
        )

    def _handle_execution(self):
        """Execute the planned changes"""
        # Implementation would use tools to make code changes
        self._transition_state(
            ExecutionState.TESTING,
            "execution_complete",
            {"modified_files": []}
        )

    def _handle_testing(self):
        """Run tests to verify changes"""
        # Implementation would run test commands
        test_results = {
            "passed": 0,
            "failed": 0,
            "errors": []
        }
        self._transition_state(
            ExecutionState.VERIFYING,
            "tests_completed",
            test_results
        )

    def _handle_verification(self):
        """Verify if task is completed successfully"""
        # Implementation would verify results
        self._transition_state(
            ExecutionState.VERIFYING,
            "verification_complete",
            {"success": True}
        )

    def _handle_verification_outcome(self):
        """Handle outcomes of verification"""
        # Simple example logic - would be more complex in real implementation
        self._transition_state(
            ExecutionState.COMPLETED,
            "task_successful",
            {}
        )

    def _handle_rollback(self):
        """Rollback to previous stable state"""
        self.state_store.rollback_to_last_snapshot()
        self.retry_count += 1

        if self.retry_count >= self.max_retries:
            self._transition_state(
                ExecutionState.FAILED,
                "rollback_failed_max_retries",
                {"retry_count": self.retry_count}
            )
        else:
            self._transition_state(
                ExecutionState.PLANNING,
                "rollback_complete",
                {"retry_count": self.retry_count}
            )

    def _generate_result(self, error: Optional[str] = None) -> Dict[str, Any]:
        """Generate final result in the required schema"""
        status = "success" if self.current_state == ExecutionState.COMPLETED else "failed"
        if error:
            status = "failed"

        # Collect edited files from trajectory
        edits = []
        for step in self.trajectory:
            if step.result and "modified_files" in step.result:
                for file in step.result["modified_files"]:
                    edits.append({
                        "file": file,
                        "diff": ""  # Would capture actual diff in real implementation
                    })

        # Collect test results
        test_results = {
            "passed": 0,
            "failed": 0,
            "errors": []
        }
        for step in self.trajectory:
            if step.action == "tests_completed" and step.result:
                test_results = step.result

        # Write trajectory to file
        trajectory_file = f"trajectory_{int(time.time())}.jsonl"
        with open(trajectory_file, "w") as f:
            for step in self.trajectory:
                json.dump({
                    "state": step.state,
                    "action": step.action,
                    "details": step.details,
                    "timestamp": step.timestamp,
                    "result": step.result
                }, f)
                f.write("\n")

        return {
            "status": status,
            "edits": edits,
            "test_results": test_results,
            "trajectory": trajectory_file
        }