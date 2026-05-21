"""Evaluation component - tracks and logs writing workflow trajectory"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class EvaluationEvent:
    """Represents a single evaluation event in the workflow trajectory"""
    event_type: str
    timestamp: str
    execution_state: Dict[str, Any]
    data: Dict[str, Any]
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def create(cls, event_type: str, execution_state: Dict[str, Any], data: Dict[str, Any],
               success: bool = True, error: Optional[str] = None) -> "EvaluationEvent":
        return cls(
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            execution_state=execution_state,
            data=data,
            success=success,
            error=error
        )


class EvaluationLogger:
    """Logs and tracks the entire writing workflow trajectory"""

    def __init__(self, output_dir: str = "./output/"):
        self.output_dir = Path(output_dir)
        self.trajectory_file = self.output_dir / "trajectory.jsonl"
        self.events: List[EvaluationEvent] = []
        self._initialize_file()

    def _initialize_file(self) -> None:
        """Initialize the trajectory file if it doesn't exist"""
        if not self.trajectory_file.exists():
            with open(self.trajectory_file, "w") as f:
                pass  # Just create the file

    def log_event(self, event_type: str, execution_state: Dict[str, Any], data: Dict[str, Any],
                  success: bool = True, error: Optional[str] = None) -> None:
        """Log a single evaluation event"""
        event = EvaluationEvent.create(
            event_type=event_type,
            execution_state=execution_state,
            data=data,
            success=success,
            error=error
        )

        self.events.append(event)
        self._write_event(event)

    def _write_event(self, event: EvaluationEvent) -> None:
        """Write a single event to the trajectory file"""
        event_dict = asdict(event)
        with open(self.trajectory_file, "a") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False) + "\n")

    # Convenience logging methods
    def log_workflow_started(self, task_spec: Dict[str, Any]) -> None:
        """Log workflow start event"""
        self.log_event(
            event_type="workflow_started",
            execution_state={},
            data={"task_spec": task_spec}
        )

    def log_outline_generated(self, outline: Dict[str, Any], beats_count: int, scenes_count: int) -> None:
        """Log outline generation completion"""
        self.log_event(
            event_type="outline_generated",
            execution_state={"beats_count": beats_count, "scenes_count": scenes_count},
            data={"outline": outline}
        )

    def log_scene_generated(self, scene_id: int, scene_summary: str, word_count: int,
                            total_words: int) -> None:
        """Log scene generation completion"""
        self.log_event(
            event_type="scene_generated",
            execution_state={"scene_id": scene_id, "word_count": word_count, "total_words": total_words},
            data={"scene_summary": scene_summary}
        )

    def log_consistency_checked(self, scene_id: int, issues: List[str]) -> None:
        """Log consistency check results"""
        self.log_event(
            event_type="consistency_checked",
            execution_state={"scene_id": scene_id, "issues_count": len(issues)},
            data={"issues": issues}
        )

    def log_scene_revised(self, scene_id: int, revision_count: int, original_word_count: int,
                         revised_word_count: int) -> None:
        """Log scene revision completion"""
        self.log_event(
            event_type="scene_revised",
            execution_state={"scene_id": scene_id, "revision_count": revision_count},
            data={
                "original_word_count": original_word_count,
                "revised_word_count": revised_word_count
            }
        )

    def log_manuscript_completed(self, total_words: int, manuscript_path: str) -> None:
        """Log manuscript completion"""
        self.log_event(
            event_type="manuscript_completed",
            execution_state={"total_words": total_words},
            data={"manuscript_path": manuscript_path}
        )

    def log_workflow_completed(self, status: str, total_words: int, consistency_issues: int) -> None:
        """Log workflow completion"""
        self.log_event(
            event_type="workflow_completed",
            execution_state={"total_words": total_words, "consistency_issues": consistency_issues},
            data={"status": status}
        )

    def log_workflow_failed(self, error: str, scene_id: int = 0) -> None:
        """Log workflow failure"""
        self.log_event(
            event_type="workflow_failed",
            execution_state={"scene_id": scene_id},
            data={"error": error},
            success=False,
            error=error
        )

    # Analysis and reporting methods
    def get_trajectory_summary(self) -> Dict[str, Any]:
        """Get a summary of the entire trajectory"""
        if not self.events:
            return {"message": "No events logged"}

        total_events = len(self.events)
        success_events = sum(1 for e in self.events if e.success)
        failure_events = total_events - success_events

        # Calculate timeline
        first_event = self.events[0].timestamp
        last_event = self.events[-1].timestamp

        # Aggregate scene data
        scene_events = [e for e in self.events if e.event_type == "scene_generated"]
        total_scenes = len(scene_events)
        total_words = sum(e.execution_state.get("total_words", 0) for e in self.events if "total_words" in e.execution_state)

        return {
            "total_events": total_events,
            "successful_events": success_events,
            "failed_events": failure_events,
            "total_scenes_generated": total_scenes,
            "total_words_written": total_words,
            "time_range": {
                "start": first_event,
                "end": last_event
            },
            "event_types_distribution": self._get_event_type_distribution()
        }

    def _get_event_type_distribution(self) -> Dict[str, int]:
        """Get distribution of event types"""
        distribution = {}
        for event in self.events:
            if event.event_type not in distribution:
                distribution[event.event_type] = 0
            distribution[event.event_type] += 1
        return distribution

    def get_events_by_type(self, event_type: str) -> List[EvaluationEvent]:
        """Get all events of a specific type"""
        return [e for e in self.events if e.event_type == event_type]

    def load_trajectory(self, file_path: Optional[str] = None) -> List[EvaluationEvent]:
        """Load trajectory from a file"""
        path = Path(file_path) if file_path else self.trajectory_file

        events = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event_dict = json.loads(line)
                    event = EvaluationEvent(**event_dict)
                    events.append(event)
                except json.JSONDecodeError:
                    continue

        self.events = events
        return events

    def export_analysis(self, output_path: Optional[str] = None) -> str:
        """Export trajectory analysis to a JSON file"""
        if not output_path:
            output_path = str(self.output_dir / "evaluation_analysis.json")

        analysis = {
            "summary": self.get_trajectory_summary(),
            "total_events": len(self.events),
            "events": [asdict(e) for e in self.events]
        }

        with open(output_path, "w") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)

        return output_path

    def print_summary(self) -> None:
        """Print a human-readable summary of the trajectory"""
        summary = self.get_trajectory_summary()

        print("=== Evaluation Summary ===")
        print(f"Total events: {summary['total_events']}")
        print(f"Successful events: {summary['successful_events']}")
        print(f"Failed events: {summary['failed_events']}")
        print(f"Total scenes generated: {summary['total_scenes_generated']}")
        print(f"Total words written: {summary['total_words_written']}")
        print("\nEvent type distribution:")
        for event_type, count in summary['event_types_distribution'].items():
            print(f"  {event_type}: {count}")