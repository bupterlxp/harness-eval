import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from .schemas import ResearchState


class EvaluationTrajectory:
    """Tracks and logs the full research trajectory for evaluation"""

    def __init__(self, output_file: Optional[str] = None):
        self.trajectory: List[Dict[str, Any]] = []
        self.output_file = output_file or f"research_trajectory_{datetime.now().isoformat()}.jsonl"

    def log_step(self, step_name: str, data: Dict[str, Any]) -> None:
        """Log a step in the research process"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "step": step_name,
            "data": data
        }
        self.trajectory.append(entry)

        # Write to file immediately for persistence
        if self.output_file:
            with open(self.output_file, 'a', encoding='utf-8') as f:
                json.dump(entry, f, ensure_ascii=False)
                f.write('\n')

    def log_decompose_step(self, original_questions: List[str], decomposed_queries: List[str]) -> None:
        """Log question decomposition step"""
        self.log_step("DECOMPOSE", {
            "original_questions": original_questions,
            "decomposed_queries": decomposed_queries
        })

    def log_search_step(self, query: str, results: List[Dict[str, Any]]) -> None:
        """Log search step"""
        self.log_step("SEARCH", {
            "query": query,
            "results_count": len(results),
            "results": results
        })

    def log_evaluate_step(self, source_url: str, reliability: str, relevance_score: float) -> None:
        """Log source evaluation step"""
        self.log_step("EVALUATE", {
            "source_url": source_url,
            "reliability": reliability,
            "relevance_score": relevance_score
        })

    def log_extract_step(self, source_url: str, facts_extracted: int) -> None:
        """Log fact extraction step"""
        self.log_step("EXTRACT", {
            "source_url": source_url,
            "facts_extracted": facts_extracted
        })

    def log_organize_step(self, section_title: str, evidence_count: int) -> None:
        """Log evidence organization step"""
        self.log_step("ORGANIZE", {
            "section_title": section_title,
            "evidence_count": evidence_count
        })

    def log_gap_fill_step(self, gap: str, new_queries: List[str]) -> None:
        """Log gap filling step"""
        self.log_step("GAP_FILL", {
            "gap": gap,
            "new_queries": new_queries
        })

    def log_cross_validate_step(self, claim: str, sources_used: List[str]) -> None:
        """Log cross validation step"""
        self.log_step("CROSS_VALIDATE", {
            "claim": claim,
            "sources_used": sources_used
        })

    def log_draft_step(self, section_title: str, content_length: int) -> None:
        """Log draft step"""
        self.log_step("DRAFT", {
            "section_title": section_title,
            "content_length": content_length
        })

    def log_consistency_check_step(self, errors: List[str], warnings: List[str]) -> None:
        """Log consistency check step"""
        self.log_step("CONSISTENCY_CHECK", {
            "errors": errors,
            "warnings": warnings
        })

    def log_finalize_step(self, total_sources: int, total_sections: int) -> None:
        """Log finalize step"""
        self.log_step("FINALIZE", {
            "total_sources": total_sources,
            "total_sections": total_sections
        })

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of the trajectory"""
        step_counts = {}
        total_facts = 0

        for entry in self.trajectory:
            step = entry["step"]
            step_counts[step] = step_counts.get(step, 0) + 1

            # Count facts extracted
            if step == "EXTRACT":
                total_facts += entry["data"].get("facts_extracted", 0)

        return {
            "total_steps": len(self.trajectory),
            "steps_by_type": step_counts,
            "total_facts_extracted": total_facts,
            "total_sources": next((e["data"]["total_sources"] for e in self.trajectory if e["step"] == "FINALIZE"), 0),
            "total_sections": next((e["data"]["total_sections"] for e in self.trajectory if e["step"] == "FINALIZE"), 0)
        }

    def print_summary(self) -> None:
        """Print human-readable summary"""
        summary = self.get_summary()
        print("\n=== Research Trajectory Summary ===")
        print(f"Total steps: {summary['total_steps']}")
        print(f"Total facts extracted: {summary['total_facts_extracted']}")
        print(f"Total sources used: {summary['total_sources']}")
        print(f"Total sections completed: {summary['total_sections']}")
        print("\nSteps breakdown:")
        for step, count in summary['steps_by_type'].items():
            print(f"  {step}: {count} times")

    def clear(self) -> None:
        """Clear trajectory data"""
        self.trajectory = []
        if os.path.exists(self.output_file):
            os.remove(self.output_file)