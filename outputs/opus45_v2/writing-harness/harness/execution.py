"""Execution Loop module for driving the creative writing process.

Implements an explicit state machine that moves through phases:
INIT -> PLANNING -> GENERATING -> CHECKING -> REVISING -> FINALIZING -> COMPLETED
"""

from pathlib import Path
from typing import Any

from harness.state import (
    StateStore,
    WritingState,
    WritingPhase,
    TaskSpec,
    OutlineState,
)
from harness.context import ContextManager
from harness.tools import (
    ToolRegistry,
    ParseTaskInput,
    PlanPlotInput,
    DraftSceneInput,
    CheckConsistencyInput,
    ReviseSceneInput,
)
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder


class ExecutionLoop:
    """State machine driven execution loop for creative writing."""

    def __init__(
        self,
        state_store: StateStore,
        context_manager: ContextManager,
        tool_registry: ToolRegistry,
        lifecycle_hooks: LifecycleHooks,
        trajectory_recorder: TrajectoryRecorder,
        max_revisions: int = 3,
        timeout: int = 3600,
    ):
        self._state_store = state_store
        self._context_manager = context_manager
        self._tools = tool_registry
        self._hooks = lifecycle_hooks
        self._trajectory = trajectory_recorder
        self._max_revisions = max_revisions
        self._timeout = timeout

    def run(self, prompt: str, output_dir: Path) -> dict[str, Any]:
        """Run the complete creative writing pipeline."""
        self._hooks.on_timeout(self._save_current_draft)
        self._hooks.set_timeout(self._timeout)

        try:
            self._execute_init_phase(prompt)

            self._execute_planning_phase()

            self._execute_generation_phase()

            self._execute_finalization_phase(output_dir)

            return self._build_result(output_dir, "success")

        except TimeoutError as e:
            return self._build_result(output_dir, "partial", str(e))
        except Exception as e:
            self._hooks.on_error(
                phase=self._state_store.state.phase.value,
                error=str(e),
                save_callback=self._save_current_draft,
            )
            return self._build_result(output_dir, "failed", str(e))
        finally:
            self._hooks.clear_timeout()

    def _execute_init_phase(self, prompt: str) -> None:
        """Initialize from prompt."""
        self._transition_to(WritingPhase.INIT)

        parse_tool = self._tools.get("parse_task")
        result = parse_tool.execute(ParseTaskInput(prompt=prompt))

        task_spec = TaskSpec(
            genre=result.genre,
            premise=result.premise,
            target_words=result.target_words,
            pov=result.pov,
            style_directives=result.style_directives,
            structural_constraints=result.structural_constraints,
            max_revisions=self._max_revisions,
        )

        self._state_store.initialize(task_spec)
        self._context_manager.set_structural_constraints(task_spec.structural_constraints)

    def _execute_planning_phase(self) -> None:
        """Execute the planning phase."""
        self._transition_to(WritingPhase.PLANNING)
        state = self._state_store.state
        spec = state.task_spec

        style_anchor = self._hooks.inject_style_anchor(
            pov=spec.pov,
            genre=spec.genre,
            style_directives=spec.style_directives,
        )
        self._state_store.set_style_anchor(style_anchor.to_dict())

        plan_tool = self._tools.get("plan_plot")
        result = plan_tool.execute(PlanPlotInput(
            premise=spec.premise,
            genre=spec.genre,
            target_words=spec.target_words,
            structural_constraints=spec.structural_constraints,
        ))

        outline = OutlineState(
            beats=result.beats,
            scenes=result.scenes,
            character_arcs=result.character_arcs,
        )
        self._state_store.set_outline(outline)

        self._trajectory.record_outline_created(
            num_beats=len(result.beats),
            num_scenes=len(result.scenes),
        )

    def _execute_generation_phase(self) -> None:
        """Execute scene-by-scene generation with consistency checking."""
        self._transition_to(WritingPhase.GENERATING)
        state = self._state_store.state
        spec = state.task_spec

        total_scenes = len(state.outline.scenes)
        words_per_scene = spec.target_words // max(1, total_scenes)

        for scene_info in state.outline.scenes:
            scene_id = scene_info["id"]
            scene_summary = scene_info.get("summary", "")

            self._state_store._state.current_scene_id = scene_id
            self._trajectory.record_scene_start(
                scene_id=scene_id,
                scene_summary=scene_summary,
                total_word_count=state.total_word_count,
            )

            self._generate_and_check_scene(
                scene_id=scene_id,
                scene_summary=scene_summary,
                target_words=words_per_scene,
            )

            self._state_store.snapshot(scene_id)

    def _generate_and_check_scene(
        self,
        scene_id: int,
        scene_summary: str,
        target_words: int,
    ) -> None:
        """Generate a scene and run consistency checks, revising if needed."""
        state = self._state_store.state
        prior_content = self._state_store.get_prior_context(scene_id)

        hook_result = self._hooks.before_scene_generation(
            scene_id=scene_id,
            scene_summary=scene_summary,
            prior_content=prior_content,
        )
        context_injection = hook_result.data.get("context_injection", "")

        draft_tool = self._tools.get("draft_scene")
        draft_result = draft_tool.execute(DraftSceneInput(
            scene_id=scene_id,
            scene_summary=scene_summary,
            target_words=target_words,
            context_injection=context_injection,
            prior_content=prior_content,
        ))

        if not draft_result.success:
            raise RuntimeError(f"Failed to draft scene {scene_id}: {draft_result.error}")

        scene_content = draft_result.content
        word_count = draft_result.word_count

        self._state_store.update_scene(scene_id, scene_content, word_count)

        self._hooks.after_scene_generation(scene_id, scene_content)

        self._check_and_revise_scene(
            scene_id=scene_id,
            scene_summary=scene_summary,
            target_words=target_words,
        )

        self._context_manager.set_scene_summary(scene_id, scene_summary)

        self._trajectory.record_scene_complete(
            scene_id=scene_id,
            word_count=self._state_store.get_scene(scene_id).word_count,
            total_word_count=self._state_store.state.total_word_count,
            revision_count=self._state_store.get_scene(scene_id).revision_count,
        )

        self._state_store.mark_scene_complete(scene_id)

    def _check_and_revise_scene(
        self,
        scene_id: int,
        scene_summary: str,
        target_words: int,
    ) -> None:
        """Check scene for consistency and revise if needed."""
        self._transition_to(WritingPhase.CHECKING)

        scene = self._state_store.get_scene(scene_id)
        state = self._state_store.state
        prior_content = self._state_store.get_prior_context(scene_id)

        check_tool = self._tools.get("check_consistency")
        check_result = check_tool.execute(CheckConsistencyInput(
            scene_content=scene.content,
            scene_id=scene_id,
            entity_registry={
                k: v.to_dict()
                for k, v in self._context_manager.get_all_entities().items()
            },
            prior_content=prior_content,
            style_anchor=state.style_anchor,
        ))

        self._hooks.on_consistency_check_complete(
            scene_id=scene_id,
            is_consistent=check_result.is_consistent,
            issues=check_result.issues,
            severity=check_result.severity,
            entity_updates=check_result.entity_updates,
        )

        if not check_result.is_consistent and check_result.severity in ["major", "minor"]:
            self._revise_scene(
                scene_id=scene_id,
                scene_summary=scene_summary,
                issues=check_result.issues,
                target_words=target_words,
            )

        self._state_store.set_scene_issues(
            scene_id,
            check_result.issues if not check_result.is_consistent else [],
        )

        self._transition_to(WritingPhase.GENERATING)

    def _revise_scene(
        self,
        scene_id: int,
        scene_summary: str,
        issues: list[str],
        target_words: int,
    ) -> None:
        """Revise a scene to fix consistency issues."""
        self._transition_to(WritingPhase.REVISING)

        scene = self._state_store.get_scene(scene_id)
        max_revisions = self._state_store.state.task_spec.max_revisions

        while scene.revision_count < max_revisions and issues:
            revision_number = scene.revision_count + 1

            hook_result = self._hooks.on_revision_start(
                scene_id=scene_id,
                revision_type="fix_issues",
                revision_number=revision_number,
                issues=issues,
            )

            revise_tool = self._tools.get("revise_scene")
            revise_result = revise_tool.execute(ReviseSceneInput(
                scene_content=scene.content,
                scene_id=scene_id,
                revision_type="fix_issues",
                issues=issues,
                context_injection=hook_result.data.get("context_injection", ""),
                target_words=target_words,
            ))

            if not revise_result.success:
                self._hooks.on_rollback(
                    scene_id=scene_id,
                    reason=f"Revision failed: {revise_result.error}",
                )
                break

            self._state_store.update_scene(
                scene_id,
                revise_result.revised_content,
                revise_result.word_count,
            )
            self._state_store.add_scene_revision(scene_id)

            self._trajectory.record_revision(
                scene_id=scene_id,
                revision_type="fix_issues",
                revision_number=revision_number,
                word_count=revise_result.word_count,
                total_word_count=self._state_store.state.total_word_count,
                issues_fixed=issues,
            )

            check_tool = self._tools.get("check_consistency")
            check_result = check_tool.execute(CheckConsistencyInput(
                scene_content=revise_result.revised_content,
                scene_id=scene_id,
                entity_registry={
                    k: v.to_dict()
                    for k, v in self._context_manager.get_all_entities().items()
                },
                prior_content=self._state_store.get_prior_context(scene_id),
                style_anchor=self._state_store.state.style_anchor,
            ))

            if check_result.is_consistent:
                break

            issues = check_result.issues
            scene = self._state_store.get_scene(scene_id)

    def _execute_finalization_phase(self, output_dir: Path) -> None:
        """Finalize the manuscript."""
        self._transition_to(WritingPhase.FINALIZING)

        manuscript_text = self._state_store.get_manuscript_text()

        manuscript_path = output_dir / "manuscript.txt"
        with open(manuscript_path, "w", encoding="utf-8") as f:
            f.write(manuscript_text)

        self._state_store.save()

        self._transition_to(WritingPhase.COMPLETED)

        state = self._state_store.state
        self._hooks.on_completion(
            status="success",
            total_word_count=state.total_word_count,
            num_scenes=len(state.scenes),
            consistency_issues=state.consistency_issues,
        )

    def _transition_to(self, phase: WritingPhase) -> None:
        """Transition to a new phase."""
        current_phase = self._state_store.state.phase
        if current_phase != phase:
            self._hooks.on_phase_transition(
                from_phase=current_phase.value,
                to_phase=phase.value,
                total_word_count=self._state_store.state.total_word_count,
            )
            self._state_store.set_phase(phase)

    def _save_current_draft(self) -> None:
        """Save current draft state."""
        self._state_store.save()

    def _build_result(
        self,
        output_dir: Path,
        status: str,
        error: str = "",
    ) -> dict[str, Any]:
        """Build the result dictionary."""
        state = self._state_store.state

        manuscript_path = output_dir / "manuscript.txt"
        if not manuscript_path.exists():
            manuscript_text = self._state_store.get_manuscript_text()
            if manuscript_text:
                with open(manuscript_path, "w", encoding="utf-8") as f:
                    f.write(manuscript_text)

        all_issues = list(state.consistency_issues)
        for scene in state.scenes.values():
            all_issues.extend(scene.consistency_issues)

        result = {
            "status": status,
            "manuscript_path": str(manuscript_path) if manuscript_path.exists() else "",
            "word_count": state.total_word_count,
            "outline": {
                "beats": state.outline.beats,
                "scenes": [
                    {"id": s["id"], "summary": s.get("summary", "")}
                    for s in state.outline.scenes
                ],
            },
            "consistency_issues": all_issues,
            "trajectory": str(self._trajectory.trajectory_path),
        }

        if error:
            result["error"] = error

        return result
