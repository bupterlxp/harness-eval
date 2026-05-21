"""
Context Manager (C) - Manages LLM context window with summarization.

Implements:
- Context window tracking and budget management
- Automatic summarization of long content
- Code snippet extraction (no full file dumps)
- Conversation history compression
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class ContextRole(Enum):
    """Roles in the conversation context."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ContextMessage:
    """A single message in the context."""
    role: ContextRole
    content: str
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = estimate_tokens(self.content)


def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token average)."""
    return len(text) // 4 + 1


def summarize_code(code: str, max_lines: int = 50) -> str:
    """
    Summarize code by extracting structure without full content.

    Extracts:
    - Imports
    - Class/function signatures
    - Key comments
    """
    lines = code.split("\n")
    if len(lines) <= max_lines:
        return code

    result_lines = []
    in_class = False
    in_function = False
    indent_stack: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if stripped.startswith(("import ", "from ")):
            result_lines.append(line)
        elif stripped.startswith("class "):
            result_lines.append("")
            result_lines.append(line)
            in_class = True
            indent_stack = [indent]
        elif stripped.startswith("def "):
            result_lines.append(line)
            if stripped.endswith(":"):
                docstring_idx = i + 1
                if docstring_idx < len(lines):
                    next_line = lines[docstring_idx].strip()
                    if next_line.startswith(('"""', "'''")):
                        result_lines.append(lines[docstring_idx])
                        if not (next_line.endswith('"""') or next_line.endswith("'''")):
                            for j in range(docstring_idx + 1, min(docstring_idx + 5, len(lines))):
                                result_lines.append(lines[j])
                                if lines[j].strip().endswith(('"""', "'''")):
                                    break
            in_function = True
        elif stripped.startswith("@"):
            result_lines.append(line)
        elif stripped.startswith("#") and "TODO" in stripped.upper():
            result_lines.append(line)

    if len(result_lines) > max_lines:
        result_lines = result_lines[:max_lines]
        result_lines.append("# ... (truncated)")

    return "\n".join(result_lines)


def summarize_text(text: str, max_chars: int = 2000) -> str:
    """Summarize plain text by extracting key sentences."""
    if len(text) <= max_chars:
        return text

    paragraphs = text.split("\n\n")
    result = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > max_chars:
            remaining = max_chars - current_len
            if remaining > 100:
                result.append(para[:remaining] + "...")
            break
        result.append(para)
        current_len += len(para) + 2

    return "\n\n".join(result)


def extract_code_region(
    content: str,
    start_line: int,
    end_line: int,
    context_lines: int = 5
) -> str:
    """Extract a code region with surrounding context."""
    lines = content.split("\n")
    total_lines = len(lines)

    actual_start = max(0, start_line - context_lines - 1)
    actual_end = min(total_lines, end_line + context_lines)

    result_lines = []
    for i in range(actual_start, actual_end):
        line_num = i + 1
        prefix = ">>> " if start_line <= line_num <= end_line else "    "
        result_lines.append(f"{prefix}{line_num:4d}: {lines[i]}")

    return "\n".join(result_lines)


class ContextManager:
    """
    Manages LLM context window with automatic summarization.

    Never dumps full files into context. Uses:
    - Code structure extraction
    - Relevant snippet extraction
    - Conversation compression
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        reserve_tokens: int = 2000,
        system_prompt: str = ""
    ):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.available_tokens = max_tokens - reserve_tokens

        self.system_message: ContextMessage | None = None
        if system_prompt:
            self.system_message = ContextMessage(
                role=ContextRole.SYSTEM,
                content=system_prompt
            )

        self.messages: list[ContextMessage] = []
        self.code_cache: dict[str, str] = {}

    def _current_token_count(self) -> int:
        """Calculate current token usage."""
        total = 0
        if self.system_message:
            total += self.system_message.token_estimate
        for msg in self.messages:
            total += msg.token_estimate
        return total

    def _compress_messages(self, target_reduction: int) -> int:
        """Compress older messages to free up tokens."""
        if len(self.messages) < 3:
            return 0

        freed = 0
        compress_candidates = self.messages[:-2]

        for i, msg in enumerate(compress_candidates):
            if freed >= target_reduction:
                break

            if msg.metadata.get("compressed"):
                continue

            original_tokens = msg.token_estimate

            if msg.role == ContextRole.TOOL:
                new_content = summarize_text(msg.content, max_chars=500)
            elif msg.role == ContextRole.ASSISTANT:
                new_content = summarize_text(msg.content, max_chars=1000)
            else:
                new_content = summarize_text(msg.content, max_chars=800)

            new_tokens = estimate_tokens(new_content)
            if new_tokens < original_tokens:
                self.messages[i] = ContextMessage(
                    role=msg.role,
                    content=new_content,
                    token_estimate=new_tokens,
                    metadata={**msg.metadata, "compressed": True}
                )
                freed += original_tokens - new_tokens

        return freed

    def add_message(
        self,
        role: ContextRole,
        content: str,
        metadata: dict[str, Any] | None = None
    ) -> ContextMessage:
        """Add a message to context, compressing if needed."""
        msg = ContextMessage(
            role=role,
            content=content,
            metadata=metadata or {}
        )

        needed = msg.token_estimate
        current = self._current_token_count()

        if current + needed > self.available_tokens:
            overage = (current + needed) - self.available_tokens
            self._compress_messages(overage + 500)

        current = self._current_token_count()
        if current + needed > self.available_tokens:
            while self.messages and current + needed > self.available_tokens:
                removed = self.messages.pop(0)
                current -= removed.token_estimate

        self.messages.append(msg)
        return msg

    def add_code_context(
        self,
        file_path: str,
        content: str,
        region: tuple[int, int] | None = None,
        summarize: bool = True
    ) -> str:
        """
        Add code to context without dumping full files.

        Args:
            file_path: Path for reference
            content: Full file content
            region: Optional (start_line, end_line) to extract
            summarize: Whether to summarize or extract region

        Returns:
            The processed content that was added
        """
        if region:
            processed = extract_code_region(content, region[0], region[1])
            header = f"# Code from {file_path} (lines {region[0]}-{region[1]}):\n"
        elif summarize:
            processed = summarize_code(content)
            header = f"# Structure of {file_path}:\n"
        else:
            if len(content) > 3000:
                processed = summarize_code(content)
                header = f"# Structure of {file_path} (summarized, original too large):\n"
            else:
                processed = content
                header = f"# Content of {file_path}:\n"

        self.code_cache[file_path] = content
        return header + processed

    def add_tool_result(
        self,
        tool_name: str,
        result: str,
        max_chars: int = 2000
    ) -> ContextMessage:
        """Add a tool result with automatic truncation."""
        if len(result) > max_chars:
            result = summarize_text(result, max_chars)

        content = f"[{tool_name}] {result}"
        return self.add_message(
            ContextRole.TOOL,
            content,
            metadata={"tool": tool_name}
        )

    def get_messages_for_llm(self) -> list[dict[str, str]]:
        """Get messages formatted for LLM API call."""
        result = []

        if self.system_message:
            result.append({
                "role": "system",
                "content": self.system_message.content
            })

        for msg in self.messages:
            role = msg.role.value
            if role == "tool":
                role = "user"
            result.append({
                "role": role,
                "content": msg.content
            })

        return result

    def get_token_usage(self) -> dict[str, int]:
        """Get current token usage statistics."""
        current = self._current_token_count()
        return {
            "used": current,
            "available": self.available_tokens,
            "max": self.max_tokens,
            "message_count": len(self.messages)
        }

    def clear(self) -> None:
        """Clear all messages but keep system prompt."""
        self.messages.clear()
        self.code_cache.clear()
