"""
Evaluation - Tracks research trajectory and evaluates progress
"""

import json
import time
from typing import List, Dict, Any, Optional
from pathlib import Path


class Evaluator:
    """
    Handles research trajectory logging and evaluation
    """

    def __init__(self):
        self.trajectory: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def start_session(self) -> None:
        """Start a new research session"""
        self.start_time = time.time()
        self.trajectory = []

    def end_session(self) -> None:
        """End the current research session"""
        self.end_time = time.time()

    def log_step(self, query: str, results_count: int,
                evaluation_result: Dict[str, Any], facts_extracted: int) -> None:
        """
        Log a step in the research trajectory
        """
        step_data = {
            "timestamp": time.time(),
            "query": query,
            "results_count": results_count,
            "evaluation": evaluation_result,
            "facts_extracted": facts_extracted,
            "elapsed_since_start": time.time() - (self.start_time or 0)
        }
        self.trajectory.append(step_data)

    def get_trajectory_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the research trajectory
        """
        if not self.trajectory:
            return {}

        total_steps = len(self.trajectory)
        total_facts = sum(step.get("facts_extracted", 0) for step in self.trajectory)
        total_results = sum(step.get("results_count", 0) for step in self.trajectory)

        return {
            "total_steps": total_steps,
            "total_facts_extracted": total_facts,
            "total_results_collected": total_results,
            "average_results_per_step": total_results / total_steps if total_steps > 0 else 0,
            "average_facts_per_step": total_facts / total_steps if total_steps > 0 else 0,
            "total_duration": self.end_time - self.start_time if self.start_time and self.end_time else None
        }

    def save_trajectory(self, file_path: str) -> None:
        """
        Save the full trajectory to a JSONL file
        """
        with open(file_path, "w") as f:
            for step in self.trajectory:
                json.dump(step, f)
                f.write("\n")

    def evaluate_research_quality(self, sources: List[Dict[str, Any]],
                                facts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate the overall quality of the research
        """
        source_types = defaultdict(int)
        credibility_scores = []

        for source in sources:
            credibility = source.get("credibility", "low")
            source_type = source.get("source_type", "unknown")

            source_types[source_type] += 1

            score_map = {
                "high": 3,
                "medium": 2,
                "low": 1
            }
            credibility_scores.append(score_map.get(credibility, 1))

        avg_credibility = sum(credibility_scores) / len(credibility_scores) if credibility_scores else 0

        return {
            "source_distribution": dict(source_types),
            "average_credibility_score": avg_credibility,
            "sources_count": len(sources),
            "facts_count": len(facts),
            "quality_rating": self._get_quality_rating(avg_credibility, len(sources), len(facts))
        }

    def _get_quality_rating(self, avg_credibility: float, sources_count: int, facts_count: int) -> str:
        """
        Get a qualitative quality rating
        """
        if avg_credibility >= 2.5 and sources_count >= 15 and facts_count >= 50:
            return "excellent"
        elif avg_credibility >= 2.0 and sources_count >= 10 and facts_count >= 30:
            return "good"
        elif avg_credibility >= 1.5 and sources_count >= 5 and facts_count >= 15:
            return "fair"
        else:
            return "poor"
