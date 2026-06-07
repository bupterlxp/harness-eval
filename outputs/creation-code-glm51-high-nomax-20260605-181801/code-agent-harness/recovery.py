"""Recovery: handle failures, manage checkpoints, and retry with different strategies.

Provides failure diagnosis, checkpoint/rollback management, and strategy
switching when the current approach isn't working.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import try_tool


@dataclass
class FailureDiagnosis:
    """Diagnosis of a failure from test/verification output."""
    failure_type: str  # syntax_error, test_failure, import_error, timeout, missing_file, unknown
    file_path: str = ""
    line_number: int = 0
    error_message: str = ""
    suggestion: str = ""
    recoverable: bool = True


def diagnose_failure(stderr: str, stdout: str = "") -> FailureDiagnosis:
    """Parse error output to diagnose the type and location of a failure."""
    combined = f"{stderr}\n{stdout}"

    # Python syntax errors
    m = re.search(
        r'(?:SyntaxError|IndentationError):\s*(.+?)\s*\n\s*File "(.+?)", line (\d+)',
        combined,
    )
    if m:
        return FailureDiagnosis(
            failure_type="syntax_error",
            error_message=m.group(1),
            file_path=m.group(2),
            line_number=int(m.group(3)),
            suggestion=f"Fix syntax error at {m.group(2)}:{m.group(3)}: {m.group(1)}",
        )

    # Python import errors
    m = re.search(r'ImportError:\s*(?:cannot import name .+ from |.+)', combined)
    if m:
        return FailureDiagnosis(
            failure_type="import_error",
            error_message=m.group(0),
            suggestion="Check import paths and module availability",
        )

    m = re.search(r'ModuleNotFoundError:\s*No module named [\'"](\S+?)[\'"]', combined)
    if m:
        return FailureDiagnosis(
            failure_type="import_error",
            error_message=m.group(0),
            suggestion=f"Install or fix import of module: {m.group(1)}",
        )

    # Python tracebacks - extract the last frame
    frames = re.findall(r'File "(.+?)", line (\d+), in (\S+)', combined)
    if frames:
        last_file, last_line, last_func = frames[-1]
        return FailureDiagnosis(
            failure_type="test_failure",
            file_path=last_file,
            line_number=int(last_line),
            error_message=f"Error in {last_func} at {last_file}:{last_line}",
            suggestion=f"Investigate error in {last_func}() at {last_file}:{last_line}",
        )

    # Assertion errors
    if "AssertionError" in combined or "AssertionError" in combined:
        m = re.search(r'AssertionError:\s*(.+)', combined)
        msg = m.group(1) if m else "Assertion failed"
        return FailureDiagnosis(
            failure_type="test_failure",
            error_message=msg,
            suggestion="Check the assertion and adjust the code or test expectations",
        )

    # Timeout
    if "timed out" in combined.lower() or "timeout" in combined.lower():
        return FailureDiagnosis(
            failure_type="timeout",
            error_message="Command timed out",
            suggestion="The command may be hanging; try a simpler test or add a timeout",
        )

    # Missing file
    m = re.search(r'(?:FileNotFoundError|No such file or directory|not found):\s*(.+)', combined)
    if m:
        return FailureDiagnosis(
            failure_type="missing_file",
            error_message=m.group(0),
            suggestion=f"Create or fix path to: {m.group(1)}",
        )

    # Generic error
    m = re.search(r'(\w+Error):\s*(.+)', combined)
    if m:
        return FailureDiagnosis(
            failure_type="unknown",
            error_message=f"{m.group(1)}: {m.group(2)}",
            suggestion="Diagnose and fix the error based on the message",
        )

    return FailureDiagnosis(
        failure_type="unknown",
        error_message=combined[:500],
        suggestion="Review the error output for clues",
    )


async def create_checkpoint(
    ctx: RuntimeContext, tools: ToolRegistry, name: str
) -> bool:
    """Create a checkpoint of the current workspace state."""
    ok, res = await try_tool(ctx, tools, "checkpoint", {
        "action": "create", "name": name, "note": f"auto-checkpoint before edit",
    })
    return ok and res is not None and res.ok


async def rollback_to_checkpoint(
    ctx: RuntimeContext, tools: ToolRegistry, name: str
) -> bool:
    """Roll back the workspace to a named checkpoint."""
    ok, res = await try_tool(ctx, tools, "checkpoint", {
        "action": "rollback", "name": name,
    })
    return ok and res is not None and res.ok


def build_retry_prompt(diagnosis: FailureDiagnosis, iteration: int) -> str:
    """Build a prompt for the LLM to retry with a different approach."""
    strategy_hints = {
        0: "Your first attempt had an error. Read the error carefully and try again.",
        1: "The previous approach didn't work. Try a DIFFERENT strategy. Consider reading more of the surrounding code before making changes.",
        2: "Two attempts have failed. Be more conservative: make smaller, more targeted edits. Double-check exact string matches for edit_file.",
        3: "Multiple attempts have failed. Consider rewriting the entire file or function instead of making incremental edits.",
    }

    hint = strategy_hints.get(iteration, strategy_hints[3])

    parts = [
        f"## Attempt {iteration + 1} Failed\n",
        f"**Error type:** {diagnosis.failure_type}",
    ]

    if diagnosis.file_path:
        parts.append(f"**File:** {diagnosis.file_path}:{diagnosis.line_number}")

    if diagnosis.error_message:
        parts.append(f"**Error:** {diagnosis.error_message}")

    parts.append(f"\n**Strategy:** {hint}")
    parts.append(f"\n**Suggestion:** {diagnosis.suggestion}")
    parts.append("\nPlease try again with a corrected approach. Respond with your next action in JSON format.")

    return "\n".join(parts)


def is_noop_edit(old_content: str, new_content: str) -> bool:
    """Check if an edit actually changed anything."""
    return old_content == new_content


# Track recent edits to detect loops
@dataclass
class EditTracker:
    """Track recent edits to detect repeated no-op or oscillating edits."""
    recent_edits: list[dict[str, Any]] = field(default_factory=list)
    max_history: int = 10

    def record(self, path: str, old_string: str, new_string: str, success: bool) -> None:
        self.recent_edits.append({
            "path": path,
            "old_hash": hash(old_string),
            "new_hash": hash(new_string),
            "success": success,
        })
        if len(self.recent_edits) > self.max_history:
            self.recent_edits.pop(0)

    def is_stuck(self) -> bool:
        """Detect if we're making the same edits repeatedly."""
        if len(self.recent_edits) < 4:
            return False
        recent = self.recent_edits[-4:]
        # Check if the last 4 edits are all failures
        if all(not e["success"] for e in recent):
            return True
        # Check if we're oscillating between two states
        hashes = [(e["old_hash"], e["new_hash"]) for e in recent]
        if len(set(hashes)) <= 2:
            return True
        return False
