"""Execution Loop component - drives the creative writing workflow"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from harness.context import ContextManager
from harness.state import StateStore, SceneState
from harness.tools import ToolRegistry
from harness.evaluation import EvaluationLogger


class ExecutionPhase(Enum):
    """Current phase of the execution loop"""
    INITIALIZING = "initializing"
    PLANNING = "planning"
    GENERATING = "generating"
    REVISING = "revising"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExecutionState:
    """State of the entire execution workflow"""
    phase: ExecutionPhase = ExecutionPhase.INITIALIZING
    current_scene: int = 0
    total_words: int = 0
    scenes_generated: int = 0
    consistency_issues: List[str] = None
    trajectory_path: str = None

    def __post_init__(self):
        if self.consistency_issues is None:
            self.consistency_issues = []
        if self.trajectory_path is None:
            self.trajectory_path = ""


class ExecutionLoop:
    """Main execution loop that drives the creative writing workflow"""

    def __init__(
        self,
        task_spec: Any,
        context_manager: ContextManager,
        state_store: StateStore,
        evaluation_logger: EvaluationLogger
    ):
        self.task_spec = task_spec
        self.context_manager = context_manager
        self.state_store = state_store
        self.evaluation_logger = evaluation_logger
        self.tool_registry = ToolRegistry()
        self.execution_state = ExecutionState()

        # Initialize trajectory logging
        self.execution_state.trajectory_path = str(Path(task_spec.output_dir) / "trajectory.jsonl")

    def _log_trajectory(self, event_type: str, data: Dict[str, Any]):
        """Log trajectory event to JSONL file"""
        trajectory_entry = {
            "event_type": event_type,
            "execution_state": {
                "phase": self.execution_state.phase.value,
                "current_scene": self.execution_state.current_scene,
                "total_words": self.execution_state.total_words
            },
            "data": data
        }

        with open(self.execution_state.trajectory_path, "a") as f:
            f.write(json.dumps(trajectory_entry, ensure_ascii=False) + "\n")

    def _generate_outline(self) -> Dict[str, Any]:
        """Generate story outline from premise"""
        self.execution_state.phase = ExecutionPhase.PLANNING
        self._log_trajectory("outline_generation_started", {"premise": self.task_spec.premise})

        # Placeholder: In a real implementation, this would call an LLM to generate the outline
        outline = {
            "beats": [
                "Setup: Introduce characters and setting",
                "Confrontation: Develop central conflict",
                "Climax: Turning point of the story",
                "Resolution: Resolve conflicts and conclude"
            ],
            "scenes": [
                {"id": 1, "summary": "Introduction of main character and initial situation"},
                {"id": 2, "summary": "Inciting incident that disrupts the status quo"},
                {"id": 3, "summary": "Main character reacts to the incident and begins planning"},
                {"id": 4, "summary": "Rising action and development of the central conflict"},
                {"id": 5, "summary": "Climax of the story"},
                {"id": 6, "summary": "Falling action and aftermath"},
                {"id": 7, "summary": "Final resolution"}
            ]
        }

        self._log_trajectory("outline_generation_completed", {
            "beats_count": len(outline["beats"]),
            "scenes_count": len(outline["scenes"])
        })
        return outline

    def _generate_scene(self, scene_data: Dict[str, Any], context: str) -> str:
        """Generate a single scene"""
        self.execution_state.phase = ExecutionPhase.GENERATING
        self.execution_state.current_scene = scene_data["id"]
        self._log_trajectory("scene_generation_started", {
            "scene_id": scene_data["id"],
            "scene_summary": scene_data["summary"]
        })

        # Placeholder: In a real implementation, this would call an LLM to generate the scene
        # using the context and style directives
        scene_content = f"""Scene {scene_data['id']}: {scene_data['summary']}

This is a generated scene in the {self.task_spec.genre} genre.
The narrative perspective is {self.task_spec.pov}.
Style directives: {', '.join(self.task_spec.style_directives)}

Context from previous scenes:
{context}

[Scene content would appear here - this is a placeholder]
"""

        scene_word_count = len(scene_content.split())
        self.execution_state.total_words += scene_word_count
        self.execution_state.scenes_generated += 1

        self._log_trajectory("scene_generation_completed", {
            "scene_id": scene_data["id"],
            "word_count": scene_word_count,
            "total_words_so_far": self.execution_state.total_words
        })
        return scene_content

    def _evaluate_scene(self, scene_content: str, scene_id: int) -> List[str]:
        """Evaluate scene for consistency issues"""
        self.execution_state.phase = ExecutionPhase.EVALUATING
        self._log_trajectory("scene_evaluation_started", {"scene_id": scene_id})

        # Placeholder: In a real implementation, this would run consistency checks
        issues = []

        # Example consistency check
        if "blue eyes" in scene_content.lower() and "brown eyes" in scene_content.lower():
            issues.append("Conflicting eye color descriptions found")

        self._log_trajectory("scene_evaluation_completed", {
            "scene_id": scene_id,
            "issues_found": len(issues)
        })
        return issues

    def _revise_scene(self, scene_content: str, issues: List[str], scene_id: int) -> str:
        """Revise scene based on feedback"""
        self.execution_state.phase = ExecutionPhase.REVISING
        self._log_trajectory("scene_revision_started", {
            "scene_id": scene_id,
            "issues_count": len(issues)
        })

        # Placeholder: In a real implementation, this would revise the scene
        revised_content = f"[REVISED] {scene_content}"
        if issues:
            revised_content += f"\n\n[Fixed consistency issues: {', '.join(issues)}]"

        self._log_trajectory("scene_revision_completed", {"scene_id": scene_id})
        return revised_content

    def run(self) -> Dict[str, Any]:
        """Main execution workflow"""
        try:
            self._log_trajectory("workflow_started", {
                "task_spec": {
                    "genre": self.task_spec.genre,
                    "target_words": self.task_spec.target_words,
                    "pov": self.task_spec.pov,
                    "max_revisions": self.task_spec.max_revisions
                }
            })

            # Step 1: Generate outline
            outline = self._generate_outline()

            # Step 2: Process each scene
            all_scenes = []
            cumulative_context = ""

            for scene in outline["scenes"]:
                # Get context from previous scenes
                context = self.context_manager.get_context(cumulative_context)

                # Generate scene
                scene_content = self._generate_scene(scene, context)

                # Evaluate consistency
                issues = self._evaluate_scene(scene_content, scene["id"])
                self.execution_state.consistency_issues.extend(issues)

                # Revise if needed
                if issues and self.task_spec.max_revisions > 0:
                    for revision in range(self.task_spec.max_revisions):
                        scene_content = self._revise_scene(scene_content, issues, scene["id"])
                        issues = self._evaluate_scene(scene_content, scene["id"])
                        if not issues:
                            break

                # Save scene state
                scene_state = SceneState(
                    id=scene["id"],
                    summary=scene["summary"],
                    content=scene_content,
                    word_count=len(scene_content.split()),
                    consistency_issues=issues
                )
                self.state_store.save_scene(scene_state)

                # Update cumulative context
                cumulative_context += f"\n\nScene {scene['id']}: {scene_content}"
                all_scenes.append(scene_state)

            # Step 3: Combine final manuscript
            manuscript_content = "\n\n---\n\n".join([s.content for s in all_scenes])
            manuscript_path = str(Path(self.task_spec.output_dir) / "manuscript.txt")
            with open(manuscript_path, "w") as f:
                f.write(manuscript_content)

            # Step 4: Final evaluation
            final_issues = self._evaluate_scene(manuscript_content, 0)
            self.execution_state.consistency_issues.extend(final_issues)

            # Step 5: Prepare result
            result = {
                "status": "success" if not final_issues else "partial",
                "manuscript_path": manuscript_path,
                "word_count": self.execution_state.total_words,
                "outline": {
                    "beats": outline["beats"],
                    "scenes": [{"id": s.id, "summary": s.summary} for s in all_scenes]
                },
                "consistency_issues": self.execution_state.consistency_issues,
                "trajectory": self.execution_state.trajectory_path
            }

            self.execution_state.phase = ExecutionPhase.COMPLETED
            self._log_trajectory("workflow_completed", {
                "status": result["status"],
                "total_words": result["word_count"],
                "consistency_issues_count": len(result["consistency_issues"])
            })

            return result

        except Exception as e:
            self.execution_state.phase = ExecutionPhase.FAILED
            self._log_trajectory("workflow_failed", {"error": str(e)})
            raise