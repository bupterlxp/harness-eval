"""Tests for the Execution module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.context import ContextManager
from harness.evaluation import TrajectoryLogger
from harness.execution import (
    AgentPhase,
    EditPhase,
    ExecutionContext,
    ExecutionLoop,
    InitPhase,
    LocatePhase,
    PhaseResult,
    PlanPhase,
    RetryPhase,
    TransitionResult,
    UnderstandPhase,
    VerifyPhase,
)
from harness.lifecycle import LifecycleManager
from harness.state import StateStore
from harness.tools import ToolRegistry


class TestTransitionResult:
    """Tests for TransitionResult enum."""

    def test_all_results_exist(self):
        results = [
            TransitionResult.CONTINUE,
            TransitionResult.COMPLETE,
            TransitionResult.FAILED,
            TransitionResult.RETRY,
        ]
        assert len(results) == 4


class TestPhaseResult:
    """Tests for PhaseResult dataclass."""

    def test_continue_result(self):
        result = PhaseResult(
            transition=TransitionResult.CONTINUE,
            next_phase=AgentPhase.LOCATE,
            data={"files": 10},
        )
        assert result.transition == TransitionResult.CONTINUE
        assert result.next_phase == AgentPhase.LOCATE

    def test_failed_result(self):
        result = PhaseResult(
            transition=TransitionResult.FAILED,
            error="Something went wrong",
        )
        assert result.transition == TransitionResult.FAILED
        assert result.error == "Something went wrong"


class TestExecutionContext:
    """Tests for ExecutionContext."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def context(self, temp_dir):
        state_store = StateStore(temp_dir)
        tool_registry = ToolRegistry()
        context_manager = ContextManager()
        lifecycle = LifecycleManager(state_store)
        trajectory = TrajectoryLogger(temp_dir)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_client.chat.completions.create.return_value = mock_response

        trajectory.start_session("Test task")

        return ExecutionContext(
            state_store=state_store,
            tool_registry=tool_registry,
            context_manager=context_manager,
            lifecycle=lifecycle,
            trajectory=trajectory,
            llm_client=mock_client,
            model_name="test-model",
        )

    def test_call_llm(self, context):
        messages = [{"role": "user", "content": "Hello"}]
        response = context.call_llm(messages)

        assert "content" in response
        assert context.state_store.state.llm_calls == 1

    def test_execute_tool(self, context, temp_dir):
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("content")

        result = context.execute_tool("read_file", {"path": str(test_file)})

        assert result.success
        assert "content" in result.output["content"]


class TestInitPhase:
    """Tests for InitPhase."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_execute_success(self, temp_dir):
        # Create some test files
        (Path(temp_dir) / "file1.py").touch()
        (Path(temp_dir) / "file2.py").touch()

        state_store = StateStore(temp_dir)
        state_store.state.repo_path = temp_dir

        tool_registry = ToolRegistry()
        context_manager = ContextManager()
        lifecycle = LifecycleManager(state_store)
        trajectory = TrajectoryLogger(temp_dir)
        trajectory.start_session("Test task")

        ctx = ExecutionContext(
            state_store=state_store,
            tool_registry=tool_registry,
            context_manager=context_manager,
            lifecycle=lifecycle,
            trajectory=trajectory,
            llm_client=MagicMock(),
            model_name="test",
        )

        phase = InitPhase()
        result = phase.execute(ctx)

        assert result.transition == TransitionResult.CONTINUE
        assert result.next_phase == AgentPhase.UNDERSTAND


class TestVerifyPhase:
    """Tests for VerifyPhase."""

    def test_parse_test_output_success(self):
        from harness.tools import ToolResult

        result = ToolResult(
            success=True,
            output={
                "stdout": "5 passed, 0 failed in 1.23s",
                "stderr": "",
                "returncode": 0,
            },
        )

        parsed = VerifyPhase._parse_test_output(result)

        assert parsed["passed"] == 5
        assert parsed["failed"] == 0

    def test_parse_test_output_failure(self):
        from harness.tools import ToolResult

        result = ToolResult(
            success=True,
            output={
                "stdout": "3 passed, 2 failed in 2.5s",
                "stderr": "Error: assertion failed",
                "returncode": 1,
            },
        )

        parsed = VerifyPhase._parse_test_output(result)

        assert parsed["passed"] == 3
        assert parsed["failed"] == 2
        assert len(parsed["errors"]) > 0


class TestExecutionLoop:
    """Tests for ExecutionLoop."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_phase_handlers_registered(self, temp_dir):
        state_store = StateStore(temp_dir)
        tool_registry = ToolRegistry()
        context_manager = ContextManager()
        lifecycle = LifecycleManager(state_store)
        trajectory = TrajectoryLogger(temp_dir)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            loop = ExecutionLoop(
                state_store=state_store,
                tool_registry=tool_registry,
                context_manager=context_manager,
                lifecycle=lifecycle,
                trajectory=trajectory,
            )

        assert AgentPhase.INIT in loop._handlers
        assert AgentPhase.UNDERSTAND in loop._handlers
        assert AgentPhase.LOCATE in loop._handlers
        assert AgentPhase.PLAN in loop._handlers
        assert AgentPhase.EDIT in loop._handlers
        assert AgentPhase.VERIFY in loop._handlers

    def test_compute_diff(self):
        original = "line1\nline2\nline3"
        modified = "line1\nmodified\nline3"

        diff = ExecutionLoop._compute_diff(original, modified)

        assert "-line2" in diff
        assert "+modified" in diff

    def test_build_result(self, temp_dir):
        state_store = StateStore(temp_dir)
        state_store.state.phase = AgentPhase.COMPLETE
        state_store.state.modified_files = []
        state_store.state.test_results = {"passed": 5, "failed": 0, "errors": []}

        tool_registry = ToolRegistry()
        context_manager = ContextManager()
        lifecycle = LifecycleManager(state_store)
        trajectory = TrajectoryLogger(temp_dir)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            loop = ExecutionLoop(
                state_store=state_store,
                tool_registry=tool_registry,
                context_manager=context_manager,
                lifecycle=lifecycle,
                trajectory=trajectory,
            )

        result = loop._build_result()

        assert result["status"] == "success"
        assert result["edits"] == []
        assert result["test_results"]["passed"] == 5
