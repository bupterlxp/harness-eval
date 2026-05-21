"""Tests for harness.execution module."""

import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from harness.execution import (
    ExecutionLoop,
    StateMachine,
    TransitionCondition,
    ExecutionResult,
)
from harness.state import AgentPhase


class TestStateMachine:
    """Tests for StateMachine."""

    @pytest.fixture
    def sm(self):
        """Create a StateMachine instance."""
        return StateMachine()

    def test_valid_transitions_from_init(self, sm):
        """Test valid transitions from INIT phase."""
        transitions = sm.get_valid_transitions(AgentPhase.INIT)
        assert len(transitions) > 0

    def test_can_transition(self, sm):
        """Test checking valid transitions."""
        assert sm.can_transition(
            AgentPhase.INIT,
            AgentPhase.UNDERSTAND,
            TransitionCondition.UNDERSTANDING_COMPLETE
        )

    def test_get_next_phase(self, sm):
        """Test getting next phase for condition."""
        next_phase = sm.get_next_phase(
            AgentPhase.UNDERSTAND,
            TransitionCondition.UNDERSTANDING_COMPLETE
        )
        assert next_phase == AgentPhase.LOCATE

    def test_terminal_phases(self, sm):
        """Test that COMPLETE and FAILED are terminal."""
        complete_transitions = sm.get_valid_transitions(AgentPhase.COMPLETE)
        failed_transitions = sm.get_valid_transitions(AgentPhase.FAILED)

        assert len(complete_transitions) == 0
        assert len(failed_transitions) == 0

    def test_verify_to_complete_or_retry(self, sm):
        """Test VERIFY can transition to COMPLETE or RETRY."""
        transitions = sm.get_valid_transitions(AgentPhase.VERIFY)
        to_phases = [t.to_phase for t in transitions]

        assert AgentPhase.COMPLETE in to_phases
        assert AgentPhase.RETRY in to_phases

    def test_retry_transitions(self, sm):
        """Test RETRY phase transitions."""
        transitions = sm.get_valid_transitions(AgentPhase.RETRY)
        to_phases = [t.to_phase for t in transitions]

        assert AgentPhase.EDIT in to_phases
        assert AgentPhase.LOCATE in to_phases
        assert AgentPhase.FAILED in to_phases


class TestExecutionResult:
    """Tests for ExecutionResult."""

    def test_creation(self):
        """Test creating an execution result."""
        result = ExecutionResult(
            phase=AgentPhase.UNDERSTAND,
            action_taken="read_file",
            output="file contents",
            next_condition=TransitionCondition.UNDERSTANDING_COMPLETE
        )
        assert result.phase == AgentPhase.UNDERSTAND
        assert result.next_condition == TransitionCondition.UNDERSTANDING_COMPLETE


class TestExecutionLoop:
    """Tests for ExecutionLoop."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    @pytest.fixture
    def task_spec(self):
        """Create a minimal task spec."""
        return {
            "task_type": "bug_fix",
            "description": "Fix the bug",
            "repo_path": ".",
            "test_command": None,
            "constraints": []
        }

    def test_initialization(self, temp_dir, task_spec):
        """Test ExecutionLoop initialization."""
        task_spec["repo_path"] = str(temp_dir)
        loop = ExecutionLoop(temp_dir, task_spec)

        assert loop.repo_path == temp_dir.resolve()
        assert loop.state_store is not None
        assert loop.tools is not None
        assert loop.context is not None
        assert loop.lifecycle is not None

    def test_state_machine_attached(self, temp_dir, task_spec):
        """Test state machine is attached."""
        task_spec["repo_path"] = str(temp_dir)
        loop = ExecutionLoop(temp_dir, task_spec)

        assert loop.state_machine is not None
        assert isinstance(loop.state_machine, StateMachine)

    def test_parse_llm_response_json(self, temp_dir, task_spec):
        """Test parsing JSON LLM response."""
        task_spec["repo_path"] = str(temp_dir)
        loop = ExecutionLoop(temp_dir, task_spec)

        response = '{"thought": "thinking", "action": "read_file", "action_input": {"path": "test.py"}}'
        parsed = loop._parse_llm_response(response)

        assert parsed["action"] == "read_file"
        assert parsed["action_input"]["path"] == "test.py"

    def test_parse_llm_response_with_text(self, temp_dir, task_spec):
        """Test parsing LLM response with surrounding text."""
        task_spec["repo_path"] = str(temp_dir)
        loop = ExecutionLoop(temp_dir, task_spec)

        response = 'Let me analyze this. {"thought": "x", "action": "search", "action_input": {}}'
        parsed = loop._parse_llm_response(response)

        assert parsed["action"] == "search"

    def test_build_phase_prompt(self, temp_dir, task_spec):
        """Test building phase prompts."""
        task_spec["repo_path"] = str(temp_dir)
        loop = ExecutionLoop(temp_dir, task_spec)

        prompt = loop._build_phase_prompt(AgentPhase.UNDERSTAND)
        assert "UNDERSTAND" in prompt
        assert task_spec["description"] in prompt

    @patch.object(ExecutionLoop, '_get_llm_client')
    def test_run_with_mock_llm(self, mock_client, temp_dir, task_spec):
        """Test running with mocked LLM."""
        task_spec["repo_path"] = str(temp_dir)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"thought": "done", "action": "phase_complete", "action_input": {"summary": "complete"}}'
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = mock_response
        mock_client.return_value = mock_openai

        loop = ExecutionLoop(temp_dir, task_spec)
        loop.budget.max_llm_calls = 2
        loop.budget.max_iterations = 5

        result = loop.run()

        assert "status" in result
        assert "trajectory" in result


class TestTransitionCondition:
    """Tests for TransitionCondition enum."""

    def test_all_conditions_defined(self):
        """Test all transition conditions are defined."""
        conditions = [
            TransitionCondition.UNDERSTANDING_COMPLETE,
            TransitionCondition.LOCATION_FOUND,
            TransitionCondition.PLAN_READY,
            TransitionCondition.EDIT_COMPLETE,
            TransitionCondition.TESTS_PASSED,
            TransitionCondition.TESTS_FAILED,
            TransitionCondition.RETRY_NEEDED,
            TransitionCondition.RETRY_EXHAUSTED,
            TransitionCondition.BUDGET_EXCEEDED,
            TransitionCondition.ERROR_FATAL,
            TransitionCondition.TASK_COMPLETE,
        ]
        assert len(conditions) >= 11
