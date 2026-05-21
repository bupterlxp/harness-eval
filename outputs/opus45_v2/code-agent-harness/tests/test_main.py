"""Tests for CLI entry point."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.__main__ import main, parse_task_spec, run_harness


class TestParseTaskSpec:
    """Tests for parse_task_spec function."""

    def test_detect_bug_fix(self) -> None:
        """Test detecting bug fix task type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = parse_task_spec("Fix the login bug", tmpdir)
            assert spec["task_type"] == "bug_fix"

    def test_detect_feature(self) -> None:
        """Test detecting feature task type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = parse_task_spec("Add user authentication", tmpdir)
            assert spec["task_type"] == "feature"

    def test_detect_refactor(self) -> None:
        """Test detecting refactor task type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = parse_task_spec("Refactor the database module", tmpdir)
            assert spec["task_type"] == "refactor"

    def test_detect_test_gen(self) -> None:
        """Test detecting test generation task type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = parse_task_spec("Add tests for the API", tmpdir)
            assert spec["task_type"] == "test_gen"

    def test_detect_test_command_pytest(self) -> None:
        """Test detecting pytest test command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "tests").mkdir()
            spec = parse_task_spec("Add feature", tmpdir)
            assert spec["test_command"] == "pytest tests/ -v"

    def test_detect_test_command_npm(self) -> None:
        """Test detecting npm test command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "package.json").write_text("{}")
            spec = parse_task_spec("Add feature", tmpdir)
            assert spec["test_command"] == "npm test"


class TestMain:
    """Tests for main function."""

    def test_help_flag(self) -> None:
        """Test --help flag."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['harness', '--help']):
                main()
        assert exc_info.value.code == 0

    def test_version_flag(self) -> None:
        """Test --version flag."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['harness', '--version']):
                main()
        assert exc_info.value.code == 0

    def test_missing_prompt_fails(self) -> None:
        """Test that missing prompt causes failure."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['harness']):
                main()
        assert exc_info.value.code != 0


class TestRunHarness:
    """Tests for run_harness function."""

    @patch('harness.__main__.LLMClient')
    def test_creates_output_directory(self, mock_llm: MagicMock) -> None:
        """Test that output directory is created."""
        mock_llm.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"summary": "test"}'))]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"

            result = run_harness(
                description="Test task",
                output_dir=str(output_dir),
                repo_path=tmpdir,
                max_iterations=1,
                max_llm_calls=5,
            )

            assert output_dir.exists()

    @patch('harness.__main__.LLMClient')
    def test_creates_result_json(self, mock_llm: MagicMock) -> None:
        """Test that result.json is created."""
        mock_llm.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"summary": "test"}'))]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"

            run_harness(
                description="Test task",
                output_dir=str(output_dir),
                repo_path=tmpdir,
                max_iterations=1,
                max_llm_calls=5,
            )

            result_file = output_dir / "result.json"
            assert result_file.exists()

            with open(result_file) as f:
                result = json.load(f)
                assert "status" in result
                assert "edits" in result
                assert "test_results" in result
                assert "trajectory" in result

    @patch('harness.__main__.LLMClient')
    def test_result_schema_compliance(self, mock_llm: MagicMock) -> None:
        """Test that result matches expected schema."""
        mock_llm.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"summary": "test"}'))]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"

            result = run_harness(
                description="Test task",
                output_dir=str(output_dir),
                repo_path=tmpdir,
                max_iterations=1,
                max_llm_calls=5,
            )

            assert result["status"] in ("success", "partial", "failed")
            assert isinstance(result["edits"], list)
            assert isinstance(result["test_results"], dict)
            assert "passed" in result["test_results"]
            assert "failed" in result["test_results"]
            assert "errors" in result["test_results"]
            assert isinstance(result["trajectory"], str)
