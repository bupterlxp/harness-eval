"""
H component - Core harness assembling all six components.

H = (E, T, C, S, L, V)

Coordinates:
- E: Execution state machine
- T: Tool registry
- C: Context manager
- S: State store
- L: Lifecycle hooks
- V: Evaluation interface
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import re

from harness.schemas import (
    BugReport,
    BugStatus,
    BugCategory,
    BugSeverity,
    CommitRecord,
    FixAttempt,
    TestResult,
)
from harness.state import StateStore
from harness.tools import ToolRegistry
from harness.context import ContextManager, TestContext, FixHistoryEntry
from harness.lifecycle import LifecycleManager
from harness.evaluation import EvaluationInterface
from harness.execution import (
    ExecutionStateMachine,
    ExecutionLoop,
    ExecutionContext,
    MainState,
    FixState,
    Event,
)
from harness.domain.tools import (
    create_tool_registry,
    FileEditor,
    TestRunner,
    GitOperator,
    CodeSearcher,
    StaticAnalyzer,
)
from harness.domain import prompts


@dataclass
class HarnessConfig:
    """Configuration for the harness."""
    work_dir: Path
    target_file: str = "buggy_server.py"
    test_file: str = "test_server.py"
    max_fix_attempts: int = 3
    auto_commit: bool = True
    verbose: bool = True


class CodeAgentHarness:
    """
    Main harness class assembling all six components.

    H = (E, T, C, S, L, V)
    """

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.work_dir = config.work_dir

        self.state = StateStore(config.work_dir)
        self.tools = create_tool_registry(config.work_dir)
        self.context = ContextManager()
        self.lifecycle = LifecycleManager(config.work_dir)
        self.evaluation = EvaluationInterface(config.work_dir)

        self._sm = ExecutionStateMachine()
        self._loop = ExecutionLoop(self._sm)
        self._register_handlers()

        self._current_bug: Optional[BugReport] = None
        self._output_callback: Optional[Callable[[str], None]] = None

    def _register_handlers(self) -> None:
        """Register state handlers."""
        self._sm.register_handler(MainState.INDEX, self._handle_index)
        self._sm.register_handler(MainState.TEST, self._handle_test)
        self._sm.register_handler(MainState.CLASSIFY, self._handle_classify)
        self._sm.register_handler(MainState.PRIORITIZE, self._handle_prioritize)
        self._sm.register_handler("FIX_LOCATE", self._handle_fix_locate)
        self._sm.register_handler("FIX_ANALYZE", self._handle_fix_analyze)
        self._sm.register_handler("FIX_FIX", self._handle_fix_apply)
        self._sm.register_handler("FIX_VERIFY", self._handle_fix_verify)
        self._sm.register_handler("FIX_COMMIT", self._handle_fix_commit)
        self._sm.register_handler(MainState.REGRESSION, self._handle_regression)
        self._sm.register_handler(MainState.REPORT, self._handle_report)

    def set_output_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for output messages."""
        self._output_callback = callback

    def _output(self, message: str) -> None:
        """Send output message."""
        if self._output_callback:
            self._output_callback(message)
        if self.config.verbose:
            print(message)

    def run(self) -> dict:
        """Run the full bug fixing workflow."""
        self._output(f"Starting code agent harness in {self.work_dir}")

        ctx = ExecutionContext(
            work_dir=self.work_dir,
            target_files=[self.config.target_file],
            test_files=[self.config.test_file],
        )

        def step_callback(state: MainState, event: Event) -> None:
            self.evaluation.begin_step(state.name, event.name)
            self._output(f"[{state.name}] Event: {event.name}")
            self.evaluation.end_step()

        self._loop.set_step_callback(step_callback)

        try:
            final_ctx = self._loop.run(ctx)
            report = self.evaluation.get_report()
            self.evaluation.export()
            return {
                "success": self._sm.state == MainState.COMPLETED,
                "state": self._sm.state.name,
                "progress": self.state.bug_tracker.get_progress(),
                "report": report,
            }
        except Exception as e:
            self._output(f"Error: {e}")
            return {
                "success": False,
                "state": self._sm.state.name,
                "error": str(e),
            }

    def _handle_index(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """INDEX: Scan project structure."""
        self.evaluation.begin_step("INDEX", "scanning_project")

        target_path = self.work_dir / self.config.target_file
        test_path = self.work_dir / self.config.test_file

        if not target_path.exists():
            self._output(f"Target file not found: {target_path}")
            self.evaluation.end_step()
            return Event.ERROR, ctx

        if not test_path.exists():
            self._output(f"Test file not found: {test_path}")
            self.evaluation.end_step()
            return Event.ERROR, ctx

        analyzer = self.tools.get("static_analyzer")
        result, tool_call = analyzer.run({"path": self.config.target_file, "analysis": "all"})
        self.evaluation.record_tool_call(tool_call)

        self._output(f"Indexed {self.config.target_file}: {len(result.functions)} functions, {len(result.classes)} classes")
        self.evaluation.end_step()

        return Event.INDEX_COMPLETE, ctx

    def _handle_test(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """TEST: Run initial tests."""
        self.evaluation.begin_step("TEST", "running_initial_tests")

        self.lifecycle.before_test_run()

        test_runner = self.tools.get("test_runner")
        result, tool_call = test_runner.run({
            "file_path": self.config.test_file,
            "full": True,
        })
        self.evaluation.record_tool_call(tool_call)
        self.evaluation.record_test_result(result.result)

        ctx.test_result = result.result
        self._output(f"Tests: {result.result.passed} passed, {result.result.failed} failed")

        for failure in result.result.failures:
            test_ctx = TestContext(
                test_name=failure.get("test", "unknown"),
                status="failed",
                output=failure.get("details", ""),
            )
            self.context.tests.add_result(test_ctx)

        self.evaluation.end_step()
        return Event.TEST_COMPLETE, ctx

    def _handle_classify(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """CLASSIFY: Classify failures by root cause."""
        self.evaluation.begin_step("CLASSIFY", "classifying_failures")

        file_editor = self.tools.get("file_editor")
        source_result, _ = file_editor.run({"path": self.config.target_file})
        test_result, _ = file_editor.run({"path": self.config.test_file})

        classified = prompts.classify_test_failures(
            ctx.test_result.output if ctx.test_result else "",
            source_result.content,
        )

        bug_markers = self._find_bug_markers(source_result.content)

        for marker in bug_markers:
            bug = BugReport(
                id=marker["id"],
                title=marker["title"],
                description=marker.get("description", ""),
                file_path=self.config.target_file,
                line_number=marker["line"],
                category=self._classify_bug_category(marker),
                severity=self._classify_bug_severity(marker),
            )
            self.state.bug_tracker.add_bug(bug)

        self._output(f"Classified {len(self.state.bug_tracker.get_all_bugs())} bugs")
        self.evaluation.end_step()

        return Event.CLASSIFY_COMPLETE, ctx

    def _find_bug_markers(self, content: str) -> list[dict]:
        """Find BUG markers in source code."""
        markers = []
        lines = content.splitlines()

        for i, line in enumerate(lines):
            match = re.search(r"#\s*BUG\s*(\d+):?\s*(.*)", line, re.IGNORECASE)
            if match:
                bug_id = f"BUG_{match.group(1)}"
                title = match.group(2).strip() or f"Bug {match.group(1)}"
                markers.append({
                    "id": bug_id,
                    "title": title,
                    "line": i + 1,
                    "raw": line,
                })

        return markers

    def _classify_bug_category(self, marker: dict) -> BugCategory:
        """Classify bug category from marker."""
        title_lower = marker["title"].lower()
        if "sql" in title_lower or "injection" in title_lower:
            return BugCategory.SECURITY
        if "timing" in title_lower or "after" in title_lower or "before" in title_lower:
            return BugCategory.TIMING
        if "logic" in title_lower or "and" in title_lower or "or" in title_lower:
            return BugCategory.LOGIC
        if "valid" in title_lower or "error" in title_lower:
            return BugCategory.VALIDATION
        if "200" in title_lower or "404" in title_lower or "status" in title_lower:
            return BugCategory.SPEC
        return BugCategory.CORRECTNESS

    def _classify_bug_severity(self, marker: dict) -> BugSeverity:
        """Classify bug severity from marker."""
        title_lower = marker["title"].lower()
        if "sql" in title_lower or "injection" in title_lower or "security" in title_lower:
            return BugSeverity.CRITICAL
        if "crash" in title_lower or "after" in title_lower:
            return BugSeverity.HIGH
        if "logic" in title_lower or "wrong" in title_lower:
            return BugSeverity.HIGH
        return BugSeverity.MEDIUM

    def _handle_prioritize(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """PRIORITIZE: Order bugs by severity."""
        self.evaluation.begin_step("PRIORITIZE", "prioritizing_bugs")

        order = self.state.bug_tracker.prioritize_bugs()
        self._output(f"Bug priority order: {order}")

        ctx.bugs = self.state.bug_tracker.get_all_bugs()
        self.evaluation.end_step()

        return Event.PRIORITIZE_COMPLETE, ctx

    def _handle_fix_locate(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """FIX/LOCATE: Find bug location."""
        self.evaluation.begin_step("FIX_LOCATE", "locating_bug")

        bug = self.state.bug_tracker.get_next_bug_to_fix()
        if not bug:
            self._output("All bugs processed")
            self.evaluation.end_step()
            return Event.ALL_BUGS_FIXED, ctx

        self._current_bug = bug
        ctx.current_bug = bug
        self.state.bug_tracker.update_status(bug.id, BugStatus.FIXING)

        self.state.snapshots.create_snapshot(
            bug.id,
            [self.work_dir / self.config.target_file],
        )

        self._output(f"Locating bug: {bug.id} - {bug.title} at line {bug.line_number}")
        self.evaluation.add_metadata("bug_id", bug.id)
        self.evaluation.end_step()

        return Event.LOCATE_COMPLETE, ctx

    def _handle_fix_analyze(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """FIX/ANALYZE: Understand root cause."""
        self.evaluation.begin_step("FIX_ANALYZE", "analyzing_bug")

        bug = self._current_bug
        if not bug:
            return Event.ERROR, ctx

        source_ctx = self.context.source.get_context(
            str(self.work_dir / bug.file_path),
            bug.line_number,
            window=15,
        )

        test_failures = self.context.tests.get_failures()
        test_output = "\n".join(tc.output for tc in test_failures[:3])

        analysis = prompts.analyze_bug(
            source_ctx.content,
            test_output,
            bug.file_path,
            bug.line_number,
        )

        bug.root_cause = analysis.get("root_cause", "Unknown")
        bug.fix_suggestion = analysis.get("fix_suggestion", "")

        self._output(f"Analysis: {bug.root_cause}")
        self.evaluation.add_metadata("root_cause", bug.root_cause)
        self.evaluation.end_step()

        return Event.ANALYZE_COMPLETE, ctx

    def _handle_fix_apply(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """FIX/FIX: Apply fix."""
        self.evaluation.begin_step("FIX_FIX", "applying_fix")

        bug = self._current_bug
        if not bug:
            return Event.ERROR, ctx

        self.lifecycle.before_file_modify(
            str(self.work_dir / bug.file_path),
            bug.id,
        )

        source_ctx = self.context.source.get_context(
            str(self.work_dir / bug.file_path),
            bug.line_number,
            window=20,
        )

        previous_attempts = [
            {"diff": a.diff, "error": a.error_message}
            for a in self.state.fix_history.get_attempts(bug.id)
        ]

        fix = prompts.generate_fix(
            bug,
            source_ctx.content,
            "",
            previous_attempts,
        )

        old_code = fix.get("old_code", "")
        new_code = fix.get("new_code", "")

        if not old_code or not new_code:
            self._output("Failed to generate fix")
            return Event.ERROR, ctx

        file_editor = self.tools.get("file_editor")
        try:
            result = file_editor.patch(bug.file_path, old_code, new_code)
            self.evaluation.record_diff(result.diff)
            self.context.source.invalidate_cache(str(self.work_dir / bug.file_path))
            self._output(f"Applied fix: {fix.get('explanation', 'N/A')}")
        except Exception as e:
            self._output(f"Failed to apply fix: {e}")
            return Event.ERROR, ctx

        self.evaluation.end_step()
        return Event.FIX_APPLIED, ctx

    def _handle_fix_verify(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """FIX/VERIFY: Run tests to verify."""
        self.evaluation.begin_step("FIX_VERIFY", "verifying_fix")

        bug = self._current_bug
        if not bug:
            return Event.ERROR, ctx

        test_runner = self.tools.get("test_runner")
        result, tool_call = test_runner.run({
            "file_path": self.config.test_file,
            "full": True,
        })
        self.evaluation.record_tool_call(tool_call)
        self.evaluation.record_test_result(result.result)

        attempt = FixAttempt(
            bug_id=bug.id,
            attempt_number=len(self.state.fix_history.get_attempts(bug.id)) + 1,
            diff="",
            success=result.result.failed == 0,
            tests_passed=result.result.passed,
            tests_failed=result.result.failed,
        )

        if result.result.failed > 0:
            attempt.error_message = f"{result.result.failed} tests still failing"
            self.state.fix_history.add_attempt(attempt)

            self.context.history.add_attempt(FixHistoryEntry(
                bug_id=bug.id,
                attempt_number=attempt.attempt_number,
                diff="",
                outcome="failed",
                error_message=attempt.error_message,
            ))

            self._output(f"Verification failed: {result.result.failed} tests failing")
            self.evaluation.end_step()
            return Event.VERIFY_FAILED, ctx

        self.state.fix_history.add_attempt(attempt)
        self._output(f"Verification passed: {result.result.passed} tests passing")
        self.evaluation.end_step()

        return Event.VERIFY_PASSED, ctx

    def _handle_fix_commit(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """FIX/COMMIT: Commit the fix."""
        self.evaluation.begin_step("FIX_COMMIT", "committing_fix")

        bug = self._current_bug
        if not bug:
            return Event.ERROR, ctx

        git = self.tools.get("git_operator")
        diff_result = git.diff()

        commit_msg = prompts.generate_commit_message(bug, diff_result.diff)

        validation = self.lifecycle.before_commit(bug.id, commit_msg)
        if not validation.success:
            self._output(f"Commit validation failed: {validation.message}")
            self.evaluation.end_step()
            return Event.ERROR, ctx

        git.stage([bug.file_path])
        commit_result = git.commit(commit_msg)

        record = CommitRecord(
            commit_hash=commit_result.commit_hash,
            bug_id=bug.id,
            message=commit_msg,
            files_changed=[bug.file_path],
        )
        self.state.commits.add_commit(record)

        self.state.bug_tracker.update_status(bug.id, BugStatus.FIXED)
        self.state.snapshots.clear_snapshot(bug.id)
        self.lifecycle.clear_rollback_state(bug.id)

        self._output(f"Committed fix for {bug.id}: {commit_result.commit_hash}")
        self.evaluation.add_metadata("commit_hash", commit_result.commit_hash)
        self.evaluation.end_step()

        next_bug = self.state.bug_tracker.get_next_bug_to_fix()
        if next_bug:
            return Event.BUG_SELECTED, ctx
        else:
            return Event.ALL_BUGS_FIXED, ctx

    def _handle_regression(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """REGRESSION: Run full test suite."""
        self.evaluation.begin_step("REGRESSION", "running_regression")

        test_runner = self.tools.get("test_runner")
        result, tool_call = test_runner.run({
            "file_path": self.config.test_file,
            "full": True,
        })
        self.evaluation.record_tool_call(tool_call)
        self.evaluation.record_test_result(result.result)

        self._output(f"Regression: {result.result.passed} passed, {result.result.failed} failed")

        if result.result.failed > 0:
            self._output("Regression failures detected")
            self.evaluation.end_step()
            return Event.REGRESSION_FAILED, ctx

        self.evaluation.end_step()
        return Event.REGRESSION_PASSED, ctx

    def _handle_report(self, ctx: ExecutionContext) -> tuple[Event, ExecutionContext]:
        """REPORT: Generate final report."""
        self.evaluation.begin_step("REPORT", "generating_report")

        progress = self.state.bug_tracker.get_progress()
        commits = self.state.commits.get_commits()

        report = {
            "summary": {
                "total_bugs": progress["total"],
                "fixed": progress["fixed"],
                "blocked": progress["blocked"],
                "success_rate": f"{progress['progress_pct']:.1f}%",
            },
            "commits": [
                {"hash": c.commit_hash, "bug": c.bug_id, "message": c.message[:50]}
                for c in commits
            ],
            "trajectory": self.evaluation.trajectory.get_summary(),
        }

        self._output("\n=== Fix Report ===")
        self._output(f"Bugs fixed: {progress['fixed']}/{progress['total']}")
        self._output(f"Commits: {len(commits)}")
        for c in commits:
            self._output(f"  - {c.commit_hash}: {c.bug_id}")

        self.state.save()
        self.evaluation.end_step()

        return Event.REPORT_COMPLETE, ctx

    def get_status(self) -> dict:
        """Get current status."""
        return {
            "state": self._sm.get_state_info(),
            "progress": self.state.bug_tracker.get_progress(),
            "current_bug": self._current_bug.id if self._current_bug else None,
        }

    def abort(self) -> None:
        """Abort the current run."""
        self._loop.abort()
        if self._current_bug:
            self.lifecycle.on_fix_failure(self._current_bug.id)
