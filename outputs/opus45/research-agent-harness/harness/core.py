"""Research Harness Core (H) - Six-component aggregation.

H = (E, T, C, S, L, V)
- E: Execution Loop (research state machine)
- T: Tool Registry
- C: Context Manager
- S: State Store
- L: Lifecycle Hooks
- V: Evaluation Interface (trajectory logging)
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Optional, Awaitable

from harness.schemas import ResearchTask, ResearchState
from harness.state import StateStore
from harness.tools import ToolRegistry, RateLimitConfig
from harness.context import ContextManager
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryLogger
from harness.execution import ResearchStateMachine


class ResearchHarness:
    """Complete research harness combining all six components.

    H = (E, T, C, S, L, V)
    """

    def __init__(
        self,
        task: Optional[ResearchTask] = None,
        trajectory_path: Optional[Path] = None,
        max_hops: int = 3,
        evidence_threshold: int = 2,
        max_evidence_context: int = 100,
        relevance_threshold: float = 0.5,
        min_source_reliability: float = 0.3,
    ) -> None:
        """Initialize the research harness.

        Args:
            task: Research task specification
            trajectory_path: Path for JSONL trajectory output
            max_hops: Maximum multi-hop search iterations
            evidence_threshold: Minimum evidence per section before gap fill
            max_evidence_context: Maximum evidence entries in active context
            relevance_threshold: Threshold for context compression
            min_source_reliability: Minimum reliability for source inclusion
        """
        self.task = task
        self.max_hops = max_hops
        self.evidence_threshold = evidence_threshold

        required_sections = task.required_sections if task else []

        self._state_store = StateStore(required_sections)
        self._state_store.max_hops = max_hops

        self._tool_registry = ToolRegistry()

        self._context_manager = ContextManager(
            required_sections=required_sections,
            max_evidence_entries=max_evidence_context,
            relevance_threshold=relevance_threshold,
        )

        self._lifecycle_manager = LifecycleManager()
        self._setup_lifecycle_hooks(min_source_reliability)

        self._trajectory_logger = TrajectoryLogger(trajectory_path)

        self._state_machine: Optional[ResearchStateMachine] = None

        self._on_state_change: Optional[Callable[[ResearchState, str], Awaitable[None]]] = None
        self._on_progress: Optional[Callable[[str], Awaitable[None]]] = None

    def _setup_lifecycle_hooks(self, min_source_reliability: float) -> None:
        """Set up default lifecycle hooks."""
        self._lifecycle_manager.register_pre_search(
            lambda: self._context_manager.history._query_texts
        )

        self._lifecycle_manager.register_post_search(min_source_reliability)

        self._lifecycle_manager.register_pre_draft(self.evidence_threshold)

        self._lifecycle_manager.register_post_draft(
            self._state_store.citation_mapper.validate_citations
        )

        self._lifecycle_manager.register_on_rate_limit(max_wait=300.0)

    @property
    def state_store(self) -> StateStore:
        """Get state store (S)."""
        return self._state_store

    @property
    def tool_registry(self) -> ToolRegistry:
        """Get tool registry (T)."""
        return self._tool_registry

    @property
    def context_manager(self) -> ContextManager:
        """Get context manager (C)."""
        return self._context_manager

    @property
    def lifecycle_manager(self) -> LifecycleManager:
        """Get lifecycle manager (L)."""
        return self._lifecycle_manager

    @property
    def trajectory_logger(self) -> TrajectoryLogger:
        """Get trajectory logger (V)."""
        return self._trajectory_logger

    def register_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        rate_limit: Optional[RateLimitConfig] = None,
    ) -> None:
        """Register a tool with the registry."""
        from harness.tools import ToolSafety
        self._tool_registry.register(
            name=name,
            func=func,
            description=description,
            safety=ToolSafety.SAFE,
            rate_limit=rate_limit,
        )

    def register_domain_tools(self, tools_module: Any) -> None:
        """Register all tools from a domain tools module."""
        from harness.tools import register_tools_from_module
        register_tools_from_module(self._tool_registry, tools_module)

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[ResearchState, str], Awaitable[None]]] = None,
        on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """Set callback functions for events."""
        self._on_state_change = on_state_change
        self._on_progress = on_progress

    async def run(self, task: Optional[ResearchTask] = None) -> dict[str, Any]:
        """Run the research pipeline.

        Args:
            task: Research task (uses initialized task if not provided)

        Returns:
            Dictionary with results including report and statistics
        """
        if task:
            self.task = task
            self._state_store = StateStore(task.required_sections)
            self._state_store.max_hops = self.max_hops
            self._context_manager = ContextManager(
                required_sections=task.required_sections,
            )
            self._setup_lifecycle_hooks(0.3)

        if not self.task:
            raise ValueError("No research task provided")

        self._state_machine = ResearchStateMachine(
            state_store=self._state_store,
            context_manager=self._context_manager,
            lifecycle_manager=self._lifecycle_manager,
            trajectory_logger=self._trajectory_logger,
            tool_registry=self._tool_registry,
            max_hops=self.max_hops,
            evidence_threshold=self.evidence_threshold,
        )

        self._state_machine.set_callbacks(
            on_state_change=self._on_state_change,
            on_progress=self._on_progress,
        )

        result = await self._state_machine.run(self.task)

        return {
            "success": result.get("success", False),
            "report": self._state_store.draft_manager.generate_report(),
            "sources": [
                {
                    "url": s.url,
                    "title": s.title,
                    "reliability": s.reliability.value if hasattr(s.reliability, 'value') else str(s.reliability),
                    "score": s.overall_score,
                }
                for s in self._state_store.evidence_store.get_all_sources()
            ],
            "citations": self._state_store.citation_mapper.get_citation_count(),
            "evidence_count": self._state_store.evidence_store.get_evidence_count(),
            "hops_used": self._state_store.hop_count,
            "trajectory_summary": result.get("trajectory_summary", {}),
            "state_summary": result.get("state_summary", {}),
        }

    def run_sync(self, task: Optional[ResearchTask] = None) -> dict[str, Any]:
        """Synchronous wrapper for run()."""
        return asyncio.get_event_loop().run_until_complete(self.run(task))

    def get_sources(self) -> list[dict]:
        """Get list of collected sources."""
        return [
            {
                "id": s.id,
                "url": s.url,
                "title": s.title,
                "reliability": s.reliability.value if hasattr(s.reliability, 'value') else str(s.reliability),
                "relevance": s.relevance_score,
                "overall_score": s.overall_score,
                "evaluated": s.evaluated,
            }
            for s in self._state_store.evidence_store.get_all_sources()
        ]

    def get_gaps(self) -> list[dict]:
        """Get information gaps by section."""
        gaps = []
        for section_name in (self.task.required_sections if self.task else []):
            evidence = self._state_store.evidence_store.get_evidence_for_section(section_name)
            if len(evidence) < self.evidence_threshold:
                gaps.append({
                    "section": section_name,
                    "current_evidence": len(evidence),
                    "required_evidence": self.evidence_threshold,
                    "gap_size": self.evidence_threshold - len(evidence),
                })
        return gaps

    def get_outline(self) -> dict[str, dict]:
        """Get current report outline with completion status."""
        return self._state_store.draft_manager.get_outline()

    def verify_claim(self, claim: str) -> dict:
        """Verify a claim against collected evidence."""
        evidence_list = list(self._state_store.evidence_store._evidence.values())

        supporting = []
        conflicting = []

        claim_words = set(claim.lower().split())

        for ev in evidence_list:
            ev_words = set(ev.content.lower().split())
            overlap = len(claim_words & ev_words) / max(len(claim_words), 1)

            if overlap > 0.3:
                source = self._state_store.evidence_store.get_source(ev.source_id)
                entry = {
                    "evidence_id": ev.id,
                    "content": ev.content[:200],
                    "source_url": source.url if source else "unknown",
                    "overlap_score": overlap,
                }
                supporting.append(entry)

        return {
            "claim": claim,
            "supporting_evidence": supporting[:5],
            "conflicting_evidence": conflicting[:5],
            "verification_status": "supported" if supporting else "unverified",
        }

    def get_state_summary(self) -> dict:
        """Get summary of current state."""
        return self._state_store.get_summary()

    def get_trajectory(self) -> list[dict]:
        """Get the full trajectory log."""
        return [step.to_dict() if hasattr(step, 'to_dict') else vars(step)
                for step in self._trajectory_logger.get_trajectory()]

    def save_state(self, path: Path) -> None:
        """Save current state to file."""
        self._state_store.save_snapshot(path)

    def close(self) -> None:
        """Clean up resources."""
        self._trajectory_logger.close()

    @classmethod
    def from_json_file(cls, path: Path, **kwargs) -> "ResearchHarness":
        """Create harness from a JSON task file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        task = ResearchTask.from_json(data)
        return cls(task=task, **kwargs)
