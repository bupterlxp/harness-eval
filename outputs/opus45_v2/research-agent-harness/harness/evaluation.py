"""Evaluation (V) - Research trajectory recording in JSONL format."""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from enum import Enum


class StepType(Enum):
    QUERY_DECOMPOSITION = "query_decomposition"
    SEARCH = "search"
    CONTENT_EXTRACTION = "content_extraction"
    SOURCE_EVALUATION = "source_evaluation"
    FACT_EXTRACTION = "fact_extraction"
    CROSS_VALIDATION = "cross_validation"
    SECTION_DRAFTING = "section_drafting"
    CITATION_CHECK = "citation_check"
    HOP_TRANSITION = "hop_transition"
    CONVERGENCE_CHECK = "convergence_check"
    REPORT_GENERATION = "report_generation"
    ERROR = "error"


class TrajectoryRecorder:
    """Records research trajectory steps in JSONL format."""

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._step_counter = 0
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    @property
    def step_count(self) -> int:
        return self._step_counter

    def record_step(
        self,
        step_type: StepType,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a single step in the research trajectory."""
        self._step_counter += 1

        entry = {
            "step_number": self._step_counter,
            "timestamp": datetime.now().isoformat(),
            "session_id": self._session_id,
            "step_type": step_type.value,
            "data": data,
            "metadata": metadata or {},
        }

        with open(self.output_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return entry

    def record_search(
        self,
        query: str,
        sources_returned: int,
        source_types: dict[str, int],
        new_sources: int = 0,
        deduplicated: int = 0,
    ) -> dict[str, Any]:
        """Record a search step."""
        return self.record_step(
            StepType.SEARCH,
            {
                "query": query,
                "sources_returned": sources_returned,
                "source_types": source_types,
                "new_sources": new_sources,
                "deduplicated": deduplicated,
            },
        )

    def record_evaluation(
        self,
        url: str,
        credibility: str,
        source_type: str,
        relevance_score: float,
        timeliness_score: float,
    ) -> dict[str, Any]:
        """Record a source evaluation step."""
        return self.record_step(
            StepType.SOURCE_EVALUATION,
            {
                "url": url,
                "credibility": credibility,
                "source_type": source_type,
                "relevance_score": relevance_score,
                "timeliness_score": timeliness_score,
            },
        )

    def record_extraction(
        self,
        url: str,
        facts_extracted: int,
        content_length: int,
    ) -> dict[str, Any]:
        """Record a fact extraction step."""
        return self.record_step(
            StepType.FACT_EXTRACTION,
            {
                "url": url,
                "facts_extracted": facts_extracted,
                "content_length": content_length,
            },
        )

    def record_cross_validation(
        self,
        fact_id: int,
        fact_content: str,
        verified_by: list[int],
        contradicted_by: list[int],
    ) -> dict[str, Any]:
        """Record a cross-validation check."""
        return self.record_step(
            StepType.CROSS_VALIDATION,
            {
                "fact_id": fact_id,
                "fact_content": fact_content[:200],
                "verified_by": verified_by,
                "contradicted_by": contradicted_by,
                "verification_count": len(verified_by),
                "contradiction_count": len(contradicted_by),
            },
        )

    def record_hop(
        self,
        hop_number: int,
        reason: str,
        new_queries: list[str],
        sources_before: int,
        facts_before: int,
    ) -> dict[str, Any]:
        """Record a multi-hop transition."""
        return self.record_step(
            StepType.HOP_TRANSITION,
            {
                "hop_number": hop_number,
                "reason": reason,
                "new_queries": new_queries,
                "sources_before": sources_before,
                "facts_before": facts_before,
            },
        )

    def record_convergence(
        self,
        converged: bool,
        reason: str,
        total_sources: int,
        total_facts: int,
        gaps_remaining: list[str],
    ) -> dict[str, Any]:
        """Record a convergence check."""
        return self.record_step(
            StepType.CONVERGENCE_CHECK,
            {
                "converged": converged,
                "reason": reason,
                "total_sources": total_sources,
                "total_facts": total_facts,
                "gaps_remaining": gaps_remaining,
            },
        )

    def record_section_draft(
        self,
        section_name: str,
        citations_used: list[int],
        word_count: int,
    ) -> dict[str, Any]:
        """Record section drafting."""
        return self.record_step(
            StepType.SECTION_DRAFTING,
            {
                "section_name": section_name,
                "citations_used": citations_used,
                "citation_count": len(citations_used),
                "word_count": word_count,
            },
        )

    def record_citation_check(
        self,
        total_citations: int,
        orphaned: int,
        unused: int,
        valid: bool,
    ) -> dict[str, Any]:
        """Record citation integrity check."""
        return self.record_step(
            StepType.CITATION_CHECK,
            {
                "total_citations": total_citations,
                "orphaned": orphaned,
                "unused": unused,
                "valid": valid,
            },
        )

    def record_query_decomposition(
        self,
        original_query: str,
        sub_queries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Record query decomposition."""
        return self.record_step(
            StepType.QUERY_DECOMPOSITION,
            {
                "original_query": original_query,
                "sub_queries": sub_queries,
                "sub_query_count": len(sub_queries),
            },
        )

    def record_error(
        self,
        error_type: str,
        error_message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record an error."""
        return self.record_step(
            StepType.ERROR,
            {
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {},
            },
        )

    def record_report_generation(
        self,
        sections: list[str],
        total_citations: int,
        word_count: int,
        sources_used: int,
    ) -> dict[str, Any]:
        """Record final report generation."""
        return self.record_step(
            StepType.REPORT_GENERATION,
            {
                "sections": sections,
                "total_citations": total_citations,
                "word_count": word_count,
                "sources_used": sources_used,
            },
        )

    def get_trajectory_summary(self) -> dict[str, Any]:
        """Generate a summary of the recorded trajectory."""
        if not self.output_path.exists():
            return {"total_steps": 0, "step_types": {}}

        step_types: dict[str, int] = {}
        total_sources = 0
        total_facts = 0
        total_searches = 0

        with open(self.output_path) as f:
            for line in f:
                entry = json.loads(line)
                step_type = entry.get("step_type", "unknown")
                step_types[step_type] = step_types.get(step_type, 0) + 1

                if step_type == "search":
                    total_searches += 1
                    total_sources += entry.get("data", {}).get("sources_returned", 0)
                elif step_type == "fact_extraction":
                    total_facts += entry.get("data", {}).get("facts_extracted", 0)

        return {
            "total_steps": self._step_counter,
            "step_types": step_types,
            "total_searches": total_searches,
            "total_sources_found": total_sources,
            "total_facts_extracted": total_facts,
        }

    def load_trajectory(self) -> list[dict[str, Any]]:
        """Load the full trajectory from file."""
        if not self.output_path.exists():
            return []

        entries = []
        with open(self.output_path) as f:
            for line in f:
                entries.append(json.loads(line))
        return entries
