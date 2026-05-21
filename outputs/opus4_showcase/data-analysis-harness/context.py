"""Context Manager — context management and compression with token budget.

Implements a four-layer compression strategy:
  L1: Truncate old observations (keep only summaries)
  L2: Discard old complete rounds
  L3: LLM-generated summary replacement for history
  L4: Emergency trimming (keep only system + last N messages)

Always injects a task progress summary into context so the agent
never loses track of what has been accomplished.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI


@dataclass
class ContextConfig:
    """Configuration for context management."""

    token_budget: int = 120000
    # Thresholds for triggering compression levels (as fraction of budget)
    l1_threshold: float = 0.70  # Truncate old observations at 70%
    l2_threshold: float = 0.80  # Discard old rounds at 80%
    l3_threshold: float = 0.90  # LLM summarize at 90%
    l4_threshold: float = 0.95  # Emergency trim at 95%
    # Observation truncation settings
    max_observation_tokens: int = 1500
    # Minimum rounds to keep even under compression
    min_rounds_to_keep: int = 3
    # Progress summary max tokens
    progress_summary_max_tokens: int = 800


@dataclass
class Artifact:
    """Registered artifact with compressed summary."""

    name: str
    artifact_type: str  # "dataframe" | "chart" | "file"
    summary: str  # Compressed description
    path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """Manages the LLM context window with token budget and compression.

    The context is organized as:
      1. System message (always present)
      2. Task progress summary (always injected)
      3. Artifact registry summary (compressed)
      4. Conversation history (subject to compression)
    """

    def __init__(self, config: ContextConfig | None = None) -> None:
        self.config = config or ContextConfig()
        self._messages: list[dict[str, Any]] = []
        self._system_message: dict[str, Any] | None = None
        self._progress_summary: str = ""
        self._artifacts: list[Artifact] = []
        self._findings: list[str] = []
        self._compression_level: int = 0
        self._total_tokens_used: int = 0

    @property
    def compression_level(self) -> int:
        return self._compression_level

    def set_system_message(self, content: str) -> None:
        """Set the system message (always at position 0)."""
        self._system_message = {"role": "system", "content": content}

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        self._messages.append({"role": role, "content": content})

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message."""
        self.add_message("assistant", content)

    def add_user_message(self, content: str) -> None:
        """Add a user/observation message."""
        self.add_message("user", content)

    def update_progress(self, summary: str) -> None:
        """Update the task progress summary."""
        self._progress_summary = summary

    def add_finding(self, finding: str) -> None:
        """Add a key finding to long-term memory."""
        self._findings.append(finding)
        # Keep findings list bounded
        if len(self._findings) > 20:
            self._findings = self._findings[-20:]

    def register_artifact(self, artifact: Artifact) -> None:
        """Register an artifact with its compressed summary."""
        self._artifacts.append(artifact)

    def get_messages_for_llm(self) -> list[dict[str, Any]]:
        """Build the full message list for the LLM call.

        Applies compression as needed to stay within token budget.
        Returns messages including system, progress summary, and history.
        """
        # Estimate current token usage
        estimated_tokens = self._estimate_total_tokens()

        # Apply compression levels as needed
        if estimated_tokens > self.config.token_budget * self.config.l1_threshold:
            self._apply_l1_compression()
            estimated_tokens = self._estimate_total_tokens()

        if estimated_tokens > self.config.token_budget * self.config.l2_threshold:
            self._apply_l2_compression()
            estimated_tokens = self._estimate_total_tokens()

        if estimated_tokens > self.config.token_budget * self.config.l3_threshold:
            self._apply_l3_compression()
            estimated_tokens = self._estimate_total_tokens()

        if estimated_tokens > self.config.token_budget * self.config.l4_threshold:
            self._apply_l4_compression()

        # Build final message list
        messages: list[dict[str, Any]] = []

        # System message
        if self._system_message:
            messages.append(self._system_message)

        # Inject progress summary as a system-like context
        progress_content = self._build_progress_injection()
        if progress_content:
            messages.append({"role": "system", "content": progress_content})

        # Conversation history
        messages.extend(self._messages)

        self._total_tokens_used = self._estimate_tokens_for_messages(messages)
        return messages

    def _build_progress_injection(self) -> str:
        """Build the progress/context injection block."""
        parts: list[str] = []

        if self._progress_summary:
            parts.append(f"## Task Progress\n{self._progress_summary}")

        if self._findings:
            findings_text = "\n".join(f"- {f}" for f in self._findings[-10:])
            parts.append(f"## Key Findings\n{findings_text}")

        if self._artifacts:
            artifact_lines = []
            for a in self._artifacts[-15:]:  # Keep last 15 artifacts
                artifact_lines.append(f"- [{a.artifact_type}] {a.name}: {a.summary}")
            parts.append(f"## Artifacts\n" + "\n".join(artifact_lines))

        return "\n\n".join(parts) if parts else ""

    def _apply_l1_compression(self) -> None:
        """Level 1: Truncate old observations to summaries."""
        self._compression_level = max(self._compression_level, 1)
        max_obs_chars = self.config.max_observation_tokens * 4  # rough char estimate

        # Keep last 3 rounds intact, compress older ones
        keep_recent = self.config.min_rounds_to_keep * 2  # 2 messages per round (assistant + user)

        for i in range(len(self._messages) - keep_recent):
            msg = self._messages[i]
            if msg["role"] == "user" and len(msg["content"]) > max_obs_chars:
                # Truncate observation
                content = msg["content"]
                truncated = content[:max_obs_chars]
                # Try to find a natural break point
                last_newline = truncated.rfind("\n")
                if last_newline > max_obs_chars // 2:
                    truncated = truncated[:last_newline]
                self._messages[i] = {
                    "role": "user",
                    "content": truncated + "\n[... observation truncated for context management]",
                }

    def _apply_l2_compression(self) -> None:
        """Level 2: Discard old complete rounds, keeping summaries."""
        self._compression_level = max(self._compression_level, 2)

        keep_recent = self.config.min_rounds_to_keep * 2
        if len(self._messages) <= keep_recent:
            return

        # Keep only the most recent rounds
        discard_count = len(self._messages) - keep_recent
        # Ensure we discard in pairs (assistant + user)
        discard_count = (discard_count // 2) * 2

        if discard_count > 0:
            # Create a summary of discarded rounds
            discarded = self._messages[:discard_count]
            summary_lines = []
            for i in range(0, len(discarded), 2):
                if i < len(discarded):
                    msg = discarded[i]
                    # Extract first line as summary
                    first_line = msg["content"].split("\n")[0][:150]
                    summary_lines.append(f"- Step: {first_line}")

            summary = f"[Previous {discard_count // 2} rounds compressed]\n" + "\n".join(summary_lines[:10])

            self._messages = [{"role": "user", "content": summary}] + self._messages[discard_count:]

    def _apply_l3_compression(self) -> None:
        """Level 3: LLM-generated summary replacement.

        Uses a fast LLM call to summarize the conversation history.
        Falls back to simple truncation if LLM call fails.
        """
        self._compression_level = max(self._compression_level, 3)

        # Attempt LLM summarization
        try:
            summary = self._llm_summarize_history()
            if summary:
                # Replace all but the last few messages with the summary
                keep_recent = self.config.min_rounds_to_keep * 2
                self._messages = [
                    {"role": "user", "content": f"[Conversation history summary]\n{summary}"}
                ] + self._messages[-keep_recent:]
                return
        except Exception:
            pass

        # Fallback: aggressive truncation
        keep_recent = self.config.min_rounds_to_keep * 2
        if len(self._messages) > keep_recent:
            self._messages = self._messages[-keep_recent:]

    def _apply_l4_compression(self) -> None:
        """Level 4: Emergency trimming — keep only system + last 2 rounds."""
        self._compression_level = 4
        # Keep only the last 2 full rounds (4 messages)
        self._messages = self._messages[-4:] if len(self._messages) > 4 else self._messages

    def _llm_summarize_history(self) -> str | None:
        """Use LLM to generate a summary of conversation history."""
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("MODEL_NAME", "gpt-4o-mini")

        if not api_key:
            return None

        client = OpenAI(base_url=base_url, api_key=api_key)

        # Build content to summarize
        history_text = ""
        for msg in self._messages[:-4]:  # Summarize all but last 4 messages
            role = msg["role"]
            content = msg["content"][:500]  # Limit each message
            history_text += f"[{role}]: {content}\n\n"

        if not history_text.strip():
            return None

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "Summarize the following data analysis conversation history concisely. Focus on: what data was loaded, what analyses were performed, key findings, and what remains to be done. Keep under 500 words.",
                    },
                    {"role": "user", "content": history_text[:8000]},
                ],
                max_tokens=600,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception:
            return None

    def _estimate_total_tokens(self) -> int:
        """Estimate total tokens for current context state."""
        messages = []
        if self._system_message:
            messages.append(self._system_message)
        progress = self._build_progress_injection()
        if progress:
            messages.append({"role": "system", "content": progress})
        messages.extend(self._messages)
        return self._estimate_tokens_for_messages(messages)

    @staticmethod
    def _estimate_tokens_for_messages(messages: list[dict[str, Any]]) -> int:
        """Estimate token count for a list of messages.

        Uses a rough heuristic: ~4 characters per token for English text.
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total_chars += len(part["text"])
            # Add overhead for message structure
            total_chars += 20
        return total_chars // 4

    def get_token_usage(self) -> dict[str, int]:
        """Get current token usage statistics."""
        return {
            "estimated_tokens": self._total_tokens_used,
            "budget": self.config.token_budget,
            "utilization_pct": int(self._total_tokens_used / max(self.config.token_budget, 1) * 100),
            "compression_level": self._compression_level,
        }

    def get_messages_raw(self) -> list[dict[str, Any]]:
        """Get raw messages without compression (for state snapshots)."""
        return self._messages.copy()

    def restore_messages(self, messages: list[dict[str, Any]]) -> None:
        """Restore messages from a checkpoint."""
        self._messages = messages
