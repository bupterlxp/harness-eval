"""Context manager: build and compress the LLM context window.

Manages the conversation history for the LLM, enforces a token budget,
and compresses context when it grows too large. This prevents prompt
overflow and keeps the LLM focused on the most relevant information.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import try_tool


# Approximate token-to-character ratio (conservative)
CHARS_PER_TOKEN = 3.5
DEFAULT_MAX_CONTEXT_CHARS = 80_000  # ~23k tokens


@dataclass
class ContextWindow:
    """Manages the LLM conversation history with size tracking."""
    messages: list[dict[str, Any]] = field(default_factory=list)
    total_chars: int = 0
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS
    system_prompt: str = ""

    def add_system(self, content: str) -> None:
        self.system_prompt = content
        self.total_chars += len(content)

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self.total_chars += len(content)

    def add_assistant(self, content: str, tool_calls: Optional[list[dict]] = None) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        self.total_chars += len(content)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })
        self.total_chars += len(content)

    def needs_compression(self) -> bool:
        return self.total_chars > self.max_chars

    def compress(self) -> None:
        """Compress the context by summarizing older messages."""
        if len(self.messages) <= 4:
            return

        # Keep the first user message and the last 4 messages
        # Summarize everything in between
        kept_first = 1
        kept_last = 4
        if len(self.messages) <= kept_first + kept_last:
            return

        older = self.messages[:kept_first]
        middle = self.messages[kept_first:-kept_last]
        recent = self.messages[-kept_last:]

        # Build a summary of the middle messages
        summary_parts: list[str] = []
        for msg in middle:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 500:
                content = content[:500] + "...[truncated]"
            summary_parts.append(f"[{role}]: {content}")

        summary = (
            "Previous conversation summary:\n"
            + "\n".join(summary_parts)
            + "\n\n(Older messages were compressed to save context space.)"
        )

        self.messages = older + [
            {"role": "user", "content": summary}
        ] + recent

        # Recalculate total chars
        self.total_chars = len(self.system_prompt)
        for msg in self.messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                self.total_chars += len(content)

    def build_messages(self) -> list[dict[str, Any]]:
        """Build the final message list for the LLM API call."""
        result: list[dict[str, Any]] = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        result.extend(self.messages)

        # Ensure the last message is from the user
        if result and result[-1].get("role") != "user":
            result.append({"role": "user", "content": "Continue with the next step."})

        # Merge adjacent same-role messages
        merged: list[dict[str, Any]] = []
        for msg in result:
            if merged and merged[-1].get("role") == msg.get("role") and "tool_calls" not in merged[-1]:
                existing = merged[-1].get("content", "")
                new_content = msg.get("content", "")
                merged[-1]["content"] = f"{existing}\n\n{new_content}"
            else:
                merged.append(dict(msg))

        return merged


def build_system_prompt(plan: Any) -> str:
    """Build the system prompt for the code agent LLM."""
    return (
        "You are an expert software engineer. Your job is to complete the "
        "task described below by modifying files in the repository.\n\n"
        "RULES:\n"
        "1. Use the provided tools to read, search, edit, and write files.\n"
        "2. Before making edits, understand the codebase by reading relevant files.\n"
        "3. Make precise, minimal edits that solve the task.\n"
        "4. After editing, verify your changes by running tests or checking syntax.\n"
        "5. If your first attempt fails, diagnose the error and try a different approach.\n"
        "6. When done, use the 'finish' action to signal completion.\n"
        "7. Always provide a brief explanation of what you're doing and why.\n\n"
        "AVAILABLE ACTIONS (respond with JSON):\n"
        '- {"action": "read_file", "path": "<path>"}\n'
        '- {"action": "search", "pattern": "<regex>", "path": "<dir>", "glob": "<pattern>"}\n'
        '- {"action": "list_files", "path": "<dir>", "depth": <n>}\n'
        '- {"action": "edit_file", "path": "<path>", "old_string": "<exact text>", "new_string": "<replacement>"}\n'
        '- {"action": "write_file", "path": "<path>", "content": "<full content>"}\n'
        '- {"action": "run_command", "command": "<shell command>"}\n'
        '- {"action": "finish", "status": "success|partial|failed", "message": "<summary>"}\n\n'
        "IMPORTANT:\n"
        "- For edit_file, old_string must be an EXACT match of the text to replace.\n"
        "- For write_file, provide the COMPLETE file content.\n"
        "- For run_command, the command runs in the repository root.\n"
        "- Respond with ONLY the JSON action, no other text.\n"
    )


def build_initial_user_message(plan: Any) -> str:
    """Build the initial user message with the task and repo context."""
    parts: list[str] = []

    parts.append(f"## Task\n\n{plan.prompt}\n")

    if plan.target_files:
        parts.append(f"## Target Files\n\n{', '.join(plan.target_files)}\n")

    if plan.test_commands:
        parts.append("## Test Commands\n\n" + "\n".join(f"- `{cmd}`" for cmd in plan.test_commands) + "\n")

    if plan.constraints:
        parts.append("## Constraints\n\n" + "\n".join(f"- {c}" for c in plan.constraints) + "\n")

    if plan.repo_language:
        parts.append(f"## Repository Info\n\nLanguage: {plan.repo_language}")
        if plan.repo_framework:
            parts.append(f", Framework: {plan.repo_framework}")
        parts.append("\n")

    parts.append(
        "\n## Instructions\n\n"
        "Start by reading the relevant files to understand the codebase, "
        "then make the necessary changes. Use the JSON action format.\n"
    )

    return "\n".join(parts)


def format_tool_result(tool_name: str, result: ToolResult) -> str:
    """Format a tool result for inclusion in the LLM context."""
    if not result.ok:
        error = result.error or {}
        if isinstance(error, dict):
            msg = error.get("message", str(error))
        else:
            msg = str(error)
        return f"[{tool_name} ERROR] {msg}"

    data = result.data
    if not isinstance(data, dict):
        return str(data)[:5000]

    # Format based on tool type
    if tool_name == "file_read":
        content = data.get("content", "")
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]"
        return content

    if tool_name in ("grep", "search"):
        matches = data.get("matches", [])
        lines: list[str] = []
        for m in matches[:100]:
            if isinstance(m, dict):
                lines.append(f"{m.get('file', '')}:{m.get('line', '')}:{m.get('text', '')}")
            else:
                lines.append(str(m))
        text = "\n".join(lines)
        count = data.get("count", len(matches))
        if count > 100:
            text += f"\n...({count - 100} more matches)"
        return text

    if tool_name == "bash":
        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")
        exit_code = data.get("exit_code", -1)
        parts: list[str] = []
        if stdout:
            if len(stdout) > 5000:
                stdout = stdout[:5000] + "\n...[truncated]"
            parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            if len(stderr) > 3000:
                stderr = stderr[:3000] + "\n...[truncated]"
            parts.append(f"STDERR:\n{stderr}")
        parts.append(f"Exit code: {exit_code}")
        return "\n".join(parts)

    if tool_name in ("file_edit", "file_write"):
        return str(data)

    if tool_name == "tree":
        entries = data.get("entries", [])
        tree_text = data.get("tree", "")
        if tree_text:
            if len(tree_text) > 5000:
                tree_text = tree_text[:5000] + "\n...[truncated]"
            return tree_text
        return "\n".join(str(e) for e in entries[:200])

    if tool_name == "git_status":
        changed = data.get("changed", [])
        lines = [f"Branch: {data.get('branch', 'unknown')}"]
        if changed:
            for c in changed[:50]:
                lines.append(f"  {c.get('status', '?')} {c.get('path', '')}")
        else:
            lines.append("  (clean)")
        return "\n".join(lines)

    if tool_name == "git_diff":
        return (
            f"Files changed: {data.get('files_changed', 0)}, "
            f"+{data.get('insertions', 0)}/-{data.get('deletions', 0)}"
        )

    # Generic format
    text = str(data)
    if len(text) > 5000:
        text = text[:5000] + "...[truncated]"
    return text
