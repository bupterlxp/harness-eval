import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID
from .schemas import TrajectoryEntry, GenerationState


class TrajectoryRecorder:
    """Records generation trajectory in V3 format"""

    def __init__(self, output_dir: str = "trajectories"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.session_files: Dict[UUID, str] = {}

    def _get_session_file(self, session_id: UUID) -> str:
        """Get the file path for a session's trajectory"""
        if session_id in self.session_files:
            return self.session_files[session_id]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trajectory_{session_id}_{timestamp}.jsonl"
        file_path = os.path.join(self.output_dir, filename)
        self.session_files[session_id] = file_path
        return file_path

    def write_entry(
        self,
        session_id: UUID,
        state: GenerationState,
        step_description: str,
        context_snapshot: Optional[Dict[str, Any]] = None,
        tool_call: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None
    ) -> None:
        """Write a trajectory entry"""
        entry = TrajectoryEntry(
            timestamp=datetime.now(),
            state=state,
            step_description=step_description,
            context_snapshot=context_snapshot,
            tool_call=tool_call,
            tool_result=tool_result
        )

        entry_dict = entry.dict()
        # Convert datetime to ISO format string for JSON serialization
        entry_dict["timestamp"] = entry.timestamp.isoformat()

        file_path = self._get_session_file(session_id)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_dict, ensure_ascii=False) + "\n")

    def write_entry_from_dict(
        self,
        session_id: UUID,
        entry_dict: Dict[str, Any]
    ) -> None:
        """Write a trajectory entry from a dictionary"""
        # Ensure proper datetime formatting
        if "timestamp" in entry_dict:
            if isinstance(entry_dict["timestamp"], datetime):
                entry_dict["timestamp"] = entry_dict["timestamp"].isoformat()

        file_path = self._get_session_file(session_id)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry_dict, ensure_ascii=False) + "\n")

    def get_full_trajectory(self, session_id: UUID) -> List[Dict[str, Any]]:
        """Retrieve full trajectory for a session"""
        file_path = self._get_session_file(session_id)
        if not os.path.exists(file_path):
            return []

        trajectory = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Convert ISO timestamp back to datetime
                    if "timestamp" in entry:
                        entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
                    trajectory.append(entry)
                except json.JSONDecodeError:
                    continue
        return trajectory

    def export_trajectory_summary(self, session_id: UUID, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Export a summary of the trajectory"""
        trajectory = self.get_full_trajectory(session_id)
        if not trajectory:
            return {}

        summary = {
            "session_id": str(session_id),
            "total_steps": len(trajectory),
            "start_time": trajectory[0]["timestamp"].isoformat() if trajectory else None,
            "end_time": trajectory[-1]["timestamp"].isoformat() if trajectory else None,
            "duration": (trajectory[-1]["timestamp"] - trajectory[0]["timestamp"]).total_seconds() if len(trajectory) > 1 else 0,
            "states_visited": list(set(entry["state"] for entry in trajectory)),
            "key_steps": []
        }

        for entry in trajectory:
            if entry["step_description"].startswith("[STEP]"):
                summary["key_steps"].append({
                    "state": entry["state"],
                    "description": entry["step_description"],
                    "timestamp": entry["timestamp"].isoformat()
                })

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

        return summary

    def clear_session(self, session_id: UUID) -> None:
        """Clear trajectory data for a session"""
        if session_id in self.session_files:
            file_path = self.session_files[session_id]
            if os.path.exists(file_path):
                os.remove(file_path)
            del self.session_files[session_id]

    def close(self) -> None:
        """Close all open files"""
        self.session_files.clear()