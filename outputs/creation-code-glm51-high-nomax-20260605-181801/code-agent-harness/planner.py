"""Planner: parse the task prompt, inspect the repository, and build a plan.

Extracts target files, test commands, constraints, and success criteria from
the task description and the repository structure. Produces a structured plan
that the main loop can execute step-by-step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import try_tool


@dataclass
class TaskPlan:
    """Structured plan extracted from the task prompt and repo inspection."""
    prompt: str
    target_files: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    lint_commands: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    domain: str = "code"
    repo_language: str = ""
    repo_framework: str = ""
    key_symbols: list[str] = field(default_factory=list)
    error_patterns: list[str] = field(default_factory=list)
    todo_items: list[dict[str, Any]] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 3


# File patterns for detecting project types
_PYTHON_TEST_PATTERNS = [
    "pytest", "python -m pytest", "python -m unittest",
    "test_", "_test.py", "tests/",
]
_JS_TEST_PATTERNS = [
    "npm test", "yarn test", "jest", "mocha", "vitest",
]
_MAKE_PATTERNS = ["Makefile", "makefile", "GNUmakefile"]
_CMAKE_PATTERNS = ["CMakeLists.txt"]
_CARGO_PATTERNS = ["Cargo.toml"]
_GO_PATTERNS = ["go.mod"]

_TEST_FILE_GLOBS = [
    "test_*.py", "*_test.py", "*_test.go", "*_test.js", "*_test.ts",
    "*Test*.java", "*Spec*.java", "*spec.js", "*spec.ts",
]

_LANG_EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".java": "java", ".go": "go", ".rs": "rust", ".c": "c",
    ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".rb": "ruby",
    ".php": "php", ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
}


def extract_paths_from_prompt(prompt: str) -> list[str]:
    """Extract file paths mentioned in the prompt."""
    paths: list[str] = []
    # Match paths like src/foo.py, /app/gpt2.c, tests/test_x.py
    for m in re.finditer(
        r'(?:^|[\s`"\'])([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)(?:[\s`"\']|$|,|:)',
        prompt,
    ):
        candidate = m.group(1)
        if not candidate.startswith("http") and "/" in candidate or "." in candidate.split("/")[-1]:
            if len(candidate) > 3 and candidate.count(".") < 4:
                paths.append(candidate)
    return paths


def extract_test_commands_from_prompt(prompt: str) -> list[str]:
    """Extract test or verification commands from the prompt."""
    commands: list[str] = []
    for pattern in [
        r'pytest\s+[^\n]+',
        r'python\s+-m\s+\w+\s+[^\n]+',
        r'npm\s+test[^\n]*',
        r'cargo\s+test[^\n]*',
        r'go\s+test[^\n]*',
        r'make\s+test[^\n]*',
        r'python\s+[^\n]*test[^\n]*',
    ]:
        for m in re.finditer(pattern, prompt):
            cmd = m.group(0).strip().rstrip(".,;)")
            if cmd not in commands:
                commands.append(cmd)
    return commands


async def inspect_repo(
    ctx: RuntimeContext, tools: ToolRegistry
) -> dict[str, Any]:
    """Inspect the repository structure and return metadata."""
    result: dict[str, Any] = {
        "top_files": [],
        "has_git": False,
        "languages": set(),
        "test_files": [],
        "config_files": [],
        "entry_points": [],
    }

    # Check for git
    ok, gs = await try_tool(ctx, tools, "git_status", {})
    if ok and gs and gs.ok:
        result["has_git"] = True

    # List top-level files
    ok, tree_res = await try_tool(ctx, tools, "tree", {
        "path": str(ctx.workdir), "depth": 2, "max_entries": 200,
    })
    if ok and tree_res and tree_res.ok and isinstance(tree_res.data, dict):
        entries = tree_res.data.get("entries", [])
        for entry in entries:
            if isinstance(entry, str):
                result["top_files"].append(entry)
            elif isinstance(entry, dict):
                result["top_files"].append(entry.get("name", str(entry)))

    # Find test files
    for glob_pat in _TEST_FILE_GLOBS:
        ok, glob_res = await try_tool(ctx, tools, "glob", {
            "pattern": glob_pat, "path": str(ctx.workdir),
        })
        if ok and glob_res and glob_res.ok and isinstance(glob_res.data, dict):
            matches = glob_res.data.get("matches", [])
            result["test_files"].extend(matches)

    # Detect languages from file extensions
    ok, glob_res = await try_tool(ctx, tools, "glob", {
        "pattern": "**/*", "path": str(ctx.workdir),
    })
    if ok and glob_res and glob_res.ok and isinstance(glob_res.data, dict):
        matches = glob_res.data.get("matches", [])
        for m in matches:
            ext = Path(m).suffix.lower()
            if ext in _LANG_EXTENSIONS:
                result["languages"].add(_LANG_EXTENSIONS[ext])

    result["languages"] = list(result["languages"])
    return result


def detect_test_command(repo_info: dict[str, Any], plan: TaskPlan) -> list[str]:
    """Detect the most likely test command for the repo."""
    commands: list[str] = []
    languages = repo_info.get("languages", [])
    top_files = repo_info.get("top_files", [])
    test_files = repo_info.get("test_files", [])

    if "python" in languages:
        if test_files or any("test" in f.lower() for f in top_files):
            commands.append("python -m pytest -x --tb=short -q 2>&1 | head -100")
            commands.append("python -m pytest --tb=short -q 2>&1 | head -100")

    if "javascript" in languages or "typescript" in languages:
        if "package.json" in top_files:
            commands.append("npm test 2>&1 | head -100")

    if "go" in languages:
        commands.append("go test ./... 2>&1 | head -100")

    if "rust" in languages:
        commands.append("cargo test 2>&1 | head -100")

    if "java" in languages:
        if "pom.xml" in top_files:
            commands.append("mvn test 2>&1 | head -100")
        elif "build.gradle" in top_files:
            commands.append("./gradlew test 2>&1 | head -100")

    if "c" in languages or "cpp" in languages:
        if any(f in top_files for f in _MAKE_PATTERNS):
            commands.append("make test 2>&1 | head -100")
            commands.append("make check 2>&1 | head -100")

    return commands


def detect_framework(repo_info: dict[str, Any]) -> tuple[str, str]:
    """Return (language, framework) detected from repo."""
    languages = repo_info.get("languages", [])
    top_files = repo_info.get("top_files", [])

    if "python" in languages:
        if "setup.py" in top_files or "pyproject.toml" in top_files:
            return "python", "setuptools"
        if "requirements.txt" in top_files:
            return "python", "pip"
        return "python", ""

    if "javascript" in languages or "typescript" in languages:
        if "package.json" in top_files:
            return "javascript", "npm"
        return "javascript", ""

    if "go" in languages:
        return "go", "go_modules"

    if "rust" in languages:
        return "rust", "cargo"

    if "java" in languages:
        if "pom.xml" in top_files:
            return "java", "maven"
        if "build.gradle" in top_files:
            return "java", "gradle"
        return "java", ""

    lang = languages[0] if languages else ""
    return lang, ""


async def build_plan(
    ctx: RuntimeContext, tools: ToolRegistry
) -> TaskPlan:
    """Build a TaskPlan from the prompt and repo inspection."""
    prompt = ctx.task.prompt or ""
    meta = ctx.task.metadata or {}
    max_steps = ctx.policy.max_steps if ctx.policy else 50
    max_iterations = max(1, min(max_steps // 5, 8))

    plan = TaskPlan(
        prompt=prompt,
        domain=meta.get("domain") or ctx.task.domain or "code",
        max_iterations=max_iterations,
    )

    # Extract explicit paths and commands from the prompt
    plan.target_files = extract_paths_from_prompt(prompt)
    plan.test_commands = extract_test_commands_from_prompt(prompt)
    if meta.get("test_command"):
        plan.test_commands.insert(0, str(meta["test_command"]))

    # Inspect the repo
    repo_info = await inspect_repo(ctx, tools)
    lang, framework = detect_framework(repo_info)
    plan.repo_language = lang
    plan.repo_framework = framework

    # Auto-detect test commands if not in prompt
    if not plan.test_commands:
        plan.test_commands = detect_test_command(repo_info, plan)

    # Auto-detect build commands
    top_files = repo_info.get("top_files", [])
    if "python" in (lang,) and ("setup.py" in top_files or "pyproject.toml" in top_files):
        plan.build_commands.append("pip install -e . 2>&1 | tail -5")
    if any(f in top_files for f in _MAKE_PATTERNS):
        plan.build_commands.append("make 2>&1 | tail -20")

    # Build success criteria
    if plan.target_files:
        plan.success_criteria.append(
            f"Target files must exist and be non-empty: {', '.join(plan.target_files)}"
        )
    if plan.test_commands:
        plan.success_criteria.append("Tests pass (exit code 0)")
    plan.success_criteria.append("Code changes produce a valid diff/patch")

    ctx.trajectory.log_info(
        "plan_built",
        target_files=plan.target_files,
        test_commands=plan.test_commands,
        language=lang,
        framework=framework,
        iterations=max_iterations,
    )

    return plan
