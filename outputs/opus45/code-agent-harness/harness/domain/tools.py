"""
Domain-specific tools for code manipulation.

Tools:
- CodeSearcher: Find code patterns/symbols
- FileEditor: Read/write/patch files
- TestRunner: Run pytest selectively or fully
- GitOperator: Stage, commit, diff
- StaticAnalyzer: AST-based code analysis
"""

import ast
import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from harness.tools import Tool, ToolExecutionError
from harness.schemas import TestResult


class CodeSearchInput(BaseModel):
    """Input for code search."""
    pattern: str = Field(description="Regex pattern to search for")
    file_glob: str = Field(default="**/*.py", description="Glob pattern for files")
    context_lines: int = Field(default=3, description="Lines of context around matches")


class CodeSearchMatch(BaseModel):
    """A single search match."""
    file_path: str
    line_number: int
    line_content: str
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)


class CodeSearchOutput(BaseModel):
    """Output from code search."""
    matches: list[CodeSearchMatch]
    total_matches: int
    files_searched: int


class CodeSearcher(Tool[CodeSearchInput, CodeSearchOutput]):
    """Search for code patterns across files."""

    name = "code_searcher"
    description = "Search for code patterns using regex"
    input_schema = CodeSearchInput
    output_schema = CodeSearchOutput

    def __init__(self, work_dir: Path) -> None:
        super().__init__()
        self._work_dir = work_dir

    def execute(self, input_data: CodeSearchInput) -> CodeSearchOutput:
        pattern = re.compile(input_data.pattern, re.IGNORECASE)
        matches = []
        files_searched = 0

        for file_path in self._work_dir.glob(input_data.file_glob):
            if not file_path.is_file():
                continue
            files_searched += 1

            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            for i, line in enumerate(lines):
                if pattern.search(line):
                    start = max(0, i - input_data.context_lines)
                    end = min(len(lines), i + input_data.context_lines + 1)

                    match = CodeSearchMatch(
                        file_path=str(file_path.relative_to(self._work_dir)),
                        line_number=i + 1,
                        line_content=line,
                        context_before=lines[start:i],
                        context_after=lines[i + 1:end],
                    )
                    matches.append(match)

        return CodeSearchOutput(
            matches=matches,
            total_matches=len(matches),
            files_searched=files_searched,
        )


class FileReadInput(BaseModel):
    """Input for file read."""
    path: str = Field(description="Path to file")
    start_line: Optional[int] = Field(default=None, description="Starting line (1-indexed)")
    end_line: Optional[int] = Field(default=None, description="Ending line (inclusive)")


class FileReadOutput(BaseModel):
    """Output from file read."""
    content: str
    total_lines: int
    path: str


class FileWriteInput(BaseModel):
    """Input for file write."""
    path: str = Field(description="Path to file")
    content: str = Field(description="Content to write")


class FileWriteOutput(BaseModel):
    """Output from file write."""
    path: str
    bytes_written: int
    success: bool


class FilePatchInput(BaseModel):
    """Input for file patch."""
    path: str = Field(description="Path to file")
    old_content: str = Field(description="Content to replace")
    new_content: str = Field(description="Replacement content")


class FilePatchOutput(BaseModel):
    """Output from file patch."""
    path: str
    success: bool
    diff: str
    replacements: int


class FileEditor(Tool):
    """Read, write, and patch files."""

    name = "file_editor"
    description = "Read, write, or patch files"
    input_schema = FileReadInput
    output_schema = FileReadOutput

    def __init__(self, work_dir: Path) -> None:
        self._work_dir = work_dir

    def execute(self, input_data: FileReadInput) -> FileReadOutput:
        path = self._work_dir / input_data.path
        if not path.exists():
            raise ToolExecutionError(self.name, f"File not found: {input_data.path}")

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()

        if input_data.start_line or input_data.end_line:
            start = (input_data.start_line or 1) - 1
            end = input_data.end_line or len(lines)
            content = "\n".join(lines[start:end])

        return FileReadOutput(
            content=content,
            total_lines=len(lines),
            path=str(path),
        )

    def read(self, path: str, start_line: int = None, end_line: int = None) -> FileReadOutput:
        """Read a file."""
        return self.execute(FileReadInput(path=path, start_line=start_line, end_line=end_line))

    def write(self, path: str, content: str) -> FileWriteOutput:
        """Write content to a file."""
        file_path = self._work_dir / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return FileWriteOutput(
            path=str(file_path),
            bytes_written=len(content.encode("utf-8")),
            success=True,
        )

    def patch(self, path: str, old_content: str, new_content: str) -> FilePatchOutput:
        """Replace content in a file."""
        file_path = self._work_dir / path
        if not file_path.exists():
            raise ToolExecutionError(self.name, f"File not found: {path}")

        original = file_path.read_text(encoding="utf-8")
        if old_content not in original:
            raise ToolExecutionError(
                self.name,
                f"Content to replace not found in {path}",
            )

        count = original.count(old_content)
        modified = original.replace(old_content, new_content)
        file_path.write_text(modified, encoding="utf-8")

        diff = "\n".join(difflib.unified_diff(
            original.splitlines(),
            modified.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        ))

        return FilePatchOutput(
            path=str(file_path),
            success=True,
            diff=diff,
            replacements=count,
        )


class TestRunInput(BaseModel):
    """Input for test run."""
    pattern: Optional[str] = Field(default=None, description="Test name pattern to match")
    file_path: Optional[str] = Field(default=None, description="Specific test file")
    verbose: bool = Field(default=True, description="Verbose output")
    full: bool = Field(default=False, description="Run all tests")


class TestRunOutput(BaseModel):
    """Output from test run."""
    result: TestResult
    output: str
    command: str


class TestRunner(Tool[TestRunInput, TestRunOutput]):
    """Run pytest tests."""

    name = "test_runner"
    description = "Run pytest tests selectively or fully"
    input_schema = TestRunInput
    output_schema = TestRunOutput

    def __init__(self, work_dir: Path) -> None:
        super().__init__()
        self._work_dir = work_dir

    def execute(self, input_data: TestRunInput) -> TestRunOutput:
        cmd = ["python", "-m", "pytest"]

        if input_data.verbose:
            cmd.append("-v")

        cmd.append("--tb=short")

        if not input_data.full:
            if input_data.file_path:
                cmd.append(input_data.file_path)
            if input_data.pattern:
                cmd.extend(["-k", input_data.pattern])

        try:
            result = subprocess.run(
                cmd,
                cwd=self._work_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = result.stdout + result.stderr
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            output = "Test execution timed out after 300 seconds"
            returncode = -1
        except Exception as e:
            output = f"Failed to run tests: {e}"
            returncode = -1

        test_result = self._parse_output(output, returncode)

        return TestRunOutput(
            result=test_result,
            output=output,
            command=" ".join(cmd),
        )

    def _parse_output(self, output: str, returncode: int) -> TestResult:
        """Parse pytest output to extract results."""
        passed = failed = errors = skipped = 0

        summary_match = re.search(
            r"(\d+) passed",
            output,
        )
        if summary_match:
            passed = int(summary_match.group(1))

        failed_match = re.search(r"(\d+) failed", output)
        if failed_match:
            failed = int(failed_match.group(1))

        error_match = re.search(r"(\d+) error", output)
        if error_match:
            errors = int(error_match.group(1))

        skipped_match = re.search(r"(\d+) skipped", output)
        if skipped_match:
            skipped = int(skipped_match.group(1))

        failures = []
        failure_sections = re.findall(
            r"FAILED ([^\n]+)\n(.*?)(?=FAILED|\Z)",
            output,
            re.DOTALL,
        )
        for test_name, details in failure_sections:
            failures.append({
                "test": test_name.strip(),
                "details": details.strip()[:500],
            })

        return TestResult(
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            total=passed + failed + errors + skipped,
            duration_ms=0.0,
            failures=failures,
            output=output,
        )


class GitStatusInput(BaseModel):
    """Input for git status."""
    pass


class GitStatusOutput(BaseModel):
    """Output from git status."""
    clean: bool
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]


class GitStageInput(BaseModel):
    """Input for git stage."""
    files: list[str] = Field(description="Files to stage")


class GitStageOutput(BaseModel):
    """Output from git stage."""
    staged: list[str]
    success: bool


class GitCommitInput(BaseModel):
    """Input for git commit."""
    message: str = Field(description="Commit message")


class GitCommitOutput(BaseModel):
    """Output from git commit."""
    commit_hash: str
    message: str
    files_changed: int
    success: bool


class GitDiffInput(BaseModel):
    """Input for git diff."""
    staged: bool = Field(default=False, description="Show staged changes")
    file_path: Optional[str] = Field(default=None, description="Specific file")


class GitDiffOutput(BaseModel):
    """Output from git diff."""
    diff: str
    files_changed: list[str]


class GitOperator(Tool):
    """Perform git operations."""

    name = "git_operator"
    description = "Stage, commit, and diff git changes"
    input_schema = GitStatusInput
    output_schema = GitStatusOutput

    def __init__(self, work_dir: Path) -> None:
        self._work_dir = work_dir

    def execute(self, input_data: GitStatusInput) -> GitStatusOutput:
        return self.status()

    def _run_git(self, *args: str) -> tuple[str, int]:
        """Run a git command."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._work_dir,
                capture_output=True,
                text=True,
            )
            return result.stdout + result.stderr, result.returncode
        except Exception as e:
            return str(e), -1

    def status(self) -> GitStatusOutput:
        """Get git status."""
        output, _ = self._run_git("status", "--porcelain")
        staged = []
        unstaged = []
        untracked = []

        for line in output.strip().splitlines():
            if not line:
                continue
            status = line[:2]
            file_path = line[3:]

            if status[0] in "MADRC":
                staged.append(file_path)
            if status[1] in "MD":
                unstaged.append(file_path)
            if status == "??":
                untracked.append(file_path)

        return GitStatusOutput(
            clean=not (staged or unstaged or untracked),
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
        )

    def stage(self, files: list[str]) -> GitStageOutput:
        """Stage files."""
        for f in files:
            self._run_git("add", f)
        return GitStageOutput(staged=files, success=True)

    def commit(self, message: str) -> GitCommitOutput:
        """Create a commit."""
        output, returncode = self._run_git("commit", "-m", message)
        if returncode != 0:
            raise ToolExecutionError(self.name, f"Commit failed: {output}")

        hash_output, _ = self._run_git("rev-parse", "HEAD")
        commit_hash = hash_output.strip()[:7]

        files_output, _ = self._run_git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        files_changed = len(files_output.strip().splitlines())

        return GitCommitOutput(
            commit_hash=commit_hash,
            message=message,
            files_changed=files_changed,
            success=True,
        )

    def diff(self, staged: bool = False, file_path: str = None) -> GitDiffOutput:
        """Get diff."""
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.append(file_path)

        output, _ = self._run_git(*args)

        files = []
        for line in output.splitlines():
            if line.startswith("diff --git"):
                parts = line.split()
                if len(parts) >= 4:
                    files.append(parts[3][2:])

        return GitDiffOutput(diff=output, files_changed=files)


class ASTAnalyzeInput(BaseModel):
    """Input for AST analysis."""
    path: str = Field(description="Path to Python file")
    analysis: str = Field(
        default="functions",
        description="Type of analysis: functions, classes, imports, all",
    )


class FunctionInfo(BaseModel):
    """Information about a function."""
    name: str
    line_number: int
    args: list[str]
    decorators: list[str]
    docstring: Optional[str]


class ClassInfo(BaseModel):
    """Information about a class."""
    name: str
    line_number: int
    bases: list[str]
    methods: list[str]
    docstring: Optional[str]


class ASTAnalyzeOutput(BaseModel):
    """Output from AST analysis."""
    path: str
    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class StaticAnalyzer(Tool[ASTAnalyzeInput, ASTAnalyzeOutput]):
    """Perform AST-based static analysis."""

    name = "static_analyzer"
    description = "Analyze Python code structure using AST"
    input_schema = ASTAnalyzeInput
    output_schema = ASTAnalyzeOutput

    def __init__(self, work_dir: Path) -> None:
        super().__init__()
        self._work_dir = work_dir

    def execute(self, input_data: ASTAnalyzeInput) -> ASTAnalyzeOutput:
        path = self._work_dir / input_data.path
        if not path.exists():
            raise ToolExecutionError(self.name, f"File not found: {input_data.path}")

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            raise ToolExecutionError(self.name, f"Syntax error: {e}")

        result = ASTAnalyzeOutput(path=input_data.path)

        if input_data.analysis in ("functions", "all"):
            result.functions = self._extract_functions(tree)

        if input_data.analysis in ("classes", "all"):
            result.classes = self._extract_classes(tree)

        if input_data.analysis in ("imports", "all"):
            result.imports = self._extract_imports(tree)

        return result

    def _extract_functions(self, tree: ast.AST) -> list[FunctionInfo]:
        """Extract function information."""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(FunctionInfo(
                    name=node.name,
                    line_number=node.lineno,
                    args=[arg.arg for arg in node.args.args],
                    decorators=[
                        ast.unparse(d) if hasattr(ast, "unparse") else str(d)
                        for d in node.decorator_list
                    ],
                    docstring=ast.get_docstring(node),
                ))
        return functions

    def _extract_classes(self, tree: ast.AST) -> list[ClassInfo]:
        """Extract class information."""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, ast.FunctionDef)
                ]
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(f"{base.value.id}.{base.attr}" if isinstance(base.value, ast.Name) else base.attr)

                classes.append(ClassInfo(
                    name=node.name,
                    line_number=node.lineno,
                    bases=bases,
                    methods=methods,
                    docstring=ast.get_docstring(node),
                ))
        return classes

    def _extract_imports(self, tree: ast.AST) -> list[str]:
        """Extract import statements."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
        return imports


def create_tool_registry(work_dir: Path):
    """Create a tool registry with all domain tools."""
    from harness.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register(CodeSearcher(work_dir))
    registry.register(FileEditor(work_dir))
    registry.register(TestRunner(work_dir))
    registry.register(GitOperator(work_dir))
    registry.register(StaticAnalyzer(work_dir))

    return registry
