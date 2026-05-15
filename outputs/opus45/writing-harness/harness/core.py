"""
core.py - H: Harness Aggregation Class

Aggregates all six components (E, T, C, S, L, V) into a unified interface.
Provides run(task) entry point for task execution.
"""

from __future__ import annotations
import os
import uuid
from pathlib import Path
from typing import Any, Callable

from harness.schemas import (
    TaskSpec, SessionState, ExecutionState, StyleSpec,
    ComparisonReport, ComparisonDimension
)
from harness.state import StateStore
from harness.tools import ToolRegistry
from harness.context import ContextManager, ContextBudget
from harness.lifecycle import HookManager, ApprovalHook, AuditHook
from harness.evaluation import TrajectoryRecorder
from harness.execution import ExecutionLoop


class Harness:
    """
    H = (E, T, C, S, L, V)

    Main harness class that aggregates all six components and provides
    a unified interface for short story generation.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        trajectory_dir: str | Path | None = None,
        approval_handler: Callable[[str, dict[str, Any]], bool] | None = None,
        on_output: Callable[[str], None] | None = None,
        auto_approve: bool = False
    ):
        self.state_store = StateStore(db_path)

        self.tools = ToolRegistry()

        self.context = ContextManager(
            budget=ContextBudget(total_tokens=8000, reserved_for_output=2000)
        )

        self.hooks = HookManager()

        if auto_approve:
            self._approval_hook = self.hooks.create_approval_hook(lambda t, a: True)
        elif approval_handler:
            self._approval_hook = self.hooks.create_approval_hook(approval_handler)
        else:
            self._approval_hook = self.hooks.create_approval_hook()

        self._audit_hook = self.hooks.create_audit_hook()

        self._trajectory_dir = Path(trajectory_dir) if trajectory_dir else None
        self._current_trajectory: TrajectoryRecorder | None = None

        self._on_output = on_output or (lambda x: print(x))

        self._execution: ExecutionLoop | None = None
        self._current_session: SessionState | None = None

    def _create_trajectory(self, session_id: str) -> TrajectoryRecorder:
        """Create a trajectory recorder for a session"""
        return TrajectoryRecorder(session_id, self._trajectory_dir)

    def _create_execution(self, trajectory: TrajectoryRecorder) -> ExecutionLoop:
        """Create an execution loop with all components"""
        return ExecutionLoop(
            tools=self.tools,
            context=self.context,
            state_store=self.state_store,
            hooks=self.hooks,
            trajectory=trajectory,
            on_output=self._on_output
        )

    def register_tools(self, tools: list[Any]) -> None:
        """Register domain-specific tools"""
        for tool in tools:
            self.tools.register(tool)

    def parse_task_input(self, raw_input: str) -> TaskSpec:
        """Parse raw task input into TaskSpec"""
        lines = raw_input.strip().split('\n')
        spec_dict: dict[str, Any] = {
            "raw_input": raw_input,
            "genre": "psychological thriller",
            "core_tension": "",
            "obsession_object": "",
            "style": {}
        }

        current_section = None
        current_value = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if ':' in line and not line.startswith('-') and not line.startswith(' '):
                if current_section and current_value:
                    spec_dict[current_section] = '\n'.join(current_value).strip()

                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_').replace('体裁', 'genre').replace('篇幅', 'word_count').replace('视角', 'pov').replace('核心张力', 'core_tension')

                if key == 'genre':
                    spec_dict['genre'] = value.strip()
                    current_section = None
                elif key == 'word_count' or key == '篇幅':
                    import re
                    match = re.search(r'(\d+).*?(\d+)?', value)
                    if match:
                        spec_dict['word_count_min'] = int(match.group(1))
                        if match.group(2):
                            spec_dict['word_count_max'] = int(match.group(2))
                    current_section = None
                elif key == 'pov':
                    spec_dict['pov'] = value.strip()
                    current_section = None
                elif key == 'core_tension':
                    spec_dict['core_tension'] = value.strip()
                    current_section = None
                elif '关键约束' in key or 'constraints' in key.lower():
                    current_section = 'constraints'
                    current_value = []
                elif '风格' in key or 'style' in key.lower():
                    current_section = 'style_notes'
                    current_value = []
                else:
                    spec_dict[key] = value.strip()
                    current_section = None
            elif line.startswith('-'):
                content = line[1:].strip()
                if current_section == 'constraints':
                    if '执念' in content or 'obsession' in content.lower():
                        spec_dict['obsession_object'] = content
                    elif '延宕' in content or 'delay' in content.lower():
                        spec_dict['temporal_structure'] = 'delay_then_eruption'
                    elif '隐藏' in content or 'conceal' in content.lower():
                        spec_dict['concealment_method'] = content
                    elif '感官' in content or 'sensory' in content.lower():
                        spec_dict['exposure_signal'] = 'auditory'
                    elif '崩溃' in content or 'breakdown' in content.lower():
                        spec_dict['ending_type'] = 'self_confession'
                elif current_section == 'style_notes':
                    if '破折号' in content or 'dash' in content.lower():
                        spec_dict.setdefault('style', {})['dash_density'] = 'high'
                    if '感叹号' in content or 'exclamation' in content.lower():
                        spec_dict.setdefault('style', {})['exclamation_density'] = 'high'
                    if '呼告' in content or 'address' in content.lower():
                        spec_dict.setdefault('style', {})['reader_address_frequency'] = 'frequent'
                    if '重复' in content or 'repetition' in content.lower():
                        spec_dict.setdefault('style', {})['repetition_style'] = 'escalating'
                    if '听觉' in content or 'auditory' in content.lower():
                        spec_dict.setdefault('style', {})['dominant_sensory'] = 'auditory'

        if 'style' in spec_dict and isinstance(spec_dict['style'], dict):
            spec_dict['style'] = StyleSpec(**spec_dict['style'])
        else:
            spec_dict['style'] = StyleSpec()

        required = ['genre', 'core_tension', 'obsession_object']
        for field in required:
            if not spec_dict.get(field):
                spec_dict[field] = f"[{field} not specified]"

        return TaskSpec(**spec_dict)

    def run(self, task: str | TaskSpec, session_id: str | None = None) -> SessionState:
        """
        Main entry point: run a writing task to completion.

        Args:
            task: Either raw task string or TaskSpec object
            session_id: Optional session ID (generated if not provided)

        Returns:
            Final session state with generated story
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        if isinstance(task, str):
            task_spec = self.parse_task_input(task)
        else:
            task_spec = task

        self._current_session = self.state_store.create_session(session_id)
        self._current_session.task_spec = task_spec

        self._current_trajectory = self._create_trajectory(session_id)
        self._execution = self._create_execution(self._current_trajectory)

        self._on_output(f"Starting session {session_id[:8]}...")
        final_state = self._execution.run(self._current_session)

        return final_state

    def resume(self, session_id: str) -> SessionState:
        """Resume a previously interrupted session"""
        self._current_trajectory = self._create_trajectory(session_id)
        self._execution = self._create_execution(self._current_trajectory)

        self._on_output(f"Resuming session {session_id[:8]}...")
        return self._execution.resume(session_id)

    def get_trajectory(self) -> TrajectoryRecorder | None:
        """Get current trajectory recorder"""
        return self._current_trajectory

    def get_session(self) -> SessionState | None:
        """Get current session state"""
        return self._current_session

    def interrupt(self) -> None:
        """Interrupt current execution"""
        if self._execution:
            self._execution.interrupt()

    def compare_with_sample(self, sample_path: str | Path) -> ComparisonReport:
        """Compare current output with sample file"""
        sample_path = Path(sample_path)
        if not sample_path.exists():
            raise FileNotFoundError(f"Sample not found: {sample_path}")

        with open(sample_path) as f:
            sample_text = f.read()

        if not self._current_session or not self._current_session.final_draft:
            raise ValueError("No generated output to compare")

        actual_text = self._current_session.final_draft

        report = ComparisonReport()

        sample_words = len(sample_text.split())
        actual_words = len(actual_text.split())
        report.structure_comparisons.append(ComparisonDimension(
            dimension="structure",
            aspect="word_count",
            sample_value=str(sample_words),
            actual_value=str(actual_words),
            aligned=0.8 <= actual_words/sample_words <= 1.2,
            gap_description=f"Difference: {actual_words - sample_words} words"
        ))

        sample_dashes = sample_text.count('—') + sample_text.count('--')
        actual_dashes = actual_text.count('—') + actual_text.count('--')
        report.style_comparisons.append(ComparisonDimension(
            dimension="style",
            aspect="dash_density",
            sample_value=f"{sample_dashes / sample_words * 100:.2f}%",
            actual_value=f"{actual_dashes / max(1, actual_words) * 100:.2f}%",
            aligned=abs(sample_dashes/sample_words - actual_dashes/max(1, actual_words)) < 0.02,
            component_attribution="C" if not abs(sample_dashes/sample_words - actual_dashes/max(1, actual_words)) < 0.02 else ""
        ))

        sample_exclaim = sample_text.count('!')
        actual_exclaim = actual_text.count('!')
        report.style_comparisons.append(ComparisonDimension(
            dimension="style",
            aspect="exclamation_density",
            sample_value=f"{sample_exclaim / sample_words * 100:.2f}%",
            actual_value=f"{actual_exclaim / max(1, actual_words) * 100:.2f}%",
            aligned=abs(sample_exclaim/sample_words - actual_exclaim/max(1, actual_words)) < 0.02,
            component_attribution="C" if not abs(sample_exclaim/sample_words - actual_exclaim/max(1, actual_words)) < 0.02 else ""
        ))

        reader_addresses = ['you', 'your', 'yourself']
        sample_addresses = sum(sample_text.lower().count(w) for w in reader_addresses)
        actual_addresses = sum(actual_text.lower().count(w) for w in reader_addresses)
        report.style_comparisons.append(ComparisonDimension(
            dimension="style",
            aspect="reader_address_frequency",
            sample_value=str(sample_addresses),
            actual_value=str(actual_addresses),
            aligned=0.5 <= actual_addresses/max(1, sample_addresses) <= 2.0,
            component_attribution="T" if not 0.5 <= actual_addresses/max(1, sample_addresses) <= 2.0 else ""
        ))

        aligned_count = sum(1 for c in report.structure_comparisons + report.style_comparisons + report.imagery_comparisons if c.aligned)
        total_count = len(report.structure_comparisons) + len(report.style_comparisons) + len(report.imagery_comparisons)
        report.overall_alignment_score = aligned_count / max(1, total_count)

        report.summary = f"Alignment score: {report.overall_alignment_score:.2%} ({aligned_count}/{total_count} dimensions aligned)"

        return report

    def get_final_draft(self) -> str:
        """Get the final generated text"""
        if self._current_session and self._current_session.final_draft:
            return self._current_session.final_draft
        return ""

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions"""
        return self.state_store.list_sessions()


def create_harness(**kwargs) -> Harness:
    """Factory function to create a configured harness"""
    from harness.domain.tools import get_domain_tools

    harness = Harness(**kwargs)
    harness.register_tools(get_domain_tools())
    return harness
