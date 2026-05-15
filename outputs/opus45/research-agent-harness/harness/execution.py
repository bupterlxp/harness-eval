"""Execution Loop (E) - Research state machine with multi-hop support.

States: DECOMPOSE → SEARCH → EVALUATE → EXTRACT → ORGANIZE → GAP_FILL →
        CROSS_VALIDATE → DRAFT → CONSISTENCY_CHECK → FINALIZE → COMPLETED

GAP_FILL can loop back to SEARCH with max_hops limit to prevent infinite loops.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, Awaitable

from harness.schemas import (
    ResearchState,
    ResearchTask,
    ResearchQuery,
    Source,
    Evidence,
    GapAnalysis,
)
from harness.state import StateStore
from harness.context import ContextManager
from harness.lifecycle import LifecycleManager, HookResult
from harness.evaluation import TrajectoryLogger
from harness.tools import ToolRegistry


class ExecutionError(Exception):
    """Error during execution."""
    pass


@dataclass
class StateContext:
    """Context for state execution."""
    task: ResearchTask
    queries: list[ResearchQuery] = field(default_factory=list)
    current_query_index: int = 0
    current_section_index: int = 0
    gap_fill_section: Optional[str] = None
    iteration: int = 0


@dataclass
class StateResult:
    """Result from a state execution."""
    next_state: ResearchState
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    should_notify_user: bool = False


class ResearchStateMachine:
    """State machine for research execution with multi-hop support."""

    def __init__(
        self,
        state_store: StateStore,
        context_manager: ContextManager,
        lifecycle_manager: LifecycleManager,
        trajectory_logger: TrajectoryLogger,
        tool_registry: ToolRegistry,
        max_hops: int = 3,
        evidence_threshold: int = 2,
    ) -> None:
        self.state_store = state_store
        self.context = context_manager
        self.lifecycle = lifecycle_manager
        self.trajectory = trajectory_logger
        self.tools = tool_registry
        self.max_hops = max_hops
        self.evidence_threshold = evidence_threshold

        self._state_handlers: dict[ResearchState, Callable] = {
            ResearchState.DECOMPOSE: self._handle_decompose,
            ResearchState.SEARCH: self._handle_search,
            ResearchState.EVALUATE: self._handle_evaluate,
            ResearchState.EXTRACT: self._handle_extract,
            ResearchState.ORGANIZE: self._handle_organize,
            ResearchState.GAP_FILL: self._handle_gap_fill,
            ResearchState.CROSS_VALIDATE: self._handle_cross_validate,
            ResearchState.DRAFT: self._handle_draft,
            ResearchState.CONSISTENCY_CHECK: self._handle_consistency_check,
            ResearchState.FINALIZE: self._handle_finalize,
        }

        self._on_state_change: Optional[Callable[[ResearchState, str], Awaitable[None]]] = None
        self._on_progress: Optional[Callable[[str], Awaitable[None]]] = None

    def set_callbacks(
        self,
        on_state_change: Optional[Callable[[ResearchState, str], Awaitable[None]]] = None,
        on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        """Set callback functions for events."""
        self._on_state_change = on_state_change
        self._on_progress = on_progress

    async def run(self, task: ResearchTask) -> dict[str, Any]:
        """Run the full research pipeline."""
        ctx = StateContext(task=task)
        current_state = ResearchState.DECOMPOSE

        while current_state != ResearchState.COMPLETED:
            handler = self._state_handlers.get(current_state)
            if not handler:
                raise ExecutionError(f"No handler for state: {current_state}")

            try:
                result = await handler(ctx)

                self.trajectory.log_state_transition(
                    from_state=current_state.value,
                    to_state=result.next_state.value,
                    reason=result.message,
                )

                if self._on_state_change:
                    await self._on_state_change(result.next_state, result.message)

                if result.should_notify_user and self._on_progress:
                    await self._on_progress(result.message)

                current_state = result.next_state
                self.state_store.current_state = current_state
                ctx.iteration += 1

            except Exception as e:
                self.trajectory.log_error(
                    state=current_state.value,
                    action="state_execution",
                    error=str(e),
                )
                raise ExecutionError(f"Error in {current_state.value}: {e}") from e

        return {
            "success": True,
            "state_summary": self.state_store.get_summary(),
            "trajectory_summary": self.trajectory.get_summary(),
        }

    async def _handle_decompose(self, ctx: StateContext) -> StateResult:
        """Decompose research questions into search queries."""
        result = await self.tools.execute(
            "decompose_questions",
            topic=ctx.task.topic,
            questions=ctx.task.questions,
            sections=ctx.task.required_sections,
        )

        if not result.success:
            raise ExecutionError(f"Failed to decompose questions: {result.error}")

        queries = result.data
        ctx.queries = queries

        self.trajectory.log_step(
            state="decompose",
            action="decompose_questions",
            details={
                "question_count": len(ctx.task.questions),
                "query_count": len(queries),
            },
        )

        return StateResult(
            next_state=ResearchState.SEARCH,
            message=f"Decomposed {len(ctx.task.questions)} questions into {len(queries)} queries",
            should_notify_user=True,
        )

    async def _handle_search(self, ctx: StateContext) -> StateResult:
        """Execute search queries and collect sources."""
        if ctx.current_query_index >= len(ctx.queries):
            return StateResult(
                next_state=ResearchState.EVALUATE,
                message="All queries executed, proceeding to evaluation",
            )

        query = ctx.queries[ctx.current_query_index]

        hook_result = await self.lifecycle.run_hooks(
            "pre_search",
            {"query_text": query.query_text}
        )

        if hook_result.result == HookResult.SKIP:
            ctx.current_query_index += 1
            return StateResult(
                next_state=ResearchState.SEARCH,
                message=f"Query skipped (duplicate): {query.query_text[:50]}...",
            )

        if self._on_progress:
            await self._on_progress(f"Searching: {query.query_text[:50]}...")

        result = await self.tools.execute(
            "web_search",
            query=query.query_text,
            max_results=10,
        )

        if result.success and result.data:
            sources = result.data
            source_ids = []

            for source_data in sources:
                existing = self.state_store.evidence_store.get_source_by_url(
                    source_data.get("url", "")
                )
                if existing:
                    source_ids.append(existing.id)
                    continue

                source = Source(
                    id="",
                    url=source_data.get("url", ""),
                    title=source_data.get("title", ""),
                    content=source_data.get("content", ""),
                )
                source_id = self.state_store.evidence_store.add_source(source)
                source_ids.append(source_id)

            self.context.history.add_query(query, len(sources), source_ids)

            self.trajectory.log_query(
                query_id=query.id,
                query_text=query.query_text,
                target_section=query.target_section,
                result_count=len(sources),
                source_ids=source_ids,
                duration_ms=result.execution_time * 1000,
            )

        query.executed = True
        ctx.current_query_index += 1

        if ctx.current_query_index < len(ctx.queries):
            return StateResult(
                next_state=ResearchState.SEARCH,
                message=f"Query {ctx.current_query_index}/{len(ctx.queries)} completed",
            )
        else:
            return StateResult(
                next_state=ResearchState.EVALUATE,
                message=f"All {len(ctx.queries)} queries completed",
                should_notify_user=True,
            )

    async def _handle_evaluate(self, ctx: StateContext) -> StateResult:
        """Evaluate source quality."""
        sources = self.state_store.evidence_store.get_all_sources()
        unevaluated = [s for s in sources if not s.evaluated]

        if not unevaluated:
            return StateResult(
                next_state=ResearchState.EXTRACT,
                message="All sources evaluated",
            )

        if self._on_progress:
            await self._on_progress(f"Evaluating {len(unevaluated)} sources...")

        for source in unevaluated:
            result = await self.tools.execute(
                "evaluate_source",
                url=source.url,
                content=source.content,
            )

            if result.success and result.data:
                eval_data = result.data
                source.reliability = eval_data.get("reliability", source.reliability)
                source.relevance_score = eval_data.get("relevance_score", 0.5)
                source.timeliness_score = eval_data.get("timeliness_score", 0.5)
                source.compute_overall_score()
                source.evaluated = True

                self.trajectory.log_source_evaluation(
                    source_id=source.id,
                    url=source.url,
                    reliability=source.reliability.value if hasattr(source.reliability, 'value') else str(source.reliability),
                    relevance_score=source.relevance_score,
                    timeliness_score=source.timeliness_score,
                    overall_score=source.overall_score,
                )

        hook_result = await self.lifecycle.run_hooks(
            "post_search",
            {"sources": [{"url": s.url, "reliability_score": s.overall_score} for s in sources]}
        )

        return StateResult(
            next_state=ResearchState.EXTRACT,
            message=f"Evaluated {len(unevaluated)} sources",
            should_notify_user=True,
        )

    async def _handle_extract(self, ctx: StateContext) -> StateResult:
        """Extract evidence from sources."""
        sources = self.state_store.evidence_store.get_evaluated_sources()
        high_quality_sources = [s for s in sources if s.overall_score >= 0.5]

        if self._on_progress:
            await self._on_progress(f"Extracting from {len(high_quality_sources)} sources...")

        for source in high_quality_sources:
            existing_evidence = self.state_store.evidence_store.get_evidence_for_source(source.id)
            if existing_evidence:
                continue

            result = await self.tools.execute(
                "extract_facts",
                content=source.content,
                questions=ctx.task.questions,
                sections=ctx.task.required_sections,
            )

            if result.success and result.data:
                facts = result.data
                for fact in facts:
                    evidence = Evidence(
                        id="",
                        source_id=source.id,
                        content=fact.get("content", ""),
                        source_paragraph=fact.get("source_paragraph", ""),
                        target_section=fact.get("target_section", ""),
                        related_questions=fact.get("related_questions", []),
                        confidence=fact.get("confidence", 1.0),
                    )
                    evidence_id = self.state_store.evidence_store.add_evidence(evidence)

                    self.context.evidence.add_evidence(
                        evidence, source, fact.get("relevance_score", 0.7)
                    )

                    self.trajectory.log_evidence_extraction(
                        source_id=source.id,
                        evidence_id=evidence_id,
                        content_preview=evidence.content,
                        target_section=evidence.target_section,
                        confidence=evidence.confidence,
                    )

        return StateResult(
            next_state=ResearchState.ORGANIZE,
            message=f"Extracted evidence from {len(high_quality_sources)} sources",
            should_notify_user=True,
        )

    async def _handle_organize(self, ctx: StateContext) -> StateResult:
        """Organize evidence and detect gaps."""
        gaps: list[GapAnalysis] = []

        for section in ctx.task.required_sections:
            evidence = self.state_store.evidence_store.get_evidence_for_section(section)
            evidence_count = len(evidence)

            if evidence_count < self.evidence_threshold:
                result = await self.tools.execute(
                    "analyze_gap",
                    section=section,
                    evidence=evidence,
                    questions=ctx.task.questions,
                )

                if result.success and result.data:
                    gap_data = result.data
                    gap = GapAnalysis(
                        section_name=section,
                        has_gap=True,
                        missing_topics=gap_data.get("missing_topics", []),
                        current_evidence_count=evidence_count,
                        required_evidence_count=self.evidence_threshold,
                        suggested_queries=gap_data.get("suggested_queries", []),
                    )
                    gaps.append(gap)

                    self.trajectory.log_gap_detection(
                        section_name=section,
                        missing_topics=gap.missing_topics,
                        suggested_queries=gap.suggested_queries,
                        current_evidence_count=evidence_count,
                    )

        if gaps and self.state_store.hop_count < self.max_hops:
            ctx.gap_fill_section = gaps[0].section_name
            return StateResult(
                next_state=ResearchState.GAP_FILL,
                message=f"Found {len(gaps)} gaps, initiating gap fill (hop {self.state_store.hop_count + 1})",
                should_notify_user=True,
            )

        return StateResult(
            next_state=ResearchState.CROSS_VALIDATE,
            message="Evidence organized, proceeding to validation",
        )

    async def _handle_gap_fill(self, ctx: StateContext) -> StateResult:
        """Fill information gaps with additional searches."""
        self.state_store.hop_count += 1

        if self.state_store.hop_count > self.max_hops:
            return StateResult(
                next_state=ResearchState.CROSS_VALIDATE,
                message=f"Max hops ({self.max_hops}) reached, proceeding with available evidence",
                should_notify_user=True,
            )

        result = await self.tools.execute(
            "generate_gap_queries",
            section=ctx.gap_fill_section,
            existing_evidence=self.state_store.evidence_store.get_evidence_for_section(
                ctx.gap_fill_section or ""
            ),
            questions=ctx.task.questions,
        )

        if result.success and result.data:
            new_queries = result.data
            for i, query_data in enumerate(new_queries):
                query = ResearchQuery(
                    id=f"gap_{self.state_store.hop_count}_{i}",
                    original_question_index=-1,
                    query_text=query_data.get("query_text", ""),
                    target_section=ctx.gap_fill_section or "",
                )
                ctx.queries.append(query)

            self.trajectory.log_gap_fill_attempt(
                section_name=ctx.gap_fill_section or "",
                hop_number=self.state_store.hop_count,
                queries_generated=len(new_queries),
            )

            if self._on_progress:
                await self._on_progress(
                    f"Gap fill hop {self.state_store.hop_count}: "
                    f"generated {len(new_queries)} queries for {ctx.gap_fill_section}"
                )

        ctx.current_query_index = len(ctx.queries) - len(result.data) if result.data else len(ctx.queries)

        return StateResult(
            next_state=ResearchState.SEARCH,
            message=f"Gap fill initiated, returning to search",
        )

    async def _handle_cross_validate(self, ctx: StateContext) -> StateResult:
        """Cross-validate key claims."""
        evidence_list = list(self.state_store.evidence_store._evidence.values())

        key_claims = [e for e in evidence_list if e.confidence >= 0.8][:10]

        if self._on_progress:
            await self._on_progress(f"Cross-validating {len(key_claims)} key claims...")

        for evidence in key_claims:
            if evidence.cross_validated:
                continue

            result = await self.tools.execute(
                "cross_validate",
                claim=evidence.content,
                sources=[
                    self.state_store.evidence_store.get_source(e.source_id)
                    for e in evidence_list
                    if e.id != evidence.id and e.target_section == evidence.target_section
                ],
            )

            if result.success and result.data:
                validation = result.data
                evidence.cross_validated = True
                evidence.validation_sources = validation.get("supporting_sources", [])

                self.trajectory.log_cross_validation(
                    claim=evidence.content,
                    is_valid=validation.get("is_valid", True),
                    supporting_sources=validation.get("supporting_sources", []),
                    conflicting_sources=validation.get("conflicting_sources", []),
                )

        return StateResult(
            next_state=ResearchState.DRAFT,
            message=f"Cross-validated {len(key_claims)} claims",
            should_notify_user=True,
        )

    async def _handle_draft(self, ctx: StateContext) -> StateResult:
        """Draft report sections."""
        sections = ctx.task.required_sections

        if ctx.current_section_index >= len(sections):
            return StateResult(
                next_state=ResearchState.CONSISTENCY_CHECK,
                message="All sections drafted",
                should_notify_user=True,
            )

        section_name = sections[ctx.current_section_index]

        evidence_list = self.state_store.evidence_store.get_evidence_for_section(section_name)

        hook_result = await self.lifecycle.run_hooks(
            "pre_draft",
            {
                "section_name": section_name,
                "evidence_count": len(evidence_list),
            }
        )

        if hook_result.result == HookResult.SKIP:
            ctx.current_section_index += 1
            return StateResult(
                next_state=ResearchState.DRAFT,
                message=f"Section {section_name} skipped (insufficient evidence)",
            )

        if self._on_progress:
            await self._on_progress(f"Drafting section: {section_name}")

        sources_for_evidence = []
        for ev in evidence_list:
            source = self.state_store.evidence_store.get_source(ev.source_id)
            if source:
                sources_for_evidence.append(source)

        result = await self.tools.execute(
            "draft_section",
            section=section_name,
            evidence=evidence_list,
            sources=sources_for_evidence,
            outline=ctx.task.constraints.get("expected_outline", {}),
            citation_mapper=self.state_store.citation_mapper,
        )

        if result.success and result.data:
            draft_data = result.data
            content = draft_data.get("content", "")
            evidence_ids = [e.id for e in evidence_list]
            citation_ids = draft_data.get("citation_ids", [])

            self.state_store.draft_manager.update_section(
                section_name, content, evidence_ids, citation_ids
            )

            self.context.outline.update_section(
                self.state_store.draft_manager.get_section(section_name)
            )

            self.trajectory.log_draft(
                section_name=section_name,
                word_count=len(content.split()),
                citation_count=len(citation_ids),
                evidence_count=len(evidence_ids),
            )

        ctx.current_section_index += 1

        return StateResult(
            next_state=ResearchState.DRAFT,
            message=f"Section {section_name} drafted",
            should_notify_user=True,
        )

    async def _handle_consistency_check(self, ctx: StateContext) -> StateResult:
        """Check citation consistency and report integrity."""
        report = self.state_store.draft_manager.generate_report()

        broken_citations = self.state_store.citation_mapper.validate_citations(report)

        if broken_citations:
            self.trajectory.log_step(
                state="consistency_check",
                action="citation_validation",
                details={
                    "broken_citations": broken_citations,
                    "status": "failed",
                },
            )

        hook_result = await self.lifecycle.run_hooks(
            "post_draft",
            {"content": report}
        )

        if hook_result.result == HookResult.RETRY and hook_result.modified_data:
            broken = hook_result.modified_data.get("broken_citations", [])
            if broken:
                if self._on_progress:
                    await self._on_progress(f"Fixing {len(broken)} broken citations...")

        return StateResult(
            next_state=ResearchState.FINALIZE,
            message="Consistency check completed",
            should_notify_user=True,
        )

    async def _handle_finalize(self, ctx: StateContext) -> StateResult:
        """Finalize the report."""
        references = self.state_store.citation_mapper.format_reference_list()

        self.state_store.draft_manager.update_section(
            "参考文献",
            references,
            [],
            [c.id for c in self.state_store.citation_mapper.get_all_citations()],
        )

        final_report = self.state_store.draft_manager.generate_report()

        title = f"# {ctx.task.topic}\n\n"
        final_report = title + final_report

        self.trajectory.log_step(
            state="finalize",
            action="generate_final_report",
            details={
                "total_words": len(final_report.split()),
                "total_citations": self.state_store.citation_mapper.get_citation_count(),
                "total_sources": self.state_store.evidence_store.get_source_count(),
            },
        )

        return StateResult(
            next_state=ResearchState.COMPLETED,
            message="Report finalized",
            should_notify_user=True,
            data={"report": final_report},
        )
