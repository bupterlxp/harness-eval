"""Verifier: run tests, syntax checks, build commands, and validate artifacts.

Executes the most relevant verification command for the repo, captures results,
and returns structured verification status. Used by the main loop to determine
whether edits were successful.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import try_tool


@dataclass
class VerificationResult:
    """Result of running verification commands."""
    passed: bool = False
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    syntax_ok: bool = True
    artifacts_exist: bool = False
    artifacts_non_empty: bool = False
    details: dict[str, Any] = field(default_factory=dict)


async def verify_syntax(
    ctx: RuntimeContext, tools: ToolRegistry, target_files: list[str]
) -> dict[str, bool]:
    """Check syntax of target files. Returns {path: ok} mapping."""
    results: dict[str, bool] = {}
    for rel_path in target_files:
        abs_path = ctx.workdir / rel_path
        if not abs_path.exists():
            results[rel_path] = False
            continue
        if abs_path.suffix == ".py":
            ok, res = await try_tool(ctx, tools, "bash", {
                "command": f"python3 -c 'import py_compile; py_compile.compile(\"{str(abs_path)}\", doraise=True)' 2>&1",
            })
            if ok and res:
                results[rel_path] = res.ok
            else:
                results[rel_path] = False
        elif abs_path.suffix in (".js", ".ts"):
            ok, res = await try_tool(ctx, tools, "bash", {
                "command": f"node --check {rel_path} 2>&1",
            })
            if ok and res:
                results[rel_path] = res.ok
            else:
                results[rel_path] = True  # No syntax checker available, assume ok
        else:
            results[rel_path] = True  # Can't check syntax, assume ok
    return results


async def verify_artifacts(
    ctx: RuntimeContext,
    target_files: list[str],
    require_patch: bool = True,
) -> dict[str, Any]:
    """Check that required artifacts exist and are non-empty."""
    result: dict[str, Any] = {
        "targets_exist": True,
        "targets_non_empty": True,
        "patch_exists": False,
        "missing": [],
        "empty": [],
    }

    for rel_path in target_files:
        abs_path = ctx.workdir / rel_path
        if not abs_path.exists():
            result["targets_exist"] = False
            result["missing"].append(rel_path)
            continue
        try:
            if abs_path.stat().st_size == 0:
                result["targets_non_empty"] = False
                result["empty"].append(rel_path)
        except OSError:
            result["targets_exist"] = False
            result["missing"].append(rel_path)

    # Check for patch/diff in output directory
    for name in ("patch.diff", "response.md"):
        candidate = ctx.out_dir / name
        if candidate.exists() and candidate.stat().st_size > 0:
            result["patch_exists"] = True
            break

    return result


async def run_test_command(
    ctx: RuntimeContext,
    tools: ToolRegistry,
    command: str,
    timeout: float = 120.0,
) -> VerificationResult:
    """Run a single test command and return a VerificationResult."""
    result = VerificationResult(command=command)

    ok, res = await try_tool(ctx, tools, "bash", {
        "command": command,
        "timeout": timeout,
    })

    if not ok or res is None:
        result.passed = False
        result.stderr = "bash tool unavailable"
        return result

    data = res.data if res.ok else (res.error or {})
    if isinstance(data, dict):
        result.stdout = str(data.get("stdout", ""))[:10000]
        result.stderr = str(data.get("stderr", ""))[:5000]
        result.exit_code = data.get("exit_code", -1)
        result.timed_out = data.get("timed_out", False)

    result.passed = res.ok and result.exit_code == 0
    return result


async def run_verification(
    ctx: RuntimeContext,
    tools: ToolRegistry,
    test_commands: list[str],
    target_files: list[str],
    iteration: int = 0,
) -> VerificationResult:
    """Run the full verification pipeline: syntax, tests, artifacts."""
    combined = VerificationResult()

    # 1. Syntax check target files
    if target_files:
        syntax_results = await verify_syntax(ctx, tools, target_files)
        combined.syntax_ok = all(syntax_results.values())
        combined.details["syntax"] = syntax_results

    # 2. Run test commands (try each until one works)
    if test_commands:
        # Try a subset of test commands based on iteration to avoid wasting budget
        cmds_to_try = test_commands[:min(2 + iteration, len(test_commands))]
        for cmd in cmds_to_try:
            test_result = await run_test_command(ctx, tools, cmd)
            combined.command = cmd
            combined.exit_code = test_result.exit_code
            combined.stdout = test_result.stdout
            combined.stderr = test_result.stderr
            combined.timed_out = test_result.timed_out
            if test_result.passed:
                combined.passed = True
                break
            # If the command ran but failed, capture the error for diagnosis
            combined.details["test_output"] = test_result.stdout[:3000]
            combined.details["test_error"] = test_result.stderr[:3000]

    # 3. Check artifacts
    artifact_result = await verify_artifacts(ctx, target_files)
    combined.artifacts_exist = artifact_result["targets_exist"]
    combined.artifacts_non_empty = artifact_result["targets_non_empty"]
    combined.details["artifacts"] = artifact_result

    # Overall pass: tests pass (or no tests) AND syntax ok AND artifacts exist
    test_passed = combined.passed or not test_commands
    combined.passed = test_passed and combined.syntax_ok and combined.artifacts_exist

    return combined
