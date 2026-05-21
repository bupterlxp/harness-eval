"""Context Manager — context management and compression.

Implements token budget tracking, history compression, and LLM-driven summarization
to keep the conversation within the model's context window.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.state import StepRecord


# Approximate token counting: 1 token ~ 4 chars for English text
def _estimate_tokens(text: str) -> int:
    """Estimate token count from character count (rough heuristic)."""
    return len(text) // 4 + 1


@dataclass
class ContextConfig:
    """Configuration for context management."""

    max_token_budget: int = 128000
    warning_threshold: float = 0.75  # Warn at 75% usage
    emergency_threshold: float = 0.90  # Emergency compress at 90%
    preserve_recent_steps: int = 5
    max_observation_chars: int = 10000
    max_observation_lines: int = 200
    overflow_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="harness_overflow_")))


class ContextManager:
    """Manages the context window for LLM interactions.

    Responsibilities:
    - Truncate long tool outputs (save full version to file)
    - Compress old history steps (replace observations with summaries)
    - Track overall token budget
    - Trigger LLM-driven summarization when approaching limits
    - Generate repo-map for global structure awareness
    """

    def __init__(
        self,
        model_name: str = "gpt-4o",
        max_token_budget: int = 128000,
        preserve_recent_steps: int = 5,
        overflow_dir: Path | None = None,
    ) -> None:
        self.config = ContextConfig(
            max_token_budget=max_token_budget,
            preserve_recent_steps=preserve_recent_steps,
        )
        if overflow_dir:
            self.config.overflow_dir = overflow_dir
            self.config.overflow_dir.mkdir(parents=True, exist_ok=True)

        self.model_name = model_name
        self._summary_cache: str = ""
        self._repo_map: str = ""

    def truncate_output(self, output: str, step_number: int) -> str:
        """Truncate tool output if it exceeds thresholds.

        If truncated, saves full output to a file and returns truncated version
        with a reference to the full file.
        """
        lines = output.split("\n")
        char_over = len(output) > self.config.max_observation_chars
        line_over = len(lines) > self.config.max_observation_lines

        if not char_over and not line_over:
            return output

        # Save full output to overflow file
        overflow_path = self.config.overflow_dir / f"step_{step_number}_full_output.txt"
        with open(overflow_path, "w") as f:
            f.write(output)

        # Truncate
        if line_over:
            truncated_lines = lines[: self.config.max_observation_lines]
            truncated = "\n".join(truncated_lines)
        else:
            truncated = output[: self.config.max_observation_chars]

        truncated += f"\n\n[OUTPUT TRUNCATED — full output saved to: {overflow_path}]"
        return truncated

    def compress_history(self, history: list[StepRecord]) -> list[dict[str, Any]]:
        """Compress history for inclusion in LLM messages.

        Recent steps are preserved in full.
        Older steps have their observations replaced with ellipsis markers.
        """
        if not history:
            return []

        compressed: list[dict[str, Any]] = []
        preserve_from = max(0, len(history) - self.config.preserve_recent_steps)

        for i, step in enumerate(history):
            if i < preserve_from:
                # Compress old steps
                compressed.append({
                    "step": step.step_number,
                    "action": step.action,
                    "action_input_summary": _summarize_input(step.action_input),
                    "observation": "[...compressed...]",
                    "thought_summary": step.thought[:100] + "..." if len(step.thought) > 100 else step.thought,
                })
            else:
                # Full recent steps
                compressed.append({
                    "step": step.step_number,
                    "thought": step.thought,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                })

        return compressed

    def build_messages(
        self,
        system_prompt: str,
        task_prompt: str,
        history: list[StepRecord],
        extra_context: str = "",
        budget_warning: str = "",
        doom_loop_warning: str = "",
    ) -> list[dict[str, Any]]:
        """Build the full message list for the LLM, respecting token budget.

        Structure:
        - System message (instructions + repo map)
        - User message (task + context summary)
        - Alternating assistant/user messages for history
        """
        messages: list[dict[str, Any]] = []

        # System message
        sys_content = system_prompt
        if self._repo_map:
            sys_content += f"\n\n## Repository Structure\n{self._repo_map}"

        messages.append({"role": "system", "content": sys_content})

        # Initial user message with task
        user_content = f"## Task\n{task_prompt}"
        if self._summary_cache:
            user_content += f"\n\n## Previous Progress Summary\n{self._summary_cache}"
        if extra_context:
            user_content += f"\n\n## Additional Context\n{extra_context}"
        if budget_warning:
            user_content += f"\n\n## WARNING\n{budget_warning}"
        if doom_loop_warning:
            user_content += f"\n\n## CRITICAL: LOOP DETECTED\n{doom_loop_warning}\nYou MUST try a different approach."

        messages.append({"role": "user", "content": user_content})

        # History as conversation turns
        compressed = self.compress_history(history)
        for entry in compressed:
            if "thought" in entry:
                # Full entry — assistant turn
                assistant_msg = f"Thought: {entry['thought']}\n\nAction: {entry['action']}\nAction Input: {json.dumps(entry['action_input'])}"
                messages.append({"role": "assistant", "content": assistant_msg})
                # Observation as user turn
                messages.append({"role": "user", "content": f"Observation: {entry['observation']}"})
            else:
                # Compressed entry — brief assistant + user pair
                assistant_msg = f"Thought: {entry.get('thought_summary', '...')}\n\nAction: {entry['action']}\nAction Input: {entry['action_input_summary']}"
                messages.append({"role": "assistant", "content": assistant_msg})
                messages.append({"role": "user", "content": "Observation: [...compressed...]"})

        # Check token budget
        total_tokens = self._estimate_messages_tokens(messages)
        if total_tokens > self.config.max_token_budget * self.config.emergency_threshold:
            messages = self._emergency_compress(messages, history)

        return messages

    def estimate_usage(self, messages: list[dict[str, Any]]) -> float:
        """Return estimated fraction of token budget used (0.0 to 1.0+)."""
        tokens = self._estimate_messages_tokens(messages)
        return tokens / self.config.max_token_budget

    def is_over_budget(self, messages: list[dict[str, Any]]) -> bool:
        """Check if messages exceed the token budget."""
        return self.estimate_usage(messages) > 1.0

    def needs_warning(self, messages: list[dict[str, Any]]) -> bool:
        """Check if approaching budget threshold."""
        return self.estimate_usage(messages) > self.config.warning_threshold

    def set_summary(self, summary: str) -> None:
        """Set the cached summary of previous progress."""
        self._summary_cache = summary

    def set_repo_map(self, repo_map: str) -> None:
        """Set the repository structure map."""
        self._repo_map = repo_map

    def generate_repo_map(self, workspace: Path, max_depth: int = 3) -> str:
        """Generate a simple repo map showing file structure."""
        lines: list[str] = []
        self._walk_dir(workspace, "", max_depth, lines, workspace)
        repo_map = "\n".join(lines[:150])
        if len(lines) > 150:
            repo_map += f"\n... ({len(lines) - 150} more entries)"
        self._repo_map = repo_map
        return repo_map

    def create_emergency_summary(self, history: list[StepRecord]) -> str:
        """Create a concise summary from history when context is critically full.

        This is a fallback non-LLM summary (extractive).
        """
        if not history:
            return ""

        parts = []
        parts.append(f"Completed {len(history)} steps so far.")

        # Summarize actions taken
        action_counts: dict[str, int] = {}
        for step in history:
            action_counts[step.action] = action_counts.get(step.action, 0) + 1
        parts.append(f"Actions used: {dict(action_counts)}")

        # Key observations from recent steps
        recent = history[-3:]
        for step in recent:
            obs_preview = step.observation[:150].replace("\n", " ")
            parts.append(f"Step {step.step_number} ({step.action}): {obs_preview}")

        summary = "\n".join(parts)
        self._summary_cache = summary
        return summary

    def _estimate_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate total tokens in a message list."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += _estimate_tokens(content) + 4  # overhead per message
        return total

    def _emergency_compress(
        self, messages: list[dict[str, Any]], history: list[StepRecord]
    ) -> list[dict[str, Any]]:
        """Emergency compression: keep only system + task + summary + recent steps."""
        # Create extractive summary
        summary = self.create_emergency_summary(history)

        # Rebuild with minimal context
        new_messages = []
        # Keep system message but trim repo map
        if messages:
            sys_msg = messages[0]["content"]
            # Trim repo map if present
            if "## Repository Structure" in sys_msg:
                sys_msg = sys_msg[: sys_msg.index("## Repository Structure")]
            new_messages.append({"role": "system", "content": sys_msg})

        # Compact user message
        task_msg = messages[1]["content"] if len(messages) > 1 else ""
        new_messages.append({
            "role": "user",
            "content": f"{task_msg}\n\n## Emergency Context (history compressed)\n{summary}",
        })

        # Only include most recent steps
        recent = history[-self.config.preserve_recent_steps:]
        for step in recent:
            assistant_msg = f"Thought: {step.thought}\n\nAction: {step.action}\nAction Input: {json.dumps(step.action_input)}"
            new_messages.append({"role": "assistant", "content": assistant_msg})
            obs = step.observation[:2000]
            new_messages.append({"role": "user", "content": f"Observation: {obs}"})

        return new_messages

    def _walk_dir(self, path: Path, prefix: str, depth: int, lines: list[str], root: Path) -> None:
        """Walk directory tree for repo map."""
        if depth < 0:
            return
        skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".eggs", "dist", "build"}
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name in skip or entry.name.startswith("."):
                continue
            rel = entry.relative_to(root)
            if entry.is_dir():
                lines.append(f"{prefix}{rel}/")
                self._walk_dir(entry, prefix + "  ", depth - 1, lines, root)
            else:
                lines.append(f"{prefix}{rel}")


def _summarize_input(action_input: dict[str, Any]) -> str:
    """Create a brief summary of action input for compressed history."""
    parts = []
    for k, v in action_input.items():
        val_str = str(v)
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        parts.append(f"{k}={val_str}")
    return ", ".join(parts) if parts else "{}"
