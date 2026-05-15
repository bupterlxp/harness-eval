import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock
from httpx import Response

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.state import StateStore
from harness.tools import ToolRegistry, FileEditorTool, TestRunnerTool
from harness.context import ContextManager, SourceContext
from harness.schemas import BugReport, BugSeverity, BugType


class TestStateStore:
    def test_init(self):
        store = StateStore("./test_state")
        assert store is not None
        assert store.current_state == "INIT"

    def test_snapshot_creation(self):
        store = StateStore("./test_state")
        snapshot_path = store.create_snapshot("test_snap")
        assert os.path.exists(snapshot_path)
        assert os.path.exists(os.path.join(snapshot_path, "bugs.json"))


class TestTools:
    def test_tool_registry(self):
        registry = ToolRegistry()
        assert registry is not None

        editor = FileEditorTool()
        registry.register_tool(editor)
        assert registry.get_tool("file_editor") is not None

    def test_file_editor(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        editor = FileEditorTool()
        result = editor.execute(str(test_file), "hello", "changed")
        assert result.success
        assert test_file.read_text() == "changed world"


class TestContextManager:
    def test_source_context(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        manager = ContextManager()
        context = manager.get_source_context(str(test_file), 3)
        assert context.line_number == 3
        assert "line2" in context.before_content
        assert "line4" in context.after_content


class TestBugReport:
    def test_bug_creation(self):
        bug = BugReport(
            bug_id=1,
            title="Test Bug",
            description="Test description",
            severity=BugSeverity.HIGH,
            bug_type=BugType.SECURITY,
            file_path="test.py",
            line_number=10,
            code_snippet="bad_code()"
        )
        assert bug.bug_id == 1
        assert bug.severity == BugSeverity.HIGH
        assert bug.bug_type == BugType.SECURITY