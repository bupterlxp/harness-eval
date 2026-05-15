"""End-to-end tests for the harness."""

import pytest
from pathlib import Path
import tempfile
import shutil
import os

from harness.schemas import BugReport, BugCategory, BugSeverity, BugStatus
from harness.state import StateStore, BugTracker
from harness.tools import ToolRegistry
from harness.context import ContextManager
from harness.lifecycle import LifecycleManager
from harness.evaluation import EvaluationInterface
from harness.execution import ExecutionStateMachine, MainState, Event
from harness.domain.tools import (
    CodeSearcher,
    FileEditor,
    TestRunner,
    GitOperator,
    StaticAnalyzer,
)


class TestToolsIntegration:
    """Integration tests for domain tools."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        (path / "test.py").write_text("""
def hello():
    # BUG 1: returns wrong value
    return "world"

def add(a, b):
    return a + b
""")
        yield path
        shutil.rmtree(path)

    def test_code_searcher(self, temp_dir):
        searcher = CodeSearcher(temp_dir)
        result, _ = searcher.run({"pattern": "BUG", "file_glob": "*.py"})

        assert result.total_matches >= 1
        assert any("BUG 1" in m.line_content for m in result.matches)

    def test_file_editor_read(self, temp_dir):
        editor = FileEditor(temp_dir)
        result = editor.read("test.py")

        assert "hello" in result.content
        assert result.total_lines > 0

    def test_file_editor_patch(self, temp_dir):
        editor = FileEditor(temp_dir)
        result = editor.patch(
            "test.py",
            'return "world"',
            'return "hello"',
        )

        assert result.success
        assert result.replacements == 1

        content = (temp_dir / "test.py").read_text()
        assert 'return "hello"' in content

    def test_static_analyzer(self, temp_dir):
        analyzer = StaticAnalyzer(temp_dir)
        result, _ = analyzer.run({"path": "test.py", "analysis": "functions"})

        assert len(result.functions) == 2
        func_names = [f.name for f in result.functions]
        assert "hello" in func_names
        assert "add" in func_names


class TestContextManager:
    """Tests for context manager."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        (path / "code.py").write_text("\n".join(f"line {i}" for i in range(100)))
        yield path
        shutil.rmtree(path)

    def test_get_source_context(self, temp_dir):
        cm = ContextManager(context_lines=5)
        ctx = cm.source.get_context(str(temp_dir / "code.py"), 50)

        assert ctx.focus_line == 50
        assert "line 50" in ctx.content
        assert ctx.start_line < 50
        assert ctx.end_line > 50

    def test_compress_long_text(self):
        cm = ContextManager()
        long_text = "x" * 20000
        compressed = cm.compress(long_text, max_length=1000)

        assert len(compressed) <= 1500
        assert "truncated" in compressed


class TestStateStore:
    """Tests for state store."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_save_and_load(self, temp_dir):
        store = StateStore(temp_dir)

        bug = BugReport(
            id="BUG_1",
            title="Test",
            description="",
            file_path="test.py",
            line_number=10,
            category=BugCategory.CORRECTNESS,
            severity=BugSeverity.MEDIUM,
        )
        store.bug_tracker.add_bug(bug)
        store.save()

        new_store = StateStore(temp_dir)
        assert new_store.load()
        assert new_store.bug_tracker.get_bug("BUG_1") is not None


class TestEvaluation:
    """Tests for evaluation interface."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_trajectory_recording(self, temp_dir):
        eval_if = EvaluationInterface(temp_dir, session_id="test")

        eval_if.begin_step("INDEX", "scanning")
        eval_if.add_metadata("files", 10)
        step = eval_if.end_step()

        assert step.state == "INDEX"
        assert step.action == "scanning"
        assert step.metadata["files"] == 10

    def test_metrics_collection(self, temp_dir):
        eval_if = EvaluationInterface(temp_dir)

        eval_if.metrics.increment("bugs_found", 8)
        eval_if.metrics.record("fix_time_ms", 100)
        eval_if.metrics.record("fix_time_ms", 200)

        assert eval_if.metrics.get_counter("bugs_found") == 8
        assert eval_if.metrics.get_metric_avg("fix_time_ms") == 150


class TestBugPrioritization:
    """Tests for bug prioritization."""

    def test_security_bugs_first(self):
        tracker = BugTracker()

        tracker.add_bug(BugReport(
            id="BUG_1",
            title="Logic error",
            description="",
            file_path="test.py",
            line_number=10,
            category=BugCategory.LOGIC,
            severity=BugSeverity.MEDIUM,
        ))

        tracker.add_bug(BugReport(
            id="BUG_2",
            title="SQL injection",
            description="",
            file_path="test.py",
            line_number=20,
            category=BugCategory.SECURITY,
            severity=BugSeverity.CRITICAL,
        ))

        tracker.add_bug(BugReport(
            id="BUG_3",
            title="Spec violation",
            description="",
            file_path="test.py",
            line_number=30,
            category=BugCategory.SPEC,
            severity=BugSeverity.LOW,
        ))

        order = tracker.prioritize_bugs()

        assert order[0] == "BUG_2"

    def test_get_next_bug_follows_priority(self):
        tracker = BugTracker()

        tracker.add_bug(BugReport(
            id="BUG_1",
            title="Low priority",
            description="",
            file_path="test.py",
            line_number=10,
            category=BugCategory.SPEC,
            severity=BugSeverity.LOW,
        ))

        tracker.add_bug(BugReport(
            id="BUG_2",
            title="High priority",
            description="",
            file_path="test.py",
            line_number=20,
            category=BugCategory.SECURITY,
            severity=BugSeverity.CRITICAL,
        ))

        tracker.prioritize_bugs()
        next_bug = tracker.get_next_bug_to_fix()

        assert next_bug.id == "BUG_2"
