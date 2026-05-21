"""Tests for the Execution Loop module."""

import pytest
import pandas as pd
from pathlib import Path
import tempfile
import shutil
import json
from unittest.mock import patch, MagicMock

from harness.execution import ExecutionLoop, ExecutionState, run_analysis


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory."""
    dirpath = tempfile.mkdtemp()
    yield Path(dirpath)
    shutil.rmtree(dirpath)


@pytest.fixture
def sample_csv(temp_output_dir):
    """Create a sample CSV file."""
    df = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'value': [10, 20, 30, 40, 50],
        'category': ['A', 'B', 'A', 'B', 'C']
    })
    path = temp_output_dir / "test_data.csv"
    df.to_csv(path, index=False)
    return path


class TestExecutionState:
    """Tests for ExecutionState enum."""

    def test_states_exist(self):
        assert ExecutionState.INIT
        assert ExecutionState.DISCOVER_DATA
        assert ExecutionState.LOAD_DATA
        assert ExecutionState.ANALYZE
        assert ExecutionState.COMPLETE
        assert ExecutionState.FAILED


class TestExecutionLoop:
    """Tests for ExecutionLoop class."""

    def test_initialization(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test analysis",
            data_files=[],
            max_steps=10
        )

        assert loop.current_state == ExecutionState.INIT
        assert loop.step_count == 0
        assert loop.analysis_goal == "Test analysis"

    def test_init_phase(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        result = loop.run_init()

        assert result is True
        assert loop.current_state == ExecutionState.DISCOVER_DATA

    def test_discover_data_with_files(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        result = loop.run_discover_data()

        assert result is True
        assert loop.current_state == ExecutionState.LOAD_DATA

    def test_discover_data_no_files(self, temp_output_dir):
        empty_dir = temp_output_dir / "empty"
        empty_dir.mkdir()

        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(empty_dir)

            loop = ExecutionLoop(
                output_dir=temp_output_dir,
                analysis_goal="Test",
                data_files=[],
                max_steps=10
            )

            loop.run_init()
            result = loop.run_discover_data()

            assert result is False
            assert loop.current_state == ExecutionState.FAILED
        finally:
            import os
            os.chdir(original_cwd)

    def test_load_data_success(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        loop.run_discover_data()
        result = loop.run_load_data()

        assert result is True
        assert loop.current_state == ExecutionState.ANALYZE
        assert loop.state_store.list_dataframes()

    def test_valid_state_transition(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        assert loop._transition_to(ExecutionState.DISCOVER_DATA, "test")
        assert loop.current_state == ExecutionState.DISCOVER_DATA

    def test_invalid_state_transition(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        assert not loop._transition_to(ExecutionState.COMPLETE, "invalid")
        assert loop.current_state == ExecutionState.INIT

    def test_rollback(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        loop.run_discover_data()
        loop.run_load_data()

        loop.state_store.set_variable("test_var", "initial")
        loop.state_store.snapshot()

        loop.state_store.set_variable("test_var", "modified")
        loop.state_store.snapshot()

        assert loop.rollback(0)
        assert loop.state_store.get_variable("test_var") == "initial"

    def test_build_result_success(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test analysis",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        loop.run_discover_data()
        loop.run_load_data()
        loop.state_store.add_insight("Test insight with 42 items")
        loop.current_state = ExecutionState.COMPLETE

        result = loop._build_result()

        assert result["status"] == "success"
        assert "report_path" in result
        assert "script_path" in result
        assert "trajectory" in result

    def test_build_result_partial(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.current_state = ExecutionState.COMPLETE

        result = loop._build_result()

        assert result["status"] == "partial"

    def test_generate_report(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Analyze test data",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        loop.run_discover_data()
        loop.run_load_data()
        loop.state_store.add_insight("Revenue increased 15% to $100K")

        report_path = loop._generate_report()

        assert report_path.exists()

        content = report_path.read_text()
        assert "Analysis Goal" in content
        assert "15%" in content

    def test_generate_script(self, temp_output_dir, sample_csv):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[str(sample_csv)],
            max_steps=10
        )

        loop.run_init()
        loop.run_discover_data()
        loop.run_load_data()

        script_path = loop._generate_script()

        assert script_path.exists()

        content = script_path.read_text()
        assert "import pandas" in content
        assert "import matplotlib" in content


class TestRunAnalysis:
    """Tests for run_analysis function."""

    @patch('harness.execution.ExecutionLoop.run_to_completion')
    def test_run_analysis_basic(self, mock_run, temp_output_dir, sample_csv):
        mock_run.return_value = {
            "status": "success",
            "charts": [],
            "insights": [],
            "report_path": str(temp_output_dir / "report.md"),
            "script_path": str(temp_output_dir / "script.py"),
            "trajectory": str(temp_output_dir / "trajectory.jsonl")
        }

        result = run_analysis(
            analysis_goal="Test",
            output_dir=str(temp_output_dir),
            data_files=[str(sample_csv)],
            max_steps=5
        )

        assert result["status"] == "success"

    def test_run_analysis_creates_output_dir(self, temp_output_dir):
        new_dir = temp_output_dir / "new_output"

        with patch('harness.execution.ExecutionLoop.run_to_completion') as mock:
            mock.return_value = {"status": "partial", "charts": [], "insights": [],
                               "report_path": "", "script_path": "", "trajectory": ""}

            run_analysis(
                analysis_goal="Test",
                output_dir=str(new_dir),
                data_files=[],
                max_steps=5
            )

        assert new_dir.exists()


class TestLLMParsing:
    """Tests for LLM response parsing."""

    def test_parse_valid_json(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        response = '{"thought": "I will analyze", "action": "execute_code", "action_input": {"code": "x=1"}}'
        parsed = loop._parse_llm_response(response)

        assert parsed["thought"] == "I will analyze"
        assert parsed["action"] == "execute_code"

    def test_parse_json_with_text(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        response = 'Here is my response:\n{"thought": "test", "action": "finish", "action_input": {}}\nEnd.'
        parsed = loop._parse_llm_response(response)

        assert parsed["action"] == "finish"

    def test_parse_invalid_json(self, temp_output_dir):
        loop = ExecutionLoop(
            output_dir=temp_output_dir,
            analysis_goal="Test",
            data_files=[],
            max_steps=10
        )

        response = "This is not valid JSON at all"
        parsed = loop._parse_llm_response(response)

        assert "action" in parsed
