"""Evaluation module for trajectory recording.

Records each step of the creative writing process in JSONL format,
capturing state, scene ID, word counts, and consistency check results.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """A single entry in the trajectory log."""
    timestamp: str
    phase: str
    scene_id: int | None
    action: str
    word_count: int
    total_word_count: int
    consistency_check: dict[str, Any] | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class TrajectoryRecorder:
    """Records the creative writing trajectory in JSONL format."""

    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory_path = self.output_dir / "trajectory.jsonl"
        self._entries: list[TrajectoryEntry] = []

    def record(
        self,
        phase: str,
        action: str,
        scene_id: int | None = None,
        word_count: int = 0,
        total_word_count: int = 0,
        consistency_check: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a trajectory entry."""
        entry = TrajectoryEntry(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            scene_id=scene_id,
            action=action,
            word_count=word_count,
            total_word_count=total_word_count,
            consistency_check=consistency_check,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._append_to_file(entry)

    def _append_to_file(self, entry: TrajectoryEntry) -> None:
        """Append entry to JSONL file."""
        with open(self.trajectory_path, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

    def record_phase_transition(
        self,
        from_phase: str,
        to_phase: str,
        total_word_count: int = 0,
    ) -> None:
        """Record a phase transition."""
        self.record(
            phase=to_phase,
            action=f"phase_transition:{from_phase}->{to_phase}",
            total_word_count=total_word_count,
            metadata={"from_phase": from_phase, "to_phase": to_phase},
        )

    def record_scene_start(
        self,
        scene_id: int,
        scene_summary: str,
        total_word_count: int = 0,
    ) -> None:
        """Record the start of scene generation."""
        self.record(
            phase="generating",
            action="scene_start",
            scene_id=scene_id,
            total_word_count=total_word_count,
            metadata={"scene_summary": scene_summary},
        )

    def record_scene_complete(
        self,
        scene_id: int,
        word_count: int,
        total_word_count: int,
        revision_count: int = 0,
    ) -> None:
        """Record scene completion."""
        self.record(
            phase="generating",
            action="scene_complete",
            scene_id=scene_id,
            word_count=word_count,
            total_word_count=total_word_count,
            metadata={"revision_count": revision_count},
        )

    def record_consistency_check(
        self,
        scene_id: int,
        is_consistent: bool,
        issues: list[str],
        severity: str,
        total_word_count: int = 0,
    ) -> None:
        """Record a consistency check result."""
        self.record(
            phase="checking",
            action="consistency_check",
            scene_id=scene_id,
            total_word_count=total_word_count,
            consistency_check={
                "is_consistent": is_consistent,
                "issues": issues,
                "severity": severity,
            },
        )

    def record_revision(
        self,
        scene_id: int,
        revision_type: str,
        revision_number: int,
        word_count: int,
        total_word_count: int,
        issues_fixed: list[str],
    ) -> None:
        """Record a scene revision."""
        self.record(
            phase="revising",
            action=f"revision:{revision_type}",
            scene_id=scene_id,
            word_count=word_count,
            total_word_count=total_word_count,
            metadata={
                "revision_number": revision_number,
                "revision_type": revision_type,
                "issues_fixed": issues_fixed,
            },
        )

    def record_rollback(
        self,
        scene_id: int,
        reason: str,
        total_word_count: int = 0,
    ) -> None:
        """Record a scene rollback."""
        self.record(
            phase="revising",
            action="rollback",
            scene_id=scene_id,
            total_word_count=total_word_count,
            metadata={"reason": reason},
        )

    def record_outline_created(
        self,
        num_beats: int,
        num_scenes: int,
        total_word_count: int = 0,
    ) -> None:
        """Record outline creation."""
        self.record(
            phase="planning",
            action="outline_created",
            total_word_count=total_word_count,
            metadata={"num_beats": num_beats, "num_scenes": num_scenes},
        )

    def record_style_anchor_set(
        self,
        style_anchor: dict[str, Any],
    ) -> None:
        """Record style anchor creation."""
        self.record(
            phase="planning",
            action="style_anchor_set",
            metadata={"style_anchor": style_anchor},
        )

    def record_error(
        self,
        phase: str,
        error: str,
        scene_id: int | None = None,
        total_word_count: int = 0,
    ) -> None:
        """Record an error."""
        self.record(
            phase=phase,
            action="error",
            scene_id=scene_id,
            total_word_count=total_word_count,
            metadata={"error": error},
        )

    def record_completion(
        self,
        status: str,
        total_word_count: int,
        num_scenes: int,
        consistency_issues: list[str],
    ) -> None:
        """Record final completion."""
        self.record(
            phase="completed" if status == "success" else "failed",
            action="completion",
            total_word_count=total_word_count,
            metadata={
                "status": status,
                "num_scenes": num_scenes,
                "consistency_issues": consistency_issues,
            },
        )

    def get_entries(self) -> list[TrajectoryEntry]:
        """Get all recorded entries."""
        return self._entries.copy()

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the trajectory."""
        phase_counts: dict[str, int] = {}
        total_revisions = 0
        consistency_checks = 0
        issues_found = 0

        for entry in self._entries:
            phase_counts[entry.phase] = phase_counts.get(entry.phase, 0) + 1
            if "revision" in entry.action:
                total_revisions += 1
            if entry.consistency_check:
                consistency_checks += 1
                if not entry.consistency_check.get("is_consistent", True):
                    issues_found += 1

        return {
            "total_entries": len(self._entries),
            "phase_counts": phase_counts,
            "total_revisions": total_revisions,
            "consistency_checks": consistency_checks,
            "issues_found": issues_found,
        }

    def load_from_file(self) -> bool:
        """Load trajectory from existing file."""
        if not self.trajectory_path.exists():
            return False

        self._entries = []
        with open(self.trajectory_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    self._entries.append(TrajectoryEntry(**data))
        return True
