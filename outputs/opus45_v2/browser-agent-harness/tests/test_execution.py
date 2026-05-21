"""Tests for the Execution Loop module."""

import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from harness.execution import (
    ExecutionLoop,
    BrowserAgent,
    TaskFlowState,
    OperationState,
    OperationContext,
)
from harness.state import StateStore
from harness.context import ContextManager
from harness.tools import ToolRegistry, ToolResult
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder


class TestTaskFlowState:
    """Tests for TaskFlowState enum."""

    def test_states(self):
        assert TaskFlowState.INITIALIZING.value == "initializing"
        assert TaskFlowState.PLANNING.value == "planning"
        assert TaskFlowState.EXECUTING.value == "executing"
        assert TaskFlowState.RECOVERING.value == "recovering"
        assert TaskFlowState.COMPLETED.value == "completed"
        assert TaskFlowState.FAILED.value == "failed"


class TestOperationState:
    """Tests for OperationState enum."""

    def test_states(self):
        assert OperationState.PENDING.value == "pending"
        assert OperationState.WAITING.value == "waiting"
        assert OperationState.ACTING.value == "acting"
        assert OperationState.VERIFYING.value == "verifying"
        assert OperationState.SUCCEEDED.value == "succeeded"
        assert OperationState.RETRYING.value == "retrying"
        assert OperationState.FAILED.value == "failed"
        assert OperationState.SKIPPED.value == "skipped"


class TestOperationContext:
    """Tests for OperationContext."""

    def test_creation(self):
        ctx = OperationContext(
            step_id=1,
            action_type="click",
            action_params={"selector": "#button"},
        )
        assert ctx.step_id == 1
        assert ctx.action_type == "click"
        assert ctx.state == OperationState.PENDING
        assert ctx.retry_count == 0

    def test_with_target_element(self):
        ctx = OperationContext(
            step_id=1,
            action_type="type_text",
            action_params={"selector": "#input", "text": "hello"},
            target_element="Email input field",
        )
        assert ctx.target_element == "Email input field"


class TestExecutionLoop:
    """Tests for ExecutionLoop."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def execution_loop(self, temp_dir):
        state_store = StateStore(temp_dir)
        state_store.initialize_task("test", "https://example.com", "Test task")

        context_manager = ContextManager()
        tool_registry = ToolRegistry(temp_dir)
        lifecycle_hooks = LifecycleHooks(temp_dir)
        trajectory_recorder = TrajectoryRecorder(temp_dir)

        return ExecutionLoop(
            state_store,
            context_manager,
            tool_registry,
            lifecycle_hooks,
            trajectory_recorder,
        )

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.url = "https://example.com"
        page.on = MagicMock()
        page.wait_for_load_state = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.first = mock_locator
        page.locator = MagicMock(return_value=mock_locator)

        return page

    def test_init(self, execution_loop):
        assert execution_loop._task_state == TaskFlowState.INITIALIZING
        assert execution_loop._operation_state == OperationState.PENDING
        assert execution_loop._consecutive_failures == 0

    def test_set_page(self, execution_loop, mock_page):
        execution_loop.set_page(mock_page)

        assert execution_loop._page is mock_page

    def test_reset_operation_state(self, execution_loop):
        execution_loop._operation_state = OperationState.ACTING
        execution_loop._current_operation = MagicMock()

        execution_loop.reset_operation_state()

        assert execution_loop._operation_state == OperationState.PENDING
        assert execution_loop._current_operation is None

    def test_should_abort_false(self, execution_loop):
        execution_loop._consecutive_failures = 2

        assert execution_loop.should_abort() is False

    def test_should_abort_true(self, execution_loop):
        execution_loop._consecutive_failures = 5

        assert execution_loop.should_abort() is True

    def test_get_set_task_state(self, execution_loop):
        assert execution_loop.get_task_state() == TaskFlowState.INITIALIZING

        execution_loop.set_task_state(TaskFlowState.EXECUTING)

        assert execution_loop.get_task_state() == TaskFlowState.EXECUTING


class TestExecutionLoopAsync:
    """Async tests for ExecutionLoop."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.url = "https://example.com"
        page.on = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.screenshot = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.first = mock_locator
        mock_locator.wait_for = AsyncMock()
        mock_locator.click = AsyncMock()
        page.locator = MagicMock(return_value=mock_locator)

        return page

    @pytest.mark.asyncio
    async def test_execute_operation_success(self, temp_dir, mock_page):
        state_store = StateStore(temp_dir)
        state_store.initialize_task("test", "https://example.com", "Test task")

        context_manager = ContextManager()
        tool_registry = ToolRegistry(temp_dir)
        lifecycle_hooks = LifecycleHooks(temp_dir)
        trajectory_recorder = TrajectoryRecorder(temp_dir)

        loop = ExecutionLoop(
            state_store,
            context_manager,
            tool_registry,
            lifecycle_hooks,
            trajectory_recorder,
        )
        loop.set_page(mock_page)

        with patch.object(tool_registry, 'execute', return_value=ToolResult(success=True)):
            operation = OperationContext(
                step_id=0,
                action_type="click",
                action_params={"selector": "#button"},
            )

            result = await loop.execute_operation(operation)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_operation_with_retry(self, temp_dir, mock_page):
        state_store = StateStore(temp_dir)
        state_store.initialize_task("test", "https://example.com", "Test task")

        context_manager = ContextManager()
        tool_registry = ToolRegistry(temp_dir)
        lifecycle_hooks = LifecycleHooks(temp_dir)
        trajectory_recorder = TrajectoryRecorder(temp_dir)

        loop = ExecutionLoop(
            state_store,
            context_manager,
            tool_registry,
            lifecycle_hooks,
            trajectory_recorder,
        )
        loop.set_page(mock_page)

        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return ToolResult(success=False, error="Element not found")
            return ToolResult(success=True)

        with patch.object(tool_registry, 'execute', side_effect=mock_execute):
            with patch.object(tool_registry, 'take_error_screenshot', return_value=None):
                operation = OperationContext(
                    step_id=0,
                    action_type="click",
                    action_params={"selector": "#button"},
                    max_retries=3,
                )

                result = await loop.execute_operation(operation)

        assert result.success is True
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_execute_operation_max_retries_exceeded(self, temp_dir, mock_page):
        state_store = StateStore(temp_dir)
        state_store.initialize_task("test", "https://example.com", "Test task")

        context_manager = ContextManager()
        tool_registry = ToolRegistry(temp_dir)
        lifecycle_hooks = LifecycleHooks(temp_dir)
        trajectory_recorder = TrajectoryRecorder(temp_dir)

        loop = ExecutionLoop(
            state_store,
            context_manager,
            tool_registry,
            lifecycle_hooks,
            trajectory_recorder,
        )
        loop.set_page(mock_page)

        with patch.object(tool_registry, 'execute', return_value=ToolResult(success=False, error="Always fails")):
            with patch.object(tool_registry, 'take_error_screenshot', return_value=None):
                operation = OperationContext(
                    step_id=0,
                    action_type="click",
                    action_params={"selector": "#button"},
                    max_retries=2,
                )

                result = await loop.execute_operation(operation)

        assert result.success is False
        assert loop._consecutive_failures > 0


class TestBrowserAgent:
    """Tests for BrowserAgent."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init(self, temp_dir):
        agent = BrowserAgent(output_dir=temp_dir, max_steps=30)

        assert agent.output_dir == temp_dir
        assert agent.max_steps == 30
        assert agent.state_store is not None
        assert agent.context_manager is not None
        assert agent.tool_registry is not None
        assert agent.lifecycle_hooks is not None
        assert agent.trajectory_recorder is not None

    def test_init_with_model(self, temp_dir):
        agent = BrowserAgent(output_dir=temp_dir, model_name="gpt-4")

        assert agent.model_name == "gpt-4"

    def test_system_prompt(self, temp_dir):
        agent = BrowserAgent(output_dir=temp_dir)

        assert "browser automation agent" in agent.SYSTEM_PROMPT.lower()
        assert "tools" in agent.SYSTEM_PROMPT.lower()
