import time
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from uuid import UUID
from .schemas import (
    GenerationState, TaskSpec, NarratorProfile, PlotOutline,
    Scene, ConsistencyReport, DiffReport
)
from .state import StateStore
from .context import ContextManager
from .tools import ToolRegistry, ToolCallResult
from .lifecycle import HookManager
from .evaluation import TrajectoryRecorder
import openai
import os
import json


class ExecutionStepResult:
    """Result from a single execution step"""
    def __init__(
        self,
        completed: bool,
        next_state: Optional[GenerationState] = None,
        result_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        self.completed = completed
        self.next_state = next_state
        self.result_data = result_data or {}
        self.error = error


class ExecutionLoop:
    """Main execution loop state machine"""

    def __init__(
        self,
        state_store: StateStore,
        context_manager: ContextManager,
        tool_registry: ToolRegistry,
        hook_manager: HookManager,
        trajectory_recorder: TrajectoryRecorder,
        session_id: UUID,
        task_spec: Optional[TaskSpec] = None
    ):
        self.state_store = state_store
        self.context_manager = context_manager
        self.tool_registry = tool_registry
        self.hook_manager = hook_manager
        self.trajectory_recorder = trajectory_recorder
        self.session_id = session_id
        self.current_state = GenerationState.INITIALIZED
        self.task_spec = task_spec
        self._initialize_session()

    def _initialize_session(self):
        """Initialize or restore session"""
        if self.task_spec:
            self.context_manager.set_task_spec(self.task_spec.dict())
            self._update_state(GenerationState.PARSED_TASK, "Task specification parsed")

    def _update_state(self, new_state: GenerationState, step_description: str, context_snapshot: Optional[Dict[str, Any]] = None):
        """Update current state and record trajectory"""
        self.current_state = new_state
        self.hook_manager.dispatch_event({
            "event_type": "state_change",
            "previous_state": self.current_state,
            "new_state": new_state,
            "description": step_description
        })
        self.trajectory_recorder.write_entry(
            session_id=self.session_id,
            state=new_state,
            step_description=step_description,
            context_snapshot=context_snapshot
        )

    def step(self) -> ExecutionStepResult:
        """Execute one step of the state machine"""
        match self.current_state:
            case GenerationState.INITIALIZED:
                return self._handle_initialized()
            case GenerationState.PARSED_TASK:
                return self._handle_parsed_task()
            case GenerationState.GENERATED_NARRATOR:
                return self._handle_generated_narrator()
            case GenerationState.GENERATED_PLOT:
                return self._handle_generated_plot()
            case GenerationState.GENERATED_SCENES:
                return self._handle_generated_scenes()
            case GenerationState.DRAFTING_SCENES:
                return self._handle_drafting_scenes()
            case GenerationState.CHECKING_CONSISTENCY:
                return self._handle_checking_consistency()
            case GenerationState.REVISING_STYLE:
                return self._handle_revising_style()
            case GenerationState.ASSEMBLING_FINAL:
                return self._handle_assembling_final()
            case GenerationState.COMPLETED:
                return ExecutionStepResult(completed=True, next_state=GenerationState.COMPLETED)
            case GenerationState.FAILED:
                return ExecutionStepResult(completed=True, error=f"Execution failed in state {self.current_state}")
            case _:
                return ExecutionStepResult(
                    completed=False,
                    error=f"Unknown state: {self.current_state}"
                )

    def _handle_initialized(self) -> ExecutionStepResult:
        """Handle initialized state - need task specification"""
        if not self.task_spec:
            return ExecutionStepResult(
                completed=False,
                error="No task specification provided"
            )

        self._update_state(
            GenerationState.PARSED_TASK,
            "Task specification parsed successfully"
        )
        return ExecutionStepResult(
            completed=True,
            next_state=GenerationState.PARSED_TASK
        )

    def _handle_parsed_task(self) -> ExecutionStepResult:
        """Handle parsed task - generate narrator profile"""
        try:
            # Call narrator generation tool
            result = self.tool_registry.execute_tool(
                "generate_narrator_profile",
                task_spec=self.task_spec.dict()
            )

            if result.status == "needs_approval":
                self.hook_manager.request_approval(
                    tool_name="generate_narrator_profile",
                    parameters={"task_spec": self.task_spec.dict()},
                    description="Generate narrator voice profile",
                    risk_level="low"
                )
                return ExecutionStepResult(
                    completed=False,
                    error="Approval required for narrator generation"
                )
            elif result.status == "error":
                raise Exception(result.error_message)

            narrator_profile = NarratorProfile(**result.data)
            self.context_manager.set_narrator_profile(narrator_profile)
            self._update_state(
                GenerationState.GENERATED_NARRATOR,
                "Narrator profile generated successfully",
                {"narrator_profile": narrator_profile.dict()}
            )
            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.GENERATED_NARRATOR,
                result_data={"narrator_profile": narrator_profile}
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error generating narrator profile: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to generate narrator profile: {str(e)}"
            )

    def _handle_generated_narrator(self) -> ExecutionStepResult:
        """Handle generated narrator - generate plot outline"""
        try:
            result = self.tool_registry.execute_tool(
                "generate_plot_outline",
                task_spec=self.task_spec.dict(),
                narrator_profile=self.context_manager.narrator_profile.dict() if self.context_manager.narrator_profile else None
            )

            if result.status == "needs_approval":
                return ExecutionStepResult(
                    completed=False,
                    error="Approval required for plot generation"
                )
            elif result.status == "error":
                raise Exception(result.error_message)

            plot_outline = PlotOutline(**result.data)
            self.context_manager.set_plot_outline(plot_outline.dict())
            self._update_state(
                GenerationState.GENERATED_PLOT,
                "Plot outline generated successfully",
                {"plot_outline": plot_outline.dict()}
            )
            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.GENERATED_PLOT,
                result_data={"plot_outline": plot_outline}
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error generating plot outline: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to generate plot outline: {str(e)}"
            )

    def _handle_generated_plot(self) -> ExecutionStepResult:
        """Handle generated plot - generate scene outline"""
        try:
            result = self.tool_registry.execute_tool(
                "generate_scene_outline",
                plot_outline=self.context_manager.plot_outline,
                task_spec=self.task_spec.dict()
            )

            if result.status == "needs_approval":
                return ExecutionStepResult(
                    completed=False,
                    error="Approval required for scene generation"
                )
            elif result.status == "error":
                raise Exception(result.error_message)

            scenes = [Scene(**scene_data) for scene_data in result.data["scenes"]]
            self._update_state(
                GenerationState.GENERATED_SCENES,
                f"Generated {len(scenes)} scene outlines",
                {"scene_count": len(scenes), "scenes": [scene.dict() for scene in scenes]}
            )
            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.GENERATED_SCENES,
                result_data={"scenes": scenes}
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error generating scene outline: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to generate scene outline: {str(e)}"
            )

    def _handle_generated_scenes(self) -> ExecutionStepResult:
        """Handle generated scenes - start drafting scenes"""
        self._update_state(
            GenerationState.DRAFTING_SCENES,
            "Starting scene drafting"
        )
        return ExecutionStepResult(
            completed=True,
            next_state=GenerationState.DRAFTING_SCENES,
            result_data={"current_scene_index": 0}
        )

    def _handle_drafting_scenes(self) -> ExecutionStepResult:
        """Handle drafting scenes - draft one scene at a time"""
        # Get current scene index from state store
        session_info = self.state_store.get_session(self.session_id)
        current_scene_id = session_info.current_scene_id if session_info else 0

        # Get all scenes
        scenes = self.context_manager.current_scenes or []
        if not scenes:
            # Load scenes from context
            if "scenes" in self.context_manager.plot_outline:
                scenes = [Scene(**scene_data) for scene_data in self.context_manager.plot_outline["scenes"]]
            else:
                self._update_state(GenerationState.FAILED, "No scenes found to draft")
                return ExecutionStepResult(
                    completed=False,
                    error="No scenes found to draft"
                )

        if current_scene_id >= len(scenes):n            # All scenes drafted
            self._update_state(
                GenerationState.CHECKING_CONSISTENCY,
                "All scenes drafted, starting consistency checks"
            )
            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.CHECKING_CONSISTENCY
            )

        current_scene = scenes[current_scene_id]
        try:
            # Draft the scene
            result = self.tool_registry.execute_tool(
                "draft_scene",
                scene=current_scene.dict(),
                context=self.context_manager.serialize_context(),
                narrator_voice=self.context_manager.get_narrator_voice_prompt()
            )

            if result.status == "needs_approval":
                return ExecutionStepResult(
                    completed=False,
                    error="Approval required for scene drafting"
                )
            elif result.status == "error":
                raise Exception(result.error_message)

            # Update scene with content
            current_scene.content = result.data.get("content", "")
            self.context_manager.add_current_scene(current_scene.dict())

            # Update imagery from scene
            imagery = result.data.get("imagery_used", [])
            for img in imagery:
                self.context_manager.add_imagery_entry(img)

            # Update session state
            if session_info:
                session_info.current_scene_id = current_scene_id + 1
                self.state_store.update_session(session_info)

            self._update_state(
                GenerationState.DRAFTING_SCENES,
                f"Drafted scene {current_scene_id + 1}/{len(scenes)}",
                {"scene_id": current_scene_id, "scene_title": current_scene.title}
            )

            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.DRAFTING_SCENES,
                result_data={
                    "scene": current_scene.dict(),
                    "next_scene_id": current_scene_id + 1
                }
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error drafting scene {current_scene_id}: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to draft scene {current_scene_id}: {str(e)}"
            )

    def _handle_checking_consistency(self) -> ExecutionStepResult:
        """Handle consistency checking phase"""
        try:
            scenes_content = [
                scene.get("content", "")
                for scene in self.context_manager.current_scenes
                if scene.get("content")
            ]

            result = self.tool_registry.execute_tool(
                "check_consistency",
                scenes=scenes_content,
                established_imagery=self.context_manager.established_imagery,
                task_spec=self.task_spec.dict()
            )

            if result.status == "error":
                raise Exception(result.error_message)

            consistency_report = ConsistencyReport(**result.data)
            self._update_state(
                GenerationState.REVISING_STYLE,
                f"Consistency check completed: {len(consistency_report.issues)} issues found",
                {"consistency_report": consistency_report.dict()}
            )

            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.REVISING_STYLE,
                result_data={"consistency_report": consistency_report}
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error checking consistency: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to check consistency: {str(e)}"
            )

    def _handle_revising_style(self) -> ExecutionStepResult:
        """Handle style revision phase"""
        try:
            result = self.tool_registry.execute_tool(
                "revise_style",
                scenes=self.context_manager.current_scenes,
                style_requirements=self.context_manager.style_requirements,
                narrator_voice=self.context_manager.get_narrator_voice_prompt()
            )

            if result.status == "needs_approval":
                return ExecutionStepResult(
                    completed=False,
                    error="Approval required for style revision"
                )
            elif result.status == "error":
                raise Exception(result.error_message)

            revised_scenes = result.data.get("scenes", [])
            self.context_manager.current_scenes = revised_scenes

            self._update_state(
                GenerationState.ASSEMBLING_FINAL,
                "Style revision completed, assembling final manuscript"
            )

            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.ASSEMBLING_FINAL,
                result_data={"revised_scenes_count": len(revised_scenes)}
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error revising style: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to revise style: {str(e)}"
            )

    def _handle_assembling_final(self) -> ExecutionStepResult:
        """Handle final manuscript assembly"""
        try:
            result = self.tool_registry.execute_tool(
                "assemble_final_manuscript",
                scenes=self.context_manager.current_scenes,
                task_spec=self.task_spec.dict()
            )

            if result.status == "error":
                raise Exception(result.error_message)

            final_manuscript = result.data.get("manuscript", "")
            final_title = result.data.get("title", "Generated Story")

            self._update_state(
                GenerationState.COMPLETED,
                "Final manuscript assembled successfully"
            )

            return ExecutionStepResult(
                completed=True,
                next_state=GenerationState.COMPLETED,
                result_data={
                    "manuscript": final_manuscript,
                    "title": final_title,
                    "word_count": len(final_manuscript.split())
                }
            )

        except Exception as e:
            self._update_state(GenerationState.FAILED, f"Error assembling final manuscript: {str(e)}")
            return ExecutionStepResult(
                completed=False,
                error=f"Failed to assemble final manuscript: {str(e)}"
            )

    def run_to_completion(self, max_steps: int = 100) -> Dict[str, Any]:
        """Run the execution loop until completion or failure"""
        steps = 0
        start_time = time.time()

        while steps < max_steps:
            steps += 1
            result = self.step()

            if result.error:
                return {
                    "success": False,
                    "error": result.error,
                    "state": self.current_state.value,
                    "steps_taken": steps,
                    "elapsed_time": time.time() - start_time
                }

            if result.completed and result.next_state == GenerationState.COMPLETED:
                return {
                    "success": True,
                    "result": result.result_data,
                    "state": self.current_state.value,
                    "steps_taken": steps,
                    "elapsed_time": time.time() - start_time
                }

            if not result.completed:
                # Waiting for user input or approval
                return {
                    "success": False,
                    "waiting": True,
                    "state": self.current_state.value,
                    "steps_taken": steps,
                    "result_data": result.result_data,
                    "elapsed_time": time.time() - start_time
                }

        return {
            "success": False,
            "error": "Max steps exceeded",
            "state": self.current_state.value,
            "steps_taken": steps,
            "elapsed_time": time.time() - start_time
        }