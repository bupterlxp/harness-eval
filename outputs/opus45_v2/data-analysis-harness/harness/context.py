"""
Context Manager (C) - LLM context management with compression.

Manages LLM prompts using schema + statistical summaries instead of full DataFrame content.
"""

import json
from typing import Any, Optional
import pandas as pd

from harness.state import StateStore, get_df_schema, get_df_stats


class ContextManager:
    """
    Manages LLM context by compressing DataFrame information into
    schema + statistics summaries. Never includes full DataFrame content.
    """

    MAX_SAMPLE_ROWS = 3
    MAX_COLUMN_DISPLAY = 50

    def __init__(self, state_store: StateStore):
        self.state = state_store
        self.system_prompt: str = ""
        self.analysis_goal: str = ""
        self.constraints: list[str] = []
        self.conversation_history: list[dict] = []

    def set_analysis_goal(self, goal: str) -> None:
        """Set the analysis goal/task description."""
        self.analysis_goal = goal

    def set_constraints(self, constraints: list[str]) -> None:
        """Set analysis constraints."""
        self.constraints = constraints

    def _format_df_summary(self, name: str, df: pd.DataFrame) -> str:
        """Format DataFrame as schema + statistics (NOT full content)."""
        stats = get_df_stats(df)
        schema = get_df_schema(df)

        lines = [f"DataFrame: {name}"]
        lines.append(f"  Shape: {stats['shape'][0]} rows × {stats['shape'][1]} columns")
        lines.append(f"  Memory: {stats['memory_mb']:.2f} MB")

        lines.append("  Columns:")
        cols = list(schema.items())
        if len(cols) > self.MAX_COLUMN_DISPLAY:
            cols = cols[:self.MAX_COLUMN_DISPLAY]
            lines.append(f"    (showing first {self.MAX_COLUMN_DISPLAY} of {len(schema)} columns)")

        for col, dtype in cols:
            null_count = stats['null_counts'].get(col, 0)
            null_pct = (null_count / stats['shape'][0] * 100) if stats['shape'][0] > 0 else 0
            lines.append(f"    - {col}: {dtype} (nulls: {null_count}, {null_pct:.1f}%)")

        if "numeric_summary" in stats:
            lines.append("  Numeric Summary:")
            for col, col_stats in list(stats["numeric_summary"].items())[:10]:
                lines.append(f"    {col}: min={col_stats.get('min')}, max={col_stats.get('max')}, "
                           f"mean={col_stats.get('mean')}, std={col_stats.get('std')}")

        sample = df.head(self.MAX_SAMPLE_ROWS)
        lines.append(f"  Sample ({self.MAX_SAMPLE_ROWS} rows):")
        lines.append("    " + sample.to_string(max_cols=10).replace("\n", "\n    "))

        return "\n".join(lines)

    def _format_all_dataframes(self) -> str:
        """Format all DataFrames in state as compressed summaries."""
        dfs = self.state.get_all_dataframes()
        if not dfs:
            return "No DataFrames loaded yet."

        summaries = []
        for name, df in dfs.items():
            summaries.append(self._format_df_summary(name, df))

        return "\n\n".join(summaries)

    def _format_variables(self) -> str:
        """Format stored variables for context."""
        variables = self.state.variables
        if not variables:
            return "No variables stored."

        lines = ["Stored Variables:"]
        for name, value in variables.items():
            val_str = str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            lines.append(f"  {name}: {val_str}")

        return "\n".join(lines)

    def _format_charts(self) -> str:
        """Format generated charts for context."""
        if not self.state.charts:
            return "No charts generated yet."

        lines = ["Generated Charts:"]
        for chart in self.state.charts:
            lines.append(f"  - {chart['path']} ({chart['chart_type']}): {chart['description']}")

        return "\n".join(lines)

    def _format_insights(self) -> str:
        """Format discovered insights."""
        if not self.state.insights:
            return "No insights recorded yet."

        lines = ["Discovered Insights:"]
        for i, insight in enumerate(self.state.insights, 1):
            lines.append(f"  {i}. {insight}")

        return "\n".join(lines)

    def _format_step_history(self, max_steps: int = 5) -> str:
        """Format recent step history."""
        snapshots = self.state.snapshots[-max_steps:] if self.state.snapshots else []
        if not snapshots:
            return "No steps executed yet."

        lines = ["Recent Steps:"]
        for snap in snapshots:
            lines.append(f"  Step {snap.step_id} ({snap.timestamp}):")
            if snap.code_executed:
                code_preview = snap.code_executed[:150]
                if len(snap.code_executed) > 150:
                    code_preview += "..."
                lines.append(f"    Code: {code_preview}")
            if snap.output_shape:
                lines.append(f"    Output shape: {snap.output_shape}")
            if snap.charts_generated:
                lines.append(f"    Charts: {', '.join(snap.charts_generated)}")

        return "\n".join(lines)

    def build_system_prompt(self) -> str:
        """Build the system prompt for LLM."""
        return """You are a data analysis agent. Your task is to analyze data and generate insights.

IMPORTANT RULES:
1. Write Python code to analyze data using pandas, matplotlib, seaborn, numpy.
2. When generating charts, ALWAYS save to files (plt.savefig()), NEVER use plt.show().
3. Every insight MUST have specific numbers from the data (e.g., "Sales increased 23% from $1.2M to $1.5M").
4. Validate calculations before reporting results.
5. Use appropriate chart types for the data.

AVAILABLE TOOLS:
- load_data(path): Load CSV/Excel/JSON/Parquet files
- execute_code(code): Execute Python code with pandas/matplotlib/seaborn/numpy
- save_chart(fig, name, chart_type, description): Save a matplotlib figure
- record_insight(insight): Record a data-driven insight with numbers
- get_dataframe(name): Get a DataFrame by name
- finish(): Mark analysis as complete

Respond with a JSON object:
{
    "thought": "Your reasoning about what to do next",
    "action": "tool_name",
    "action_input": { ... tool arguments ... }
}

For execute_code, the code should define a 'result' variable with the output.
For charts, always close the figure after saving to avoid memory issues."""

    def build_user_context(self) -> str:
        """Build the current context for LLM (compressed, no full DataFrames)."""
        sections = []

        sections.append(f"ANALYSIS GOAL:\n{self.analysis_goal}")

        if self.constraints:
            sections.append("CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in self.constraints))

        sections.append(f"CURRENT STATE:\n"
                       f"Step: {self.state.current_step}\n"
                       f"DataFrames loaded: {self.state.list_dataframes()}")

        sections.append("DATA CONTEXT:\n" + self._format_all_dataframes())

        sections.append(self._format_variables())
        sections.append(self._format_charts())
        sections.append(self._format_insights())
        sections.append(self._format_step_history())

        return "\n\n---\n\n".join(sections)

    def add_message(self, role: str, content: str) -> None:
        """Add message to conversation history."""
        self.conversation_history.append({"role": role, "content": content})

    def get_messages(self) -> list[dict]:
        """Get messages for LLM API call."""
        messages = [{"role": "system", "content": self.build_system_prompt()}]

        context = self.build_user_context()
        messages.append({"role": "user", "content": f"Current context:\n\n{context}\n\nWhat is your next action?"})

        for msg in self.conversation_history[-10:]:
            messages.append(msg)

        return messages

    def clear_history(self) -> None:
        """Clear conversation history (but keep context)."""
        self.conversation_history = []

    def compress_for_large_data(self, df: pd.DataFrame, max_rows: int = 10000) -> pd.DataFrame:
        """
        Compress large DataFrame by sampling if needed.
        Returns original if small enough, sampled version if too large.
        """
        if len(df) <= max_rows:
            return df

        sampled = df.sample(n=max_rows, random_state=42)
        return sampled

    def estimate_token_count(self) -> int:
        """Rough estimate of token count in current context."""
        context = self.build_user_context()
        return len(context) // 4
