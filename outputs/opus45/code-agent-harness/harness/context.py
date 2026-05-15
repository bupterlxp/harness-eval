"""
C component - Context Manager for source, test, and fix history.

Manages three types of context:
1. Source context: Current file with surrounding lines
2. Test context: Test outputs and failure information
3. Fix history context: Previous attempts and their outcomes

Implements compression, retrieval, and priority interfaces.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import re


@dataclass
class SourceContext:
    """Context around a specific code location."""
    file_path: str
    start_line: int
    end_line: int
    content: str
    language: str = "python"
    focus_line: Optional[int] = None


@dataclass
class TestContext:
    """Context from test execution."""
    test_name: str
    status: str
    output: str
    traceback: Optional[str] = None
    relevant_lines: list[int] = field(default_factory=list)


@dataclass
class FixHistoryEntry:
    """Historical fix attempt context."""
    bug_id: str
    attempt_number: int
    diff: str
    outcome: str
    error_message: Optional[str] = None


class SourceContextManager:
    """Manages source code context with windowing."""

    def __init__(self, context_lines: int = 20) -> None:
        self._context_lines = context_lines
        self._file_cache: dict[str, list[str]] = {}

    def _load_file(self, file_path: str) -> list[str]:
        """Load and cache file lines."""
        if file_path not in self._file_cache:
            path = Path(file_path)
            if path.exists():
                self._file_cache[file_path] = path.read_text(encoding="utf-8").splitlines()
            else:
                self._file_cache[file_path] = []
        return self._file_cache[file_path]

    def invalidate_cache(self, file_path: Optional[str] = None) -> None:
        """Invalidate file cache."""
        if file_path:
            self._file_cache.pop(file_path, None)
        else:
            self._file_cache.clear()

    def get_context(
        self,
        file_path: str,
        line_number: int,
        window: Optional[int] = None,
    ) -> SourceContext:
        """Get source context around a line."""
        window = window or self._context_lines
        lines = self._load_file(file_path)

        start = max(0, line_number - window - 1)
        end = min(len(lines), line_number + window)

        content_lines = []
        for i in range(start, end):
            prefix = ">>> " if i == line_number - 1 else "    "
            content_lines.append(f"{i + 1:4d} {prefix}{lines[i]}")

        return SourceContext(
            file_path=file_path,
            start_line=start + 1,
            end_line=end,
            content="\n".join(content_lines),
            focus_line=line_number,
        )

    def get_full_file(self, file_path: str) -> SourceContext:
        """Get entire file content."""
        lines = self._load_file(file_path)
        content_lines = [f"{i + 1:4d}     {line}" for i, line in enumerate(lines)]
        return SourceContext(
            file_path=file_path,
            start_line=1,
            end_line=len(lines),
            content="\n".join(content_lines),
        )

    def search_pattern(self, file_path: str, pattern: str) -> list[int]:
        """Find lines matching a pattern."""
        lines = self._load_file(file_path)
        matches = []
        regex = re.compile(pattern, re.IGNORECASE)
        for i, line in enumerate(lines):
            if regex.search(line):
                matches.append(i + 1)
        return matches


class TestContextManager:
    """Manages test output context."""

    def __init__(self, max_output_length: int = 5000) -> None:
        self._max_output_length = max_output_length
        self._test_results: dict[str, TestContext] = {}

    def add_result(self, test_context: TestContext) -> None:
        """Add a test result."""
        self._test_results[test_context.test_name] = test_context

    def get_result(self, test_name: str) -> Optional[TestContext]:
        """Get a specific test result."""
        return self._test_results.get(test_name)

    def get_failures(self) -> list[TestContext]:
        """Get all failed tests."""
        return [tc for tc in self._test_results.values() if tc.status == "failed"]

    def clear(self) -> None:
        """Clear all test results."""
        self._test_results.clear()

    def compress_output(self, output: str) -> str:
        """Compress long test output."""
        if len(output) <= self._max_output_length:
            return output

        half = self._max_output_length // 2
        return (
            output[:half]
            + f"\n\n... [{len(output) - self._max_output_length} chars truncated] ...\n\n"
            + output[-half:]
        )

    def extract_relevant_lines(self, traceback: str, source_file: str) -> list[int]:
        """Extract line numbers from traceback for a file."""
        lines = []
        pattern = rf'{re.escape(source_file)}.*line (\d+)'
        for match in re.finditer(pattern, traceback):
            lines.append(int(match.group(1)))
        return lines


class FixHistoryManager:
    """Manages fix attempt history context."""

    def __init__(self, max_history_per_bug: int = 5) -> None:
        self._max_history = max_history_per_bug
        self._history: dict[str, list[FixHistoryEntry]] = {}

    def add_attempt(self, entry: FixHistoryEntry) -> None:
        """Add a fix attempt to history."""
        if entry.bug_id not in self._history:
            self._history[entry.bug_id] = []

        self._history[entry.bug_id].append(entry)
        if len(self._history[entry.bug_id]) > self._max_history:
            self._history[entry.bug_id] = self._history[entry.bug_id][-self._max_history:]

    def get_history(self, bug_id: str) -> list[FixHistoryEntry]:
        """Get fix history for a bug."""
        return self._history.get(bug_id, [])

    def get_last_attempt(self, bug_id: str) -> Optional[FixHistoryEntry]:
        """Get the most recent attempt for a bug."""
        history = self._history.get(bug_id, [])
        return history[-1] if history else None

    def clear(self, bug_id: Optional[str] = None) -> None:
        """Clear history for a bug or all bugs."""
        if bug_id:
            self._history.pop(bug_id, None)
        else:
            self._history.clear()


class ContextManager:
    """
    C component - Unified context management.

    Coordinates source, test, and history contexts
    with compression and priority retrieval.
    """

    def __init__(
        self,
        context_lines: int = 20,
        max_output_length: int = 5000,
        max_history_per_bug: int = 5,
    ) -> None:
        self.source = SourceContextManager(context_lines)
        self.tests = TestContextManager(max_output_length)
        self.history = FixHistoryManager(max_history_per_bug)

    def build_bug_context(self, bug_id: str, file_path: str, line_number: int) -> str:
        """Build comprehensive context for fixing a bug."""
        parts = []

        source_ctx = self.source.get_context(file_path, line_number)
        parts.append(f"=== Source Context ({file_path}:{line_number}) ===")
        parts.append(source_ctx.content)

        failures = self.tests.get_failures()
        if failures:
            parts.append("\n=== Relevant Test Failures ===")
            for tc in failures:
                parts.append(f"\n--- {tc.test_name} ---")
                parts.append(self.tests.compress_output(tc.output))
                if tc.traceback:
                    parts.append("Traceback:")
                    parts.append(tc.traceback)

        history = self.history.get_history(bug_id)
        if history:
            parts.append("\n=== Previous Fix Attempts ===")
            for entry in history[-3:]:
                parts.append(f"\n--- Attempt {entry.attempt_number} ({entry.outcome}) ---")
                parts.append(entry.diff[:500] if len(entry.diff) > 500 else entry.diff)
                if entry.error_message:
                    parts.append(f"Error: {entry.error_message}")

        return "\n".join(parts)

    def compress(self, text: str, max_length: int = 10000) -> str:
        """Compress text to fit within limits."""
        if len(text) <= max_length:
            return text
        half = max_length // 2
        return text[:half] + "\n\n[...truncated...]\n\n" + text[-half:]

    def clear_all(self) -> None:
        """Clear all contexts."""
        self.source.invalidate_cache()
        self.tests.clear()
        self.history.clear()
