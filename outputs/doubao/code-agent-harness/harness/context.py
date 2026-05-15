"""
Context management for the agent harness.
"""

import os
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict


@dataclass
class SourceContext:
    """Represents context around a source code location."""
    file_path: str
    line_number: int
    content: str
    surrounding_lines: int = 5
    before_content: str = ""
    after_content: str = ""

    def __post_init__(self):
        """Load surrounding content when initialized."""
        if os.path.exists(self.file_path):
            with open(self.file_path, 'r') as f:
                lines = f.readlines()

            start = max(0, self.line_number - 1 - self.surrounding_lines)
            end = min(len(lines), self.line_number + self.surrounding_lines)

            self.before_content = ''.join(lines[start:self.line_number-1])
            self.after_content = ''.join(lines[self.line_number:end])


@dataclass
class TestContext:
    """Represents context around test execution."""
    test_file: str
    test_name: Optional[str] = None
    output: str = ""
    error: str = ""
    passed: bool = False
    duration: float = 0.0


@dataclass
class FixHistoryContext:
    """Represents context around past fix attempts."""
    bug_id: int
    timestamp: float
    changes: Dict[str, Any] = field(default_factory=dict)
    success: bool = False
    test_results: List[Dict[str, Any]] = field(default_factory=list)


class ContextManager:
    """Manages source, test, and fix history contexts."""

    def __init__(self):
        self.source_cache: OrderedDict[str, str] = OrderedDict()
        self.test_contexts: List[TestContext] = []
        self.fix_history: List[FixHistoryContext] = []
        self.max_cache_size: int = 50

    def get_source_context(self, file_path: str, line_number: int, surrounding_lines: int = 5) -> SourceContext:
        """Get context around a specific source location."""
        # Cache the file content
        if file_path not in self.source_cache or len(self.source_cache) >= self.max_cache_size:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    self.source_cache[file_path] = content
                    # Evict oldest if cache full
                    if len(self.source_cache) > self.max_cache_size:
                        self.source_cache.popitem(last=False)

        return SourceContext(
            file_path=file_path,
            line_number=line_number,
            content=self.source_cache.get(file_path, ""),
            surrounding_lines=surrounding_lines
        )

    def add_test_context(self, test_context: TestContext) -> None:
        """Add a test context entry."""
        self.test_contexts.append(test_context)
        # Keep only last 100 test contexts
        if len(self.test_contexts) > 100:
            self.test_contexts = self.test_contexts[-100:]

    def add_fix_history(self, fix_context: FixHistoryContext) -> None:
        """Add a fix history entry."""
        self.fix_history.append(fix_context)

    def get_recent_fix_history(self, bug_id: Optional[int] = None, limit: int = 10) -> List[FixHistoryContext]:
        """Get recent fix history, optionally filtered by bug_id."""
        if bug_id is not None:
            filtered = [f for f in self.fix_history if f.bug_id == bug_id]
        else:
            filtered = self.fix_history

        return sorted(filtered, key=lambda x: x.timestamp, reverse=True)[:limit]

    def search_source(self, pattern: str, path: str = ".") -> List[Tuple[str, int, str]]:
        """Search source code for a pattern."""
        import re
        matches = []

        for root, dirs, files in os.walk(path):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r') as f:
                            lines = f.readlines()
                            for i, line in enumerate(lines):
                                if re.search(pattern, line, re.IGNORECASE):
                                    matches.append((file_path, i+1, line.strip()))
                    except:
                        continue

        return matches

    def compress_context(self, context: Any) -> str:
        """Compress context into a string for LLM processing."""
        if isinstance(context, SourceContext):
            return f"File: {context.file_path}\nLine: {context.line_number}\n\n{context.before_content}>>> {context.content[context.content.find('='*20)+2:] if '='*20 in context.content else context.content} <<<{context.after_content}"
        elif isinstance(context, TestContext):
            return f"Test: {context.test_name} in {context.test_file}\nPassed: {context.passed}\nOutput: {context.output[:200]}..." if len(context.output) > 200 else context.output
        elif isinstance(context, list) and all(isinstance(item, tuple) for item in context):
            # Source search results
            return "\n".join([f"{f}:{ln} - {l}" for f, ln, l in context[:10]])
        else:
            return str(context)[:500]