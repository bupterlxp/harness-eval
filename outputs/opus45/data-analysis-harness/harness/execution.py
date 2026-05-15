"""
E - Execution Loop

Analysis state machine with:
- INIT → LOAD → QUALITY_CHECK → PREPROCESS → EXPLORE → TREND → REGION → CATEGORY → CHANNEL → VALIDATE → REPORT → COMPLETE
- Each state declares input/output variables and validation conditions
- Supports rollback to any previous state
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from harness.context import ContextManager
from harness.evaluation import EvaluationInterface
from harness.lifecycle import HookType, LifecycleHooks
from harness.schemas import (
    AnalysisState,
    AnalysisStep,
    ChartRecord,
    Insight,
    STEP_REQUIREMENTS,
    StepRequirement,
    ValidationResult,
)
from harness.state import ExecutionState
from harness.tools import ToolRegistry


@dataclass
class StepResult:
    """Result of executing a step."""
    success: bool
    outputs: dict[str, Any]
    findings: list[str]
    charts: list[ChartRecord]
    insights: list[Insight]
    validation_results: list[ValidationResult]
    error: str | None = None


StepHandler = Callable[["ExecutionLoop", dict[str, Any]], StepResult]


class ExecutionLoop:
    """
    Analysis execution state machine.

    Manages transitions between analysis states, ensuring proper
    sequencing and variable dependencies.
    """

    def __init__(
        self,
        state: ExecutionState,
        context: ContextManager,
        tools: ToolRegistry,
        hooks: LifecycleHooks,
        evaluation: EvaluationInterface,
    ):
        self.state = state
        self.context = context
        self.tools = tools
        self.hooks = hooks
        self.evaluation = evaluation

        self._handlers: dict[AnalysisState, StepHandler] = {}
        self._requirements = STEP_REQUIREMENTS

    def register_handler(self, state: AnalysisState, handler: StepHandler) -> None:
        """Register a handler for a state."""
        self._handlers[state] = handler

    def get_current_state(self) -> AnalysisState:
        """Get current analysis state."""
        return self.state.current_state

    def can_transition_to(self, target: AnalysisState) -> tuple[bool, str]:
        """Check if transition to target state is valid."""
        current = self.state.current_state
        current_idx = AnalysisState.get_order().index(current)
        target_idx = AnalysisState.get_order().index(target)

        if target_idx == current_idx + 1:
            req = self._requirements.get(target)
            if req:
                missing = []
                for var in req.required_input_vars:
                    if not self.state.has_variable(var):
                        missing.append(var)
                if missing:
                    return False, f"Missing required variables: {', '.join(missing)}"
            return True, ""

        if target_idx < current_idx:
            if self.state.can_rollback_to(target_idx):
                return True, "Rollback available"
            return False, "No snapshot available for rollback"

        if target_idx > current_idx + 1:
            return False, "Cannot skip states"

        return True, ""

    def transition_to(self, target: AnalysisState) -> bool:
        """Transition to a target state."""
        can_transition, reason = self.can_transition_to(target)
        if not can_transition:
            return False

        current_idx = AnalysisState.get_order().index(self.state.current_state)
        target_idx = AnalysisState.get_order().index(target)

        if target_idx < current_idx:
            return self.state.rollback_to_state(target)

        self.state.transition_to(target)
        return True

    def execute_state(self, state: AnalysisState) -> StepResult:
        """Execute a single state."""
        handler = self._handlers.get(state)
        if not handler:
            return StepResult(
                success=False,
                outputs={},
                findings=[],
                charts=[],
                insights=[],
                validation_results=[],
                error=f"No handler registered for state: {state.value}"
            )

        req = self._requirements.get(state)
        if not req:
            return StepResult(
                success=False,
                outputs={},
                findings=[],
                charts=[],
                insights=[],
                validation_results=[],
                error=f"No requirements defined for state: {state.value}"
            )

        input_vars = {}
        for var_name in req.required_input_vars:
            value = self.state.get_variable(var_name)
            if value is None and var_name != "config":
                return StepResult(
                    success=False,
                    outputs={},
                    findings=[],
                    charts=[],
                    insights=[],
                    validation_results=[],
                    error=f"Required input variable not found: {var_name}"
                )
            input_vars[var_name] = value

        pre_results = self.hooks.execute_pre_execute(
            state, self.state.step_number + 1, input_vars
        )
        errors = [r for r in pre_results if not r.passed and r.severity == "error"]
        if errors:
            return StepResult(
                success=False,
                outputs={},
                findings=[],
                charts=[],
                insights=[],
                validation_results=pre_results,
                error=f"Pre-execute check failed: {errors[0].message}"
            )

        step = self.state.start_step(
            state=state,
            description=req.description,
            input_vars=req.required_input_vars,
            output_vars=req.produced_output_vars,
            validation_conditions=req.validation_conditions,
        )

        self.evaluation.start_step(
            step_number=step.step_number,
            state=state,
            action=req.description,
            input_vars=input_vars,
        )

        try:
            result = handler(self, input_vars)
        except Exception as e:
            error_results = self.hooks.execute_on_error(
                state, step.step_number, self.state.variables, e
            )
            self.state.complete_step(step, success=False, error=str(e))
            self.evaluation.end_step(success=False, error=str(e))
            return StepResult(
                success=False,
                outputs={},
                findings=[],
                charts=[],
                insights=[],
                validation_results=error_results,
                error=str(e)
            )

        for var_name, value in result.outputs.items():
            self.state.set_variable(var_name, value)

        for chart in result.charts:
            self.state.add_chart(chart)
            self.context.add_chart(chart)
            self.evaluation.record_chart(chart)

        for insight in result.insights:
            self.state.add_insight(insight)
            self.context.add_insight(insight)
            self.evaluation.record_insight(insight)

        self.evaluation.record_outputs(result.outputs)

        post_results = self.hooks.execute_post_execute(
            state, step.step_number, self.state.variables, req.produced_output_vars
        )
        all_validation = result.validation_results + post_results
        self.evaluation.record_validation(all_validation)

        post_errors = [r for r in post_results if not r.passed and r.severity == "error"]
        if post_errors:
            self.state.complete_step(step, success=False, error=post_errors[0].message)
            self.evaluation.end_step(success=False, error=post_errors[0].message)
            result.success = False
            result.error = post_errors[0].message
            result.validation_results = all_validation
            return result

        self.state.complete_step(step, success=True, findings=result.findings)
        self.context.add_step(step)
        for finding in result.findings:
            self.context.add_finding(state, finding)

        self.evaluation.end_step(success=True)
        result.validation_results = all_validation
        return result

    def execute_until(self, target: AnalysisState) -> list[StepResult]:
        """Execute states until reaching target state."""
        results = []
        order = AnalysisState.get_order()
        current_idx = order.index(self.state.current_state)
        target_idx = order.index(target)

        if target_idx < current_idx:
            if not self.state.rollback_to_state(target):
                return [StepResult(
                    success=False,
                    outputs={},
                    findings=[],
                    charts=[],
                    insights=[],
                    validation_results=[],
                    error=f"Cannot rollback to {target.value}"
                )]
            return results

        for i in range(current_idx + 1, target_idx + 1):
            state = order[i]
            result = self.execute_state(state)
            results.append(result)
            if not result.success:
                break

        return results

    def execute_all(self) -> list[StepResult]:
        """Execute all states until completion."""
        return self.execute_until(AnalysisState.COMPLETE)

    def rollback_to(self, target: AnalysisState) -> bool:
        """Rollback to a specific state."""
        return self.state.rollback_to_state(target)

    def rollback_to_step(self, step_number: int) -> bool:
        """Rollback to after a specific step."""
        return self.state.rollback_to_step(step_number)

    def get_available_rollback_points(self) -> list[tuple[int, AnalysisState, str]]:
        """Get available rollback points."""
        return self.state.get_available_rollback_points()

    def get_next_state(self) -> AnalysisState | None:
        """Get the next state to execute."""
        return self.state.current_state.next_state()

    def is_complete(self) -> bool:
        """Check if analysis is complete."""
        return self.state.current_state == AnalysisState.COMPLETE

    def get_progress(self) -> dict[str, Any]:
        """Get execution progress."""
        order = AnalysisState.get_order()
        current_idx = order.index(self.state.current_state)
        return {
            "current_state": self.state.current_state.value,
            "step_number": self.state.step_number,
            "progress_percent": (current_idx / (len(order) - 1)) * 100,
            "completed_states": [s.value for s in order[:current_idx]],
            "remaining_states": [s.value for s in order[current_idx + 1:]],
        }

    def re_execute_state(self, state: AnalysisState) -> StepResult:
        """Re-execute a specific state (rollback then execute)."""
        prev_state = state.previous_state()
        if prev_state and not self.rollback_to(prev_state):
            return StepResult(
                success=False,
                outputs={},
                findings=[],
                charts=[],
                insights=[],
                validation_results=[],
                error=f"Cannot rollback to {prev_state.value if prev_state else 'initial'}"
            )

        return self.execute_state(state)
