import json
import os
from typing import List, Dict, Optional, Any
from datetime import datetime
from dataclasses import asdict

from .schemas import StepResult, TaskStatus


class EvaluationRecorder:
    """Records execution trajectory for evaluation"""

    def __init__(self, output_dir: str = "evaluation"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.trajectory: List[Dict] = []
        self.start_time = datetime.now()

    def record_step(self, result: StepResult, metadata: Optional[Dict] = None) -> None:
        """Record a single step result"""
        step_data = {
            "step_id": result.step_id,
            "timestamp": result.timestamp.isoformat(),
            "url": result.url,
            "status": result.status,
            "error_message": result.error_message,
            "retry_count": result.retry_count,
            "screenshot_path": result.screenshot_path,
            "data": result.data,
            "metadata": metadata or {}
        }
        self.trajectory.append(step_data)

    def save_trajectory(self, filename: Optional[str] = None) -> str:
        """Save full trajectory to JSONL file"""
        if not filename:
            timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            filename = f"trajectory_{timestamp}.jsonl"

        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            for step in self.trajectory:
                json.dump(step, f, ensure_ascii=False)
                f.write("\n")

        return filepath

    def generate_report(self) -> Dict[str, Any]:
        """Generate evaluation report from trajectory"""
        total_steps = len(self.trajectory)
        completed = sum(1 for s in self.trajectory if s["status"] == TaskStatus.COMPLETED)
        failed = sum(1 for s in self.trajectory if s["status"] == TaskStatus.FAILED)
        skipped = sum(1 for s in self.trajectory if s["status"] == TaskStatus.SKIPPED)

        total_retries = sum(s.get("retry_count", 0) for s in self.trajectory)
        avg_retries_per_step = total_retries / total_steps if total_steps > 0 else 0

        screenshots_taken = sum(1 for s in self.trajectory if s.get("screenshot_path"))

        # Group by status
        status_counts = {
            TaskStatus.COMPLETED: completed,
            TaskStatus.FAILED: failed,
            TaskStatus.SKIPPED: skipped,
            TaskStatus.PENDING: total_steps - completed - failed - skipped
        }

        report = {
            "summary": {
                "total_steps": total_steps,
                "completed_steps": completed,
                "failed_steps": failed,
                "skipped_steps": skipped,
                "success_rate": (completed / total_steps * 100) if total_steps > 0 else 0,
                "total_retries": total_retries,
                "avg_retries_per_step": avg_retries_per_step,
                "screenshots_taken": screenshots_taken,
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration": (datetime.now() - self.start_time).total_seconds()
            },
            "status_distribution": status_counts,
            "step_details": self.trajectory
        }

        return report

    def save_report(self, report: Dict[str, Any], filename: Optional[str] = None) -> str:
        """Save evaluation report to JSON file"""
        if not filename:
            timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_report_{timestamp}.json"

        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return filepath

    def print_summary(self) -> None:
        """Print a summary of the execution"""
        report = self.generate_report()
        summary = report["summary"]

        print("\n" + "="*50)
        print("EXECUTION SUMMARY")
        print("="*50)
        print(f"Total steps: {summary['total_steps']}")
        print(f"Completed: {summary['completed_steps']} ({summary['success_rate']:.1f}%)")
        print(f"Failed: {summary['failed_steps']}")
        print(f"Skipped: {summary['skipped_steps']}")
        print(f"Total retries: {summary['total_retries']}")
        print(f"Average retries per step: {summary['avg_retries_per_step']:.2f}")
        print(f"Screenshots taken: {summary['screenshots_taken']}")
        print(f"Duration: {summary['duration']:.2f} seconds")
        print("="*50 + "\n")