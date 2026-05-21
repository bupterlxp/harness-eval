"""Context Manager (C) — context management and compression with token budget.

Manages the LLM context window: builds prompts from state, accessibility tree,
plan, and memory. Implements auto-summarize/truncate when token budget is exceeded.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from harness.state import TaskState, SubGoalStatus, StepMemory, Plan


@dataclass
class TokenBudget:
    """Token budget configuration."""

    max_tokens: int = 12000  # Max context tokens for LLM input
    system_prompt_budget: int = 2000
    tree_budget: int = 4000
    history_budget: int = 3000
    plan_budget: int = 1500
    memory_budget: int = 1500

    def total_allocated(self) -> int:
        return (
            self.system_prompt_budget
            + self.tree_budget
            + self.history_budget
            + self.plan_budget
            + self.memory_budget
        )


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (rough: ~4 chars per token)."""
    return len(text) // 4


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within token budget."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    # Truncate from middle, keeping beginning and end
    keep = max_chars // 2
    return text[:keep] + "\n... [truncated] ...\n" + text[-keep:]


class ContextManager:
    """Manages context construction and compression for LLM prompts."""

    def __init__(self, budget: TokenBudget | None = None):
        self.budget = budget or TokenBudget()
        self._conversation_history: list[dict[str, Any]] = []
        self._max_history_entries: int = 10

    def build_system_prompt(self, task_state: TaskState, max_steps: int) -> str:
        """Build the system prompt with task context."""
        budget_pct = int(task_state.budget_fraction(max_steps) * 100)

        prompt = f"""You are a browser automation agent. You complete web tasks by observing page state and taking actions.

TASK: {task_state.task_prompt}

RULES:
1. Observe the accessibility tree carefully before acting.
2. Use element indices [N] from the tree for clicks and fills.
3. One action per step. Think step-by-step.
4. When the task is done, use the "done" action with a result summary.
5. If stuck, try scrolling, navigating back, or a different approach.
6. Extract and accumulate data as you go for data extraction tasks.

BUDGET: Step {task_state.step_number}/{max_steps} ({budget_pct}% used)"""

        if budget_pct >= 75:
            prompt += "\n\nURGENT: Budget at 75%+. Save any partial results now using 'done' action."

        if task_state.step_number >= max_steps - 1:
            prompt += "\n\nFINAL STEP: You MUST use the 'done' action now. No other actions allowed."

        return truncate_to_budget(prompt, self.budget.system_prompt_budget)

    def build_observation(
        self,
        task_state: TaskState,
        accessibility_tree: str,
        max_steps: int,
        warnings: list[str] | None = None,
    ) -> str:
        """Build the observation message combining all context."""
        parts: list[str] = []

        # Tab state
        if task_state.tabs:
            tab_lines = ["## Open Tabs:"]
            for tab in task_state.tabs:
                active = " [ACTIVE]" if tab.is_active else ""
                tab_lines.append(f"  - {tab.tab_id}: {tab.title} ({tab.url}){active}")
            parts.append("\n".join(tab_lines))

        # Current URL
        parts.append(f"\n## Current URL: {task_state.current_url}")

        # Plan visualization
        plan_str = self._format_plan(task_state.plan)
        if plan_str:
            parts.append(plan_str)

        # Warnings
        if warnings:
            parts.append("\n## WARNINGS:")
            for w in warnings:
                parts.append(f"  ! {w}")

        # Accessibility tree
        tree_truncated = truncate_to_budget(accessibility_tree, self.budget.tree_budget)
        parts.append(f"\n## Page Accessibility Tree:\n{tree_truncated}")

        # Step memory
        if task_state.step_memories:
            latest = task_state.step_memories[-1]
            parts.append(f"\n## Previous Step Result: {'Success' if latest.previous_action_success else 'FAILED'}")
            parts.append(f"## Memory: {latest.memory_summary}")
            parts.append(f"## Current Goal: {latest.next_goal}")

        # Rolling summary
        if task_state.rolling_summary:
            summary_truncated = truncate_to_budget(
                task_state.rolling_summary, self.budget.memory_budget // 2
            )
            parts.append(f"\n## Task Progress Summary:\n{summary_truncated}")

        # Extracted data summary
        if task_state.extracted_data:
            data_summary = f"\n## Extracted Data: {len(task_state.extracted_data)} items collected"
            if len(task_state.extracted_data) <= 3:
                for item in task_state.extracted_data:
                    data_summary += f"\n  - {json.dumps(item)[:200]}"
            parts.append(data_summary)

        observation = "\n".join(parts)

        # Final truncation to ensure we fit in budget
        total_budget = (
            self.budget.tree_budget
            + self.budget.plan_budget
            + self.budget.memory_budget
            + self.budget.history_budget
        )
        return truncate_to_budget(observation, total_budget)

    def build_messages(
        self,
        system_prompt: str,
        observation: str,
        task_state: TaskState,
        max_steps: int,
    ) -> list[dict[str, Any]]:
        """Build complete message list for LLM call."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Add compressed conversation history
        for entry in self._conversation_history[-self._max_history_entries:]:
            messages.append(entry)

        # Add current observation as user message
        user_msg = observation

        # On final step, constrain to only "done"
        if task_state.step_number >= max_steps - 1:
            user_msg += '\n\nYou MUST respond with the "done" action only.'

        messages.append({"role": "user", "content": user_msg})

        # Check total size and compress if needed
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        if total_tokens > self.budget.max_tokens:
            messages = self._compress_messages(messages)

        return messages

    def add_to_history(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        self._conversation_history.append({"role": role, "content": content})
        # Auto-trim history
        if len(self._conversation_history) > self._max_history_entries * 2:
            self._compress_history()

    def _compress_history(self) -> None:
        """Compress conversation history by summarizing older entries."""
        if len(self._conversation_history) <= self._max_history_entries:
            return
        # Keep only recent entries, summarize older ones
        old = self._conversation_history[:-self._max_history_entries]
        recent = self._conversation_history[-self._max_history_entries:]

        # Create a summary of old entries
        actions_summary = []
        for entry in old:
            content = entry.get("content", "")
            if entry["role"] == "assistant" and "action" in content.lower():
                # Extract action name
                try:
                    parsed = json.loads(content)
                    action = parsed.get("action", "unknown")
                    actions_summary.append(action)
                except (json.JSONDecodeError, TypeError):
                    pass

        if actions_summary:
            summary_msg = {
                "role": "user",
                "content": f"[Previous actions: {', '.join(actions_summary[-10:])}]",
            }
            self._conversation_history = [summary_msg] + recent
        else:
            self._conversation_history = recent

    def _compress_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress messages to fit within token budget."""
        # Strategy: shorten middle messages, keep system and latest observation
        if len(messages) <= 2:
            return messages

        system = messages[0]
        latest = messages[-1]
        middle = messages[1:-1]

        # Aggressively truncate middle messages
        compressed_middle = []
        for msg in middle[-3:]:  # Keep only last 3 middle messages
            content = msg.get("content", "")
            compressed = truncate_to_budget(content, 500)
            compressed_middle.append({"role": msg["role"], "content": compressed})

        return [system] + compressed_middle + [latest]

    def _format_plan(self, plan: Plan) -> str:
        """Format plan for display in context."""
        if not plan.sub_goals:
            return ""

        lines = ["\n## Task Plan:"]
        for i, goal in enumerate(plan.sub_goals, 1):
            status_icon = {
                SubGoalStatus.PENDING: "[ ]",
                SubGoalStatus.CURRENT: "[>]",
                SubGoalStatus.DONE: "[x]",
                SubGoalStatus.SKIPPED: "[-]",
                SubGoalStatus.FAILED: "[!]",
            }.get(goal.status, "[ ]")
            line = f"  {status_icon} {i}. {goal.description}"
            if goal.result_summary:
                line += f" ({goal.result_summary})"
            lines.append(line)

        lines.append(f"  Progress: {plan.progress_str()}")
        return "\n".join(lines)

    def build_planning_prompt(self, task_prompt: str) -> list[dict[str, Any]]:
        """Build prompt for initial task planning/decomposition."""
        return [
            {
                "role": "system",
                "content": """You are a task planning agent. Decompose the given web task into 3-10 concrete sub-goals.
Each sub-goal should be a specific, actionable step that can be verified.
Respond with a JSON array of sub-goal descriptions.

Example:
["Navigate to the search page", "Enter search query", "Click search button", "Extract first 5 results", "Save results"]""",
            },
            {
                "role": "user",
                "content": f"Decompose this web task into sub-goals:\n\n{task_prompt}",
            },
        ]

    def build_summary_prompt(
        self, previous_summary: str, recent_actions: list[str]
    ) -> list[dict[str, Any]]:
        """Build prompt for rolling summary update."""
        return [
            {
                "role": "system",
                "content": "You are a concise summarizer. Update the task progress summary with recent actions. Keep it under 200 words.",
            },
            {
                "role": "user",
                "content": f"Previous summary: {previous_summary or 'None'}\n\nRecent actions:\n"
                + "\n".join(f"- {a}" for a in recent_actions)
                + "\n\nProvide updated summary:",
            },
        ]

    def reset(self) -> None:
        """Reset context manager state."""
        self._conversation_history = []
