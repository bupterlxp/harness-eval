"""
Context Manager (C) - Manages LLM context window with summarization.

Responsibilities:
- Manage context window size
- Implement summarization/compression strategies
- Never include entire file contents in prompts
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextEntry:
    """A single entry in the context."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    token_estimate: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = self._estimate_tokens(self.content)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation (4 chars per token average)."""
        return len(text) // 4 + 1


@dataclass
class FileContext:
    """Summarized context for a file."""
    path: str
    summary: str
    relevant_lines: list[tuple[int, int, str]]  # (start, end, content_snippet)
    total_lines: int
    last_accessed: float = 0.0


class ContextManager:
    """Manages context for LLM interactions with compression strategies."""

    MAX_TOKENS = 16000  # Leave room for response
    MAX_FILE_PREVIEW_LINES = 50
    MAX_SEARCH_RESULTS = 20
    SUMMARY_TARGET_TOKENS = 500

    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens or self.MAX_TOKENS
        self._messages: list[ContextEntry] = []
        self._file_cache: dict[str, FileContext] = {}
        self._system_prompt: str = ""
        self._total_tokens: int = 0

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self._system_prompt = prompt

    def add_message(self, role: str, content: str, **metadata: Any) -> None:
        """Add a message to context, compressing if needed."""
        entry = ContextEntry(role=role, content=content, metadata=metadata)
        self._messages.append(entry)
        self._total_tokens += entry.token_estimate
        self._compress_if_needed()

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages formatted for LLM API."""
        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        for entry in self._messages:
            msg = {"role": entry.role, "content": entry.content}
            if entry.metadata.get("tool_call_id"):
                msg["tool_call_id"] = entry.metadata["tool_call_id"]
            if entry.metadata.get("tool_calls"):
                msg["tool_calls"] = entry.metadata["tool_calls"]
            messages.append(msg)

        return messages

    def summarize_file_content(
        self,
        path: str,
        content: str,
        focus_lines: list[int] | None = None,
    ) -> str:
        """Summarize file content instead of including it entirely.

        This is a key requirement: never put entire files in prompts.
        """
        lines = content.splitlines()
        total_lines = len(lines)

        if total_lines <= self.MAX_FILE_PREVIEW_LINES:
            numbered = [f"{i+1}: {line}" for i, line in enumerate(lines)]
            return f"File: {path} ({total_lines} lines)\n" + "\n".join(numbered)

        parts = [f"File: {path} ({total_lines} lines)"]

        # Always show first few lines for context
        parts.append("--- First 10 lines ---")
        for i, line in enumerate(lines[:10], 1):
            parts.append(f"{i}: {line}")

        # Show focused lines if specified
        if focus_lines:
            focus_lines = sorted(set(focus_lines))
            parts.append("\n--- Relevant sections ---")

            # Group consecutive lines
            groups = self._group_consecutive(focus_lines)
            for start, end in groups:
                context_start = max(0, start - 3)
                context_end = min(total_lines, end + 3)

                parts.append(f"\nLines {context_start + 1}-{context_end}:")
                for i in range(context_start, context_end):
                    marker = ">" if i + 1 in focus_lines else " "
                    parts.append(f"{marker}{i+1}: {lines[i]}")

        # Structure summary
        parts.append("\n--- Structure summary ---")
        structure = self._extract_structure(content)
        parts.append(structure)

        return "\n".join(parts)

    def summarize_search_results(self, results: list[dict[str, Any]]) -> str:
        """Summarize search results to fit context limits."""
        if not results:
            return "No results found."

        if len(results) <= self.MAX_SEARCH_RESULTS:
            summary_parts = [f"Found {len(results)} matches:"]
            for r in results:
                summary_parts.append(f"  {r['file']}:{r['line']}: {r['content'][:100]}")
            return "\n".join(summary_parts)

        # Group by file and summarize
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            by_file.setdefault(r["file"], []).append(r)

        summary_parts = [f"Found {len(results)} matches in {len(by_file)} files:"]
        for file_path, file_results in list(by_file.items())[:10]:
            summary_parts.append(f"\n{file_path} ({len(file_results)} matches):")
            for r in file_results[:3]:
                summary_parts.append(f"  Line {r['line']}: {r['content'][:80]}")
            if len(file_results) > 3:
                summary_parts.append(f"  ... and {len(file_results) - 3} more matches")

        if len(by_file) > 10:
            summary_parts.append(f"\n... and {len(by_file) - 10} more files")

        return "\n".join(summary_parts)

    def summarize_command_output(self, stdout: str, stderr: str, returncode: int) -> str:
        """Summarize command output for context."""
        parts = [f"Exit code: {returncode}"]

        if stdout:
            stdout_lines = stdout.splitlines()
            if len(stdout_lines) > 30:
                parts.append(f"stdout ({len(stdout_lines)} lines):")
                parts.extend(f"  {line}" for line in stdout_lines[:10])
                parts.append("  ...")
                parts.extend(f"  {line}" for line in stdout_lines[-10:])
            else:
                parts.append("stdout:")
                parts.extend(f"  {line}" for line in stdout_lines)

        if stderr:
            stderr_lines = stderr.splitlines()
            if len(stderr_lines) > 20:
                parts.append(f"stderr ({len(stderr_lines)} lines):")
                parts.extend(f"  {line}" for line in stderr_lines[:15])
                parts.append("  ...")
            else:
                parts.append("stderr:")
                parts.extend(f"  {line}" for line in stderr_lines)

        return "\n".join(parts)

    def get_context_summary(self) -> str:
        """Get a summary of current context for snapshots."""
        summary_parts = [
            f"Messages: {len(self._messages)}",
            f"Estimated tokens: {self._total_tokens}",
            f"Cached files: {len(self._file_cache)}",
        ]

        if self._messages:
            recent = self._messages[-3:]
            summary_parts.append("Recent context:")
            for msg in recent:
                preview = msg.content[:100].replace("\n", " ")
                summary_parts.append(f"  [{msg.role}]: {preview}...")

        return "\n".join(summary_parts)

    def clear(self) -> None:
        """Clear all context."""
        self._messages.clear()
        self._file_cache.clear()
        self._total_tokens = 0

    def _compress_if_needed(self) -> None:
        """Compress context if over token limit."""
        max_iterations = len(self._messages) + 10
        iterations = 0
        while self._total_tokens > self.max_tokens and len(self._messages) > 2:
            iterations += 1
            if iterations > max_iterations:
                break
            old_count = len(self._messages)
            old_tokens = self._total_tokens
            self._compress_oldest()
            if len(self._messages) == old_count and self._total_tokens >= old_tokens:
                break

    def _compress_oldest(self) -> None:
        """Compress or remove oldest non-critical messages."""
        # Keep system, first user message, and recent messages
        if len(self._messages) <= 4:
            return

        # Find oldest compressible message
        for i, msg in enumerate(self._messages[1:-2]):
            actual_idx = i + 1
            if msg.token_estimate > self.SUMMARY_TARGET_TOKENS:
                # Compress this message
                compressed = self._compress_message(msg)
                old_tokens = msg.token_estimate
                self._messages[actual_idx] = compressed
                self._total_tokens -= old_tokens - compressed.token_estimate
                return

        # If nothing to compress, remove oldest
        removed = self._messages.pop(1)
        self._total_tokens -= removed.token_estimate

    def _compress_message(self, entry: ContextEntry) -> ContextEntry:
        """Compress a single message."""
        content = entry.content

        # For tool results, extract key information
        if entry.role == "tool":
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    # Keep error messages intact
                    if data.get("error"):
                        compressed = f"Error: {data['error']}"
                    elif data.get("output"):
                        output = data["output"]
                        if isinstance(output, str) and len(output) > 500:
                            compressed = f"Output (truncated): {output[:500]}..."
                        else:
                            compressed = f"Output: {json.dumps(output)[:500]}"
                    else:
                        compressed = f"Result: {str(data)[:500]}"
                else:
                    compressed = f"Result: {str(data)[:500]}"
            except json.JSONDecodeError:
                compressed = content[:500] + "..." if len(content) > 500 else content
        else:
            # For other messages, truncate with context
            lines = content.splitlines()
            if len(lines) > 20:
                compressed = "\n".join(lines[:10] + ["[...]"] + lines[-5:])
            else:
                compressed = content[:1000] + "..." if len(content) > 1000 else content

        return ContextEntry(
            role=entry.role,
            content=compressed,
            metadata=entry.metadata,
        )

    @staticmethod
    def _group_consecutive(numbers: list[int], gap: int = 5) -> list[tuple[int, int]]:
        """Group consecutive numbers allowing for gaps."""
        if not numbers:
            return []

        groups = []
        start = numbers[0]
        end = numbers[0]

        for n in numbers[1:]:
            if n <= end + gap:
                end = n
            else:
                groups.append((start, end))
                start = end = n

        groups.append((start, end))
        return groups

    @staticmethod
    def _extract_structure(content: str) -> str:
        """Extract structural summary from Python code."""
        import re

        structure = []

        # Find imports
        imports = re.findall(r"^(?:from\s+\S+\s+)?import\s+.+$", content, re.MULTILINE)
        if imports:
            structure.append(f"Imports: {len(imports)}")

        # Find class definitions
        classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)
        if classes:
            structure.append(f"Classes: {', '.join(classes)}")

        # Find function definitions
        functions = re.findall(r"^(?:async\s+)?def\s+(\w+)", content, re.MULTILINE)
        if functions:
            top_level = [f for f in functions if not f.startswith("_")][:10]
            structure.append(f"Functions: {', '.join(top_level)}")

        return "\n".join(structure) if structure else "No structure detected"
