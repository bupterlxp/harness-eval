"""Tests for the main harness module."""

import tempfile
from pathlib import Path

import pytest

from harness.__main__ import find_repo_path, parse_task_spec


class TestParseTaskSpec:
    """Tests for parse_task_spec function."""

    def test_bug_fix_detection(self):
        spec = parse_task_spec("Fix the bug in login.py")
        assert spec["task_type"] == "bug_fix"

        spec = parse_task_spec("There's an error in the authentication module")
        assert spec["task_type"] == "bug_fix"

    def test_refactor_detection(self):
        spec = parse_task_spec("Refactor the database module")
        assert spec["task_type"] == "refactor"

        spec = parse_task_spec("Clean up the utility functions")
        assert spec["task_type"] == "refactor"

    def test_test_gen_detection(self):
        spec = parse_task_spec("Add tests for the API endpoints")
        assert spec["task_type"] == "test_gen"

        spec = parse_task_spec("Improve test coverage")
        assert spec["task_type"] == "test_gen"

    def test_feature_detection(self):
        spec = parse_task_spec("Add a new login page")
        assert spec["task_type"] == "feature"

        spec = parse_task_spec("Implement user authentication")
        assert spec["task_type"] == "feature"

    def test_test_command_extraction(self):
        spec = parse_task_spec("Fix the bug, test with: pytest tests/")
        assert spec["test_command"] is not None
        assert "pytest" in spec["test_command"]

    def test_constraint_extraction(self):
        spec = parse_task_spec("Add feature without modifying the database")
        assert len(spec["constraints"]) > 0
        assert any("database" in c.lower() for c in spec["constraints"])


class TestFindRepoPath:
    """Tests for find_repo_path function."""

    def test_returns_path(self):
        path = find_repo_path(".")
        assert path is not None
        assert Path(path).exists()


class TestHarnessImports:
    """Tests for harness module imports."""

    def test_import_harness(self):
        import harness
        assert harness is not None

    def test_import_all_components(self):
        from harness import execution, tools, context, state, lifecycle, evaluation

        assert execution is not None
        assert tools is not None
        assert context is not None
        assert state is not None
        assert lifecycle is not None
        assert evaluation is not None

    def test_cli_help(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "harness", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "-p" in result.stdout or "--prompt" in result.stdout
        assert "--output-dir" in result.stdout
