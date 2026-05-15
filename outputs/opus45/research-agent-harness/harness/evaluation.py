"""Evaluation Interface (V) - JSONL trajectory logging for traceability.

Records every step of the research process:
- Queries executed and results
- Source evaluations
- Evidence extractions
- Citation relationships
- Draft iterations
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import threading


@dataclass
class TrajectoryStep:
    """A single step in the research trajectory."""
    step_id: int
    timestamp: datetime
    state: str
    action: str
    details: dict[str, Any]
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    query_id: Optional[str] = None
    duration_ms: Optional[float] = None
    success: bool = True
    error: Optional[str] = None

    def to_jsonl(self) -> str:
        """Convert to JSONL format."""
        data = {
            "step_id": self.step_id,
            "timestamp": self.timestamp.isoformat(),
            "state": self.state,
            "action": self.action,
            "details": self.details,
            "source_ids": self.source_ids,
            "evidence_ids": self.evidence_ids,
            "query_id": self.query_id,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
        }
        return json.dumps(data, ensure_ascii=False)


class TrajectoryLogger:
    """JSONL trajectory logger for research process traceability."""

    def __init__(self, output_path: Optional[Path] = None) -> None:
        self._steps: list[TrajectoryStep] = []
        self._step_counter = 0
        self._output_path = output_path
        self._lock = threading.Lock()
        self._file_handle = None

        if output_path:
            self._file_handle = open(output_path, "a", encoding="utf-8")

    def __del__(self) -> None:
        """Close file handle on destruction."""
        if self._file_handle:
            self._file_handle.close()

    def log_step(
        self,
        state: str,
        action: str,
        details: dict[str, Any],
        source_ids: Optional[list[str]] = None,
        evidence_ids: Optional[list[str]] = None,
        query_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> TrajectoryStep:
        """Log a trajectory step."""
        with self._lock:
            self._step_counter += 1
            step = TrajectoryStep(
                step_id=self._step_counter,
                timestamp=datetime.now(),
                state=state,
                action=action,
                details=details,
                source_ids=source_ids or [],
                evidence_ids=evidence_ids or [],
                query_id=query_id,
                duration_ms=duration_ms,
                success=success,
                error=error,
            )
            self._steps.append(step)

            if self._file_handle:
                self._file_handle.write(step.to_jsonl() + "\n")
                self._file_handle.flush()

            return step

    def log_query(
        self,
        query_id: str,
        query_text: str,
        target_section: str,
        result_count: int,
        source_ids: list[str],
        duration_ms: float,
    ) -> TrajectoryStep:
        """Log a search query execution."""
        return self.log_step(
            state="search",
            action="execute_query",
            details={
                "query_text": query_text,
                "target_section": target_section,
                "result_count": result_count,
            },
            source_ids=source_ids,
            query_id=query_id,
            duration_ms=duration_ms,
        )

    def log_source_evaluation(
        self,
        source_id: str,
        url: str,
        reliability: str,
        relevance_score: float,
        timeliness_score: float,
        overall_score: float,
    ) -> TrajectoryStep:
        """Log a source evaluation."""
        return self.log_step(
            state="evaluate",
            action="evaluate_source",
            details={
                "url": url,
                "reliability": reliability,
                "relevance_score": relevance_score,
                "timeliness_score": timeliness_score,
                "overall_score": overall_score,
            },
            source_ids=[source_id],
        )

    def log_evidence_extraction(
        self,
        source_id: str,
        evidence_id: str,
        content_preview: str,
        target_section: str,
        confidence: float,
    ) -> TrajectoryStep:
        """Log evidence extraction from a source."""
        return self.log_step(
            state="extract",
            action="extract_evidence",
            details={
                "content_preview": content_preview[:200],
                "target_section": target_section,
                "confidence": confidence,
            },
            source_ids=[source_id],
            evidence_ids=[evidence_id],
        )

    def log_gap_detection(
        self,
        section_name: str,
        missing_topics: list[str],
        suggested_queries: list[str],
        current_evidence_count: int,
    ) -> TrajectoryStep:
        """Log gap detection in a section."""
        return self.log_step(
            state="organize",
            action="detect_gap",
            details={
                "section_name": section_name,
                "missing_topics": missing_topics,
                "suggested_queries": suggested_queries,
                "current_evidence_count": current_evidence_count,
            },
        )

    def log_gap_fill_attempt(
        self,
        section_name: str,
        hop_number: int,
        queries_generated: int,
    ) -> TrajectoryStep:
        """Log a gap fill attempt (multi-hop search)."""
        return self.log_step(
            state="gap_fill",
            action="initiate_gap_fill",
            details={
                "section_name": section_name,
                "hop_number": hop_number,
                "queries_generated": queries_generated,
            },
        )

    def log_cross_validation(
        self,
        claim: str,
        is_valid: bool,
        supporting_sources: list[str],
        conflicting_sources: list[str],
    ) -> TrajectoryStep:
        """Log cross-validation of a claim."""
        return self.log_step(
            state="cross_validate",
            action="validate_claim",
            details={
                "claim": claim[:200],
                "is_valid": is_valid,
                "supporting_count": len(supporting_sources),
                "conflicting_count": len(conflicting_sources),
            },
            source_ids=supporting_sources + conflicting_sources,
        )

    def log_draft(
        self,
        section_name: str,
        word_count: int,
        citation_count: int,
        evidence_count: int,
    ) -> TrajectoryStep:
        """Log section draft creation."""
        return self.log_step(
            state="draft",
            action="create_draft",
            details={
                "section_name": section_name,
                "word_count": word_count,
                "citation_count": citation_count,
                "evidence_count": evidence_count,
            },
        )

    def log_citation_mapping(
        self,
        source_id: str,
        citation_number: int,
        formatted_citation: str,
    ) -> TrajectoryStep:
        """Log citation creation."""
        return self.log_step(
            state="draft",
            action="create_citation",
            details={
                "citation_number": citation_number,
                "formatted_citation": formatted_citation,
            },
            source_ids=[source_id],
        )

    def log_state_transition(
        self,
        from_state: str,
        to_state: str,
        reason: str,
    ) -> TrajectoryStep:
        """Log state machine transition."""
        return self.log_step(
            state=to_state,
            action="state_transition",
            details={
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
            },
        )

    def log_error(
        self,
        state: str,
        action: str,
        error: str,
        details: Optional[dict[str, Any]] = None,
    ) -> TrajectoryStep:
        """Log an error."""
        return self.log_step(
            state=state,
            action=action,
            details=details or {},
            success=False,
            error=error,
        )

    def get_trajectory(self) -> list[TrajectoryStep]:
        """Get all trajectory steps."""
        return self._steps.copy()

    def get_trajectory_jsonl(self) -> str:
        """Get entire trajectory as JSONL string."""
        return "\n".join(step.to_jsonl() for step in self._steps)

    def get_source_trace(self, source_id: str) -> list[TrajectoryStep]:
        """Get all steps involving a source."""
        return [step for step in self._steps if source_id in step.source_ids]

    def get_evidence_trace(self, evidence_id: str) -> list[TrajectoryStep]:
        """Get all steps involving evidence."""
        return [step for step in self._steps if evidence_id in step.evidence_ids]

    def get_state_timeline(self) -> list[dict]:
        """Get timeline of state transitions."""
        transitions = [
            step for step in self._steps
            if step.action == "state_transition"
        ]
        return [
            {
                "timestamp": t.timestamp.isoformat(),
                "from": t.details.get("from_state"),
                "to": t.details.get("to_state"),
                "reason": t.details.get("reason"),
            }
            for t in transitions
        ]

    def get_summary(self) -> dict:
        """Get trajectory summary statistics."""
        action_counts: dict[str, int] = {}
        state_counts: dict[str, int] = {}
        error_count = 0

        for step in self._steps:
            action_counts[step.action] = action_counts.get(step.action, 0) + 1
            state_counts[step.state] = state_counts.get(step.state, 0) + 1
            if not step.success:
                error_count += 1

        return {
            "total_steps": len(self._steps),
            "action_counts": action_counts,
            "state_counts": state_counts,
            "error_count": error_count,
            "unique_sources": len(set(
                sid for step in self._steps for sid in step.source_ids
            )),
            "unique_evidence": len(set(
                eid for step in self._steps for eid in step.evidence_ids
            )),
        }

    def close(self) -> None:
        """Close the trajectory logger."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
