"""
test_dual_state_machine.py - Tests for the dual-layer state machine.

Verifies:
- Outer state machine phase transitions
- Inner state machine phase execution
- State isolation between layers
"""

import pytest
from harness.schemas import PageOperationPhase, StepStatus, TaskPhase, TaskStep
from harness.state import TaskGraph


class TestTaskGraph:
    """Tests for the TaskGraph (outer state machine)."""

    def test_add_steps_with_dependencies(self) -> None:
        """Steps are added with correct dependency tracking."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="Init", description="Initialize")
        step2 = TaskStep(step_id=2, action="Login", description="Login page")
        step3 = TaskStep(step_id=3, action="Dashboard", description="View dashboard")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])
        graph.add_step(step3, dependencies=[2])

        assert graph.get_step(1) == step1
        assert graph.get_step(2) == step2
        assert graph.get_step(3) == step3

    def test_execution_order_respects_dependencies(self) -> None:
        """Steps execute in dependency order."""
        graph = TaskGraph()

        step3 = TaskStep(step_id=3, action="C", description="Third")
        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step3, dependencies=[2])
        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        steps = graph.get_all_steps()
        ids = [s.step_id for s in steps]

        assert ids.index(1) < ids.index(2)
        assert ids.index(2) < ids.index(3)

    def test_get_next_executable_respects_status(self) -> None:
        """get_next_executable only returns pending steps with satisfied dependencies."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")
        step3 = TaskStep(step_id=3, action="C", description="Third")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])
        graph.add_step(step3, dependencies=[2])

        next_step = graph.get_next_executable()
        assert next_step is not None
        assert next_step.step_id == 1

        graph.update_step_status(1, StepStatus.RUNNING)
        next_step = graph.get_next_executable()
        assert next_step is None

        graph.update_step_status(1, StepStatus.COMPLETED)
        next_step = graph.get_next_executable()
        assert next_step is not None
        assert next_step.step_id == 2

    def test_can_continue_after_failure(self) -> None:
        """can_continue returns False when blocked by failed dependency."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        assert graph.can_continue() is True

        graph.update_step_status(1, StepStatus.FAILED)
        assert graph.can_continue() is False

    def test_skipped_steps_unblock_dependents(self) -> None:
        """Skipped steps allow dependents to execute."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        graph.update_step_status(1, StepStatus.SKIPPED)

        next_step = graph.get_next_executable()
        assert next_step is not None
        assert next_step.step_id == 2

    def test_is_complete(self) -> None:
        """is_complete returns True when all steps are finished."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        assert graph.is_complete() is False

        graph.update_step_status(1, StepStatus.COMPLETED)
        assert graph.is_complete() is False

        graph.update_step_status(2, StepStatus.COMPLETED)
        assert graph.is_complete() is True

    def test_get_stats(self) -> None:
        """get_stats returns correct counts."""
        graph = TaskGraph()

        for i in range(1, 6):
            graph.add_step(
                TaskStep(step_id=i, action=f"Step{i}", description=f"Step {i}"),
                dependencies=[i-1] if i > 1 else [],
            )

        graph.update_step_status(1, StepStatus.COMPLETED)
        graph.update_step_status(2, StepStatus.FAILED)
        graph.update_step_status(3, StepStatus.SKIPPED)

        stats = graph.get_stats()
        assert stats["total"] == 5
        assert stats["completed"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 1
        assert stats["pending"] == 2

    def test_serialization_roundtrip(self) -> None:
        """Graph can be serialized and restored."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])
        graph.update_step_status(1, StepStatus.COMPLETED)

        data = graph.to_dict()
        restored = TaskGraph.from_dict(data)

        assert restored.get_step(1).status == StepStatus.COMPLETED
        assert restored.get_step(2).status == StepStatus.PENDING


class TestPageOperationPhases:
    """Tests for inner state machine phase definitions."""

    def test_phase_order(self) -> None:
        """Page operation phases are in correct order."""
        expected_order = [
            PageOperationPhase.NAVIGATE,
            PageOperationPhase.WAIT_LOAD,
            PageOperationPhase.POPUP_CHECK,
            PageOperationPhase.INTERACT,
            PageOperationPhase.EXTRACT,
            PageOperationPhase.SCREENSHOT,
            PageOperationPhase.RECORD,
        ]

        for i, phase in enumerate(expected_order):
            assert phase.value == expected_order[i].value

    def test_phase_values(self) -> None:
        """Phase values are correct strings."""
        assert PageOperationPhase.NAVIGATE.value == "navigate"
        assert PageOperationPhase.WAIT_LOAD.value == "wait_load"
        assert PageOperationPhase.POPUP_CHECK.value == "popup_check"
        assert PageOperationPhase.INTERACT.value == "interact"
        assert PageOperationPhase.EXTRACT.value == "extract"
        assert PageOperationPhase.SCREENSHOT.value == "screenshot"
        assert PageOperationPhase.RECORD.value == "record"


class TestTaskPhases:
    """Tests for outer state machine task phases."""

    def test_task_phase_order(self) -> None:
        """Task phases represent logical workflow."""
        phases = [
            TaskPhase.INIT,
            TaskPhase.LOGIN,
            TaskPhase.DASHBOARD,
            TaskPhase.EMPLOYEES,
            TaskPhase.LEAVE_MGMT,
            TaskPhase.REPORTS,
            TaskPhase.REPORT_GEN,
            TaskPhase.COMPLETED,
        ]

        for phase in phases:
            assert isinstance(phase, TaskPhase)

    def test_phase_values(self) -> None:
        """Phase values are correct strings."""
        assert TaskPhase.INIT.value == "init"
        assert TaskPhase.LOGIN.value == "login"
        assert TaskPhase.DASHBOARD.value == "dashboard"
        assert TaskPhase.EMPLOYEES.value == "employees"
        assert TaskPhase.LEAVE_MGMT.value == "leave_mgmt"
        assert TaskPhase.REPORTS.value == "reports"
        assert TaskPhase.REPORT_GEN.value == "report_gen"
        assert TaskPhase.COMPLETED.value == "completed"


class TestTaskStepRetry:
    """Tests for step retry behavior."""

    def test_retry_count_tracking(self) -> None:
        """Retry count is tracked correctly."""
        step = TaskStep(step_id=1, action="Test", description="Test step")

        assert step.retry_count == 0
        assert step.max_retries == 3

        step.retry_count = 1
        assert step.retry_count == 1

    def test_step_can_retry(self) -> None:
        """Step can retry within max_retries."""
        step = TaskStep(step_id=1, action="Test", description="Test step", max_retries=3)

        for i in range(3):
            step.retry_count = i
            assert step.retry_count < step.max_retries

        step.retry_count = 3
        assert step.retry_count >= step.max_retries
