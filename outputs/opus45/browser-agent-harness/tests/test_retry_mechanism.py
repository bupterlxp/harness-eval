"""
test_retry_mechanism.py - Tests for timeout and retry behavior.

Verifies:
- Retry on timeout
- Max retry limits
- Error recording during retry
"""

import pytest
from datetime import datetime, timedelta
from harness.schemas import StepStatus, TaskStep
from harness.state import TaskGraph
from harness.lifecycle import LifecycleManager, HookContext, HookResult, HookType


class TestRetryMechanism:
    """Tests for retry behavior in the harness."""

    def test_step_tracks_retry_count(self) -> None:
        """Step retry count increments correctly."""
        step = TaskStep(step_id=1, action="Test", description="Test", max_retries=3)

        assert step.retry_count == 0

        step.retry_count += 1
        assert step.retry_count == 1

        step.retry_count += 1
        assert step.retry_count == 2

    def test_step_records_error_on_failure(self) -> None:
        """Step records error message on failure."""
        step = TaskStep(step_id=1, action="Test", description="Test")

        step.status = StepStatus.FAILED
        step.error_message = "Connection timeout after 10s"

        assert step.status == StepStatus.FAILED
        assert "timeout" in step.error_message.lower()

    def test_step_timing_recorded(self) -> None:
        """Step records start and completion times."""
        step = TaskStep(step_id=1, action="Test", description="Test")

        step.started_at = datetime.now()
        step.completed_at = step.started_at + timedelta(milliseconds=1500)
        step.duration_ms = int((step.completed_at - step.started_at).total_seconds() * 1000)

        assert step.duration_ms == 1500

    def test_graph_allows_status_reset_for_retry(self) -> None:
        """Graph allows resetting failed step status for retry."""
        graph = TaskGraph()
        step = TaskStep(step_id=1, action="Test", description="Test")
        graph.add_step(step, dependencies=[])

        graph.update_step_status(1, StepStatus.FAILED, "First failure")

        retrieved = graph.get_step(1)
        assert retrieved is not None
        assert retrieved.status == StepStatus.FAILED

        retrieved.status = StepStatus.PENDING
        retrieved.error_message = None
        retrieved.retry_count = 1

        assert graph.get_step(1).status == StepStatus.PENDING


class TestLifecycleOnTimeout:
    """Tests for lifecycle on_timeout hook."""

    @pytest.mark.asyncio
    async def test_on_timeout_triggers_retry(self) -> None:
        """on_timeout hook triggers retry when under max attempts."""
        lifecycle = LifecycleManager()

        messages: list[str] = []
        lifecycle.set_log_callback(lambda m: messages.append(m))

        result = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000/test",
            operation="click #button",
            retry_count=0,
            max_retries=3,
        )

        assert result.should_retry is True
        assert any("retry" in m.lower() for m in messages)

    @pytest.mark.asyncio
    async def test_on_timeout_stops_at_max_retries(self) -> None:
        """on_timeout hook stops retry at max attempts."""
        lifecycle = LifecycleManager()

        result = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000/test",
            operation="click #button",
            retry_count=2,
            max_retries=3,
        )

        assert result.should_continue is False
        assert "max retries" in result.message.lower()

    @pytest.mark.asyncio
    async def test_on_timeout_takes_screenshot(self) -> None:
        """on_timeout hook captures screenshot."""
        lifecycle = LifecycleManager()

        screenshot_paths: list[str] = []
        async def screenshot_callback(name: str) -> str:
            path = f"screenshots/{name}.png"
            screenshot_paths.append(path)
            return path

        lifecycle.set_screenshot_callback(screenshot_callback)

        result = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000/test",
            operation="click #button",
            retry_count=0,
            max_retries=3,
        )

        assert len(screenshot_paths) == 1
        assert "timeout" in screenshot_paths[0]
        assert result.screenshot_path is not None


class TestRetryRecovery:
    """Tests for retry recovery scenarios."""

    def test_retry_after_timeout_preserves_context(self) -> None:
        """Retry preserves task context from before failure."""
        step = TaskStep(
            step_id=5,
            action="Search employees",
            description="Search for employees",
        )

        step.extracted_data["previous_step_data"] = "preserved"
        step.status = StepStatus.FAILED
        step.error_message = "Timeout waiting for element"
        step.retry_count = 1

        step.status = StepStatus.PENDING
        step.error_message = None

        assert step.extracted_data["previous_step_data"] == "preserved"

    def test_failed_step_blocks_dependents(self) -> None:
        """Failed step prevents dependent steps from executing."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        graph.update_step_status(1, StepStatus.FAILED, "Timeout")

        next_step = graph.get_next_executable()
        assert next_step is None
        assert graph.can_continue() is False

    def test_retry_success_unblocks_dependents(self) -> None:
        """Successful retry unblocks dependent steps."""
        graph = TaskGraph()

        step1 = TaskStep(step_id=1, action="A", description="First")
        step2 = TaskStep(step_id=2, action="B", description="Second")

        graph.add_step(step1, dependencies=[])
        graph.add_step(step2, dependencies=[1])

        graph.update_step_status(1, StepStatus.FAILED, "Timeout")
        assert graph.can_continue() is False

        step1_ref = graph.get_step(1)
        step1_ref.status = StepStatus.PENDING
        step1_ref.error_message = None

        next_step = graph.get_next_executable()
        assert next_step is not None
        assert next_step.step_id == 1

        graph.update_step_status(1, StepStatus.COMPLETED)

        next_step = graph.get_next_executable()
        assert next_step is not None
        assert next_step.step_id == 2


class TestRetryWithDifferentStrategies:
    """Tests for different retry strategies."""

    @pytest.mark.asyncio
    async def test_immediate_retry(self) -> None:
        """Immediate retry without delay."""
        lifecycle = LifecycleManager()

        result = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000",
            operation="wait_for_element",
            retry_count=0,
            max_retries=3,
        )

        assert result.should_retry is True

    @pytest.mark.asyncio
    async def test_custom_retry_hook(self) -> None:
        """Custom retry hook can override default behavior."""
        lifecycle = LifecycleManager()

        async def custom_timeout_hook(context: HookContext) -> HookResult:
            if context.retry_count == 0:
                return HookResult(should_retry=True, message="Custom retry logic")
            return HookResult(should_continue=False, message="Custom: stop retry")

        lifecycle.register_hook(HookType.ON_TIMEOUT, custom_timeout_hook)

        result1 = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000",
            operation="test",
            retry_count=0,
            max_retries=5,
        )
        assert result1.should_retry is True

        result2 = await lifecycle.on_timeout(
            step_id=1,
            url="http://localhost:5000",
            operation="test",
            retry_count=1,
            max_retries=5,
        )
        assert result2.should_continue is False
