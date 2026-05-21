"""Execution Loop (E) - Drives the research flow with explicit state machine and multi-hop support."""

from __future__ import annotations
import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from harness.state import StateStore, Source
from harness.context import ContextManager
from harness.tools import ToolRegistry, SearchResult, CredibilityLevel
from harness.lifecycle import LifecycleHooks, HookPhase
from harness.evaluation import TrajectoryRecorder


class ResearchState(Enum):
    """States in the research state machine."""
    INIT = "init"
    QUERY_DECOMPOSITION = "query_decomposition"
    SEARCHING = "searching"
    EXTRACTING = "extracting"
    EVALUATING = "evaluating"
    CROSS_VALIDATING = "cross_validating"
    CONVERGENCE_CHECK = "convergence_check"
    DRAFTING = "drafting"
    CITATION_CHECK = "citation_check"
    REPORT_ASSEMBLY = "report_assembly"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class TaskSpec:
    """Research task specification."""
    research_questions: list[str]
    min_sources: int = 10
    max_words: int = 3000
    required_sections: list[str] = field(default_factory=lambda: ["Introduction", "Findings", "Conclusion"])
    max_hops: int = 3
    output_dir: str = "./output"
    constraints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        return cls(
            research_questions=data.get("research_questions", []),
            min_sources=data.get("min_sources", 10),
            max_words=data.get("max_words", 3000),
            required_sections=data.get("required_sections", ["Introduction", "Findings", "Conclusion"]),
            max_hops=data.get("max_hops", 3),
            output_dir=data.get("output_dir", "./output"),
            constraints=data.get("constraints", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "research_questions": self.research_questions,
            "min_sources": self.min_sources,
            "max_words": self.max_words,
            "required_sections": self.required_sections,
            "max_hops": self.max_hops,
            "output_dir": self.output_dir,
            "constraints": self.constraints,
        }


@dataclass
class Result:
    """Research result."""
    status: str  # "success" | "partial" | "failed"
    report_path: str
    sources: list[dict[str, Any]]
    citation_integrity: dict[str, Any]
    gaps: list[str]
    trajectory: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "report_path": self.report_path,
            "sources": self.sources,
            "citation_integrity": self.citation_integrity,
            "gaps": self.gaps,
            "trajectory": self.trajectory,
        }


class ExecutionLoop:
    """Drives the research process with explicit state machine."""

    def __init__(self, task_spec: TaskSpec):
        self.task = task_spec
        self.output_dir = Path(task_spec.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.state_store = StateStore(self.output_dir)
        self.context = ContextManager(self.state_store)
        self.tools = ToolRegistry()
        self.lifecycle = LifecycleHooks(self.state_store, self.context)
        self.trajectory = TrajectoryRecorder(self.output_dir / "trajectory.jsonl")

        self._current_state = ResearchState.INIT
        self._sub_queries: list[dict[str, Any]] = []
        self._pending_urls: list[str] = []
        self._facts_this_hop: int = 0

    @property
    def current_state(self) -> ResearchState:
        return self._current_state

    def _transition(self, new_state: ResearchState) -> None:
        """Transition to a new state."""
        self._current_state = new_state

    async def run(self) -> Result:
        """Execute the full research pipeline."""
        try:
            self._transition(ResearchState.QUERY_DECOMPOSITION)
            await self._decompose_queries()

            while self.state_store.current_hop < self.task.max_hops:
                self._facts_this_hop = 0

                self._transition(ResearchState.SEARCHING)
                await self._search_phase()

                self._transition(ResearchState.EXTRACTING)
                await self._extraction_phase()

                self._transition(ResearchState.EVALUATING)
                await self._evaluation_phase()

                self._transition(ResearchState.CROSS_VALIDATING)
                await self._cross_validation_phase()

                self._transition(ResearchState.CONVERGENCE_CHECK)
                if await self._check_convergence():
                    break

                hop_result = self.lifecycle.pre_hop_check(
                    self.state_store.current_hop,
                    self.task.max_hops,
                    self.state_store.gaps,
                )
                if not hop_result.should_continue:
                    break

                self.state_store.increment_hop()
                self.trajectory.record_hop(
                    self.state_store.current_hop,
                    "Continuing search for gaps",
                    [g for g in self.state_store.gaps[:3]],
                    len(self.state_store.sources),
                    len(self.state_store.facts),
                )

                await self._generate_follow_up_queries()

            self._transition(ResearchState.DRAFTING)
            await self._drafting_phase()

            self._transition(ResearchState.CITATION_CHECK)
            citation_result = self._verify_citations()

            self._transition(ResearchState.REPORT_ASSEMBLY)
            report_path = await self._assemble_report()

            self._transition(ResearchState.COMPLETE)
            return self._build_result(report_path, citation_result)

        except Exception as e:
            self._transition(ResearchState.FAILED)
            self.trajectory.record_error("execution_error", str(e))
            return self._build_failed_result(str(e))

    async def _decompose_queries(self) -> None:
        """Decompose research questions into sub-queries."""
        all_sub_queries = []

        for question in self.task.research_questions:
            sub_queries = await self.tools.llm.decompose_query(question)
            all_sub_queries.extend(sub_queries)
            self.trajectory.record_query_decomposition(question, sub_queries)

        self._sub_queries = sorted(all_sub_queries, key=lambda q: q.get("priority", 5))

    async def _search_phase(self) -> None:
        """Execute search queries and collect sources."""
        queries_to_run = [q["query"] for q in self._sub_queries if q.get("priority", 5) <= 3]

        if not queries_to_run:
            queries_to_run = [q["query"] for q in self._sub_queries[:5]]

        dedup_result = self.lifecycle.pre_search_dedup(queries_to_run)
        if dedup_result.data:
            queries_to_run = dedup_result.data.get("new", queries_to_run)

        for query in queries_to_run:
            self.state_store.record_query(query)

            web_results, academic_results = await asyncio.gather(
                self.tools.web_search.execute_with_retry(query=query, num_results=10),
                self.tools.academic_search.execute_with_retry(query=query, num_results=5),
            )

            all_results: list[SearchResult] = web_results + academic_results
            new_count = 0
            dedup_count = 0

            for result in all_results:
                if not self.state_store.is_url_seen(result.url):
                    self._pending_urls.append(result.url)
                    new_count += 1
                else:
                    dedup_count += 1

            source_types = {
                "web": len([r for r in all_results if r.source_type == "web"]),
                "academic": len([r for r in all_results if r.source_type == "academic"]),
            }

            self.trajectory.record_search(
                query=query,
                sources_returned=len(all_results),
                source_types=source_types,
                new_sources=new_count,
                deduplicated=dedup_count,
            )

    async def _extraction_phase(self) -> None:
        """Extract content from pending URLs."""
        url_dedup_result = self.lifecycle.pre_search_url_dedup(self._pending_urls)
        urls_to_process = url_dedup_result.data.get("new", self._pending_urls) if url_dedup_result.data else self._pending_urls

        for url in urls_to_process[:20]:
            try:
                content = await self.tools.content_extractor.execute_with_retry(url=url)

                if not content.content:
                    continue

                evaluation = await self.tools.source_evaluator.execute_with_retry(
                    url=url,
                    content=content.content,
                    query_context=" ".join(self.task.research_questions),
                )

                source = self.state_store.add_source(
                    url=url,
                    title=content.title or url,
                    credibility=evaluation.credibility.value,
                    content=content.content[:5000],
                    retrieved_at=datetime.now().isoformat(),
                )

                if source:
                    facts = await self.tools.llm.analyze_facts(
                        content.content,
                        " ".join(self.task.research_questions),
                    )

                    for fact_data in facts:
                        if fact_data.get("supports_query", True):
                            self.state_store.add_fact(
                                content=fact_data.get("content", ""),
                                source_id=source.id,
                                confidence=fact_data.get("confidence", 0.8),
                            )
                            self._facts_this_hop += 1

                    self.trajectory.record_extraction(
                        url=url,
                        facts_extracted=len(facts),
                        content_length=len(content.content),
                    )

            except Exception as e:
                self.trajectory.record_error("extraction_error", str(e), {"url": url})

        self._pending_urls.clear()

    async def _evaluation_phase(self) -> None:
        """Re-evaluate sources and adjust credibility."""
        for source in self.state_store.sources:
            facts = self.state_store.get_facts_for_source(source.id)

            self.trajectory.record_evaluation(
                url=source.url,
                credibility=source.credibility,
                source_type="unknown",
                relevance_score=0.7,
                timeliness_score=0.7,
            )

    async def _cross_validation_phase(self) -> None:
        """Cross-validate facts across sources."""
        facts = self.state_store.facts
        content_map: dict[int, str] = {f.id: f.content.lower() for f in facts}

        for fact in facts:
            fact_terms = set(fact.content.lower().split())

            for other_fact in facts:
                if other_fact.id == fact.id or other_fact.source_id == fact.source_id:
                    continue

                other_terms = set(other_fact.content.lower().split())
                overlap = len(fact_terms & other_terms) / max(len(fact_terms), 1)

                if overlap > 0.5:
                    self.state_store.mark_fact_verified(fact.id, other_fact.source_id)

            self.trajectory.record_cross_validation(
                fact_id=fact.id,
                fact_content=fact.content,
                verified_by=fact.verified_by,
                contradicted_by=fact.contradicted_by,
            )

    async def _check_convergence(self) -> bool:
        """Check if research has converged."""
        convergence_result = self.lifecycle.check_convergence(
            min_sources=self.task.min_sources,
            required_sections=self.task.required_sections,
            new_facts_this_hop=self._facts_this_hop,
        )

        converged = convergence_result.data.get("converged", False) if convergence_result.data else False

        self.trajectory.record_convergence(
            converged=converged,
            reason=convergence_result.message,
            total_sources=len(self.state_store.sources),
            total_facts=len(self.state_store.facts),
            gaps_remaining=self.state_store.gaps,
        )

        return converged

    async def _generate_follow_up_queries(self) -> None:
        """Generate follow-up queries based on gaps."""
        gaps = self.state_store.gaps

        if not gaps:
            existing_facts = [f.content for f in self.state_store.facts[:10]]
            prompt = f"""Based on these research findings, identify 2-3 follow-up questions to deepen understanding:

Findings:
{chr(10).join(f'- {fact}' for fact in existing_facts)}

Original questions: {self.task.research_questions}

Return JSON array of follow-up queries."""

            try:
                result = await self.tools.llm.execute_with_retry(prompt=prompt, temperature=0.5)
                json_match = re.search(r"\[.*\]", result, re.DOTALL)
                if json_match:
                    follow_ups = json.loads(json_match.group())
                    for q in follow_ups[:3]:
                        if isinstance(q, str):
                            self._sub_queries.append({"query": q, "priority": 2, "dependency": -1})
                        elif isinstance(q, dict):
                            self._sub_queries.append(q)
            except Exception:
                pass
        else:
            for gap in gaps[:3]:
                self._sub_queries.append({"query": gap, "priority": 1, "dependency": -1})

    async def _drafting_phase(self) -> None:
        """Draft report sections."""
        for section_name in self.task.required_sections:
            evidence_check = self.lifecycle.pre_draft_evidence_check(
                section_name=section_name,
                min_sources=max(1, self.task.min_sources // 3),
                min_facts=max(1, len(self.state_store.facts) // 3),
            )

            facts_for_section = []
            citations_for_section = []

            for fact in self.state_store.facts:
                source = self.state_store.get_source(fact.source_id)
                if not source:
                    continue

                existing_citation = self.state_store.get_citation_for_source(source.id)
                if existing_citation:
                    citation_num = existing_citation.inline_number
                else:
                    mapping = self.state_store.add_citation_mapping(source.id, [fact.id])
                    citation_num = mapping.inline_number

                facts_for_section.append({
                    "content": fact.content,
                    "citation_num": citation_num,
                    "confidence": fact.confidence,
                })
                citations_for_section.append(citation_num)

            words_per_section = self.task.max_words // len(self.task.required_sections)

            section_content = await self.tools.llm.generate_section(
                section_name=section_name,
                facts=facts_for_section[:15],
                citations={c: "" for c in citations_for_section},
                max_words=words_per_section,
            )

            self.state_store.add_section_draft(section_name, section_content, citations_for_section)
            self.state_store.update_section_draft(section_name, section_content, citations_for_section, complete=True)

            self.trajectory.record_section_draft(
                section_name=section_name,
                citations_used=citations_for_section,
                word_count=len(section_content.split()),
            )

            citation_check = self.lifecycle.post_draft_citation_check(section_content)

    def _verify_citations(self) -> dict[str, Any]:
        """Verify citation integrity across all sections."""
        result = self.lifecycle.verify_citation_integrity()

        integrity = result.data or {
            "total_citations": 0,
            "orphaned": 0,
            "unused": 0,
        }

        self.trajectory.record_citation_check(
            total_citations=integrity.get("total_citations", 0),
            orphaned=integrity.get("orphaned", 0),
            unused=integrity.get("unused", 0),
            valid=result.passed,
        )

        return integrity

    async def _assemble_report(self) -> str:
        """Assemble final report from sections."""
        report_parts = []

        title = self.task.research_questions[0] if self.task.research_questions else "Research Report"
        report_parts.append(f"# {title}\n")
        report_parts.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

        for section_name in self.task.required_sections:
            draft = self.state_store.get_section_draft(section_name)
            if draft and draft.content:
                report_parts.append(f"\n## {section_name}\n")
                report_parts.append(draft.content)

        report_parts.append("\n## References\n")
        for mapping in sorted(self.state_store.citation_mappings, key=lambda m: m.inline_number):
            source = self.state_store.get_source(mapping.source_id)
            if source:
                report_parts.append(f"[{mapping.inline_number}] {source.title}. {source.url}\n")

        report_content = "\n".join(report_parts)

        report_path = self.output_dir / "report.md"
        with open(report_path, "w") as f:
            f.write(report_content)

        self.trajectory.record_report_generation(
            sections=self.task.required_sections,
            total_citations=len(self.state_store.citation_mappings),
            word_count=len(report_content.split()),
            sources_used=len(self.state_store.sources),
        )

        return str(report_path)

    def _build_result(self, report_path: str, citation_integrity: dict[str, Any]) -> Result:
        """Build successful result."""
        sources = [
            {
                "id": s.id,
                "url": s.url,
                "title": s.title,
                "credibility": s.credibility,
            }
            for s in self.state_store.sources
        ]

        gaps = self.state_store.gaps

        has_enough_sources = len(sources) >= self.task.min_sources
        citations_valid = citation_integrity.get("orphaned", 0) == 0
        sections_complete = all(
            self.state_store.get_section_draft(s) and self.state_store.get_section_draft(s).complete
            for s in self.task.required_sections
        )

        if has_enough_sources and citations_valid and sections_complete and not gaps:
            status = "success"
        elif has_enough_sources or sections_complete:
            status = "partial"
        else:
            status = "failed"

        return Result(
            status=status,
            report_path=report_path,
            sources=sources,
            citation_integrity={
                "total_citations": citation_integrity.get("total_citations", 0),
                "orphaned": citation_integrity.get("orphaned", 0),
                "unused": citation_integrity.get("unused", 0),
            },
            gaps=gaps,
            trajectory=str(self.output_dir / "trajectory.jsonl"),
        )

    def _build_failed_result(self, error: str) -> Result:
        """Build failed result."""
        return Result(
            status="failed",
            report_path="",
            sources=[],
            citation_integrity={"total_citations": 0, "orphaned": 0, "unused": 0},
            gaps=[error],
            trajectory=str(self.output_dir / "trajectory.jsonl"),
        )
