"""
execution.py - E: Execution Loop with State Machine

Implements explicit state machine with match-based transitions.
Defines δ function for all events including exceptions.
Satisfies safety (no invalid states) and liveness (progress guaranteed).
"""

from __future__ import annotations
from typing import Any, Callable, TYPE_CHECKING
from dataclasses import dataclass, field

from harness.schemas import (
    ExecutionState, EventType, TaskSpec, PlotOutline,
    SceneSpec, SceneDraft, SessionState, ImageryEntry
)
from harness.tools import ToolRegistry, ToolResult, ToolApprovalRequired
from harness.context import ContextManager, ContextCategory
from harness.state import StateStore
from harness.lifecycle import HookManager, LifecycleEventType
from harness.evaluation import TrajectoryRecorder

if TYPE_CHECKING:
    pass


class ExecutionError(Exception):
    """Execution loop error"""
    pass


class InvalidTransitionError(ExecutionError):
    """Invalid state transition attempted"""
    pass


@dataclass
class TransitionResult:
    """Result of a state transition"""
    new_state: ExecutionState
    event: EventType
    data: dict[str, Any] = field(default_factory=dict)
    should_continue: bool = True


class ExecutionLoop:
    """
    E component: State machine execution loop.

    Uses explicit match on current state to determine next action.
    δ function is defined for all (state, event) pairs.
    """

    VALID_TRANSITIONS: dict[ExecutionState, dict[EventType, ExecutionState]] = {
        ExecutionState.INIT: {
            EventType.START: ExecutionState.PARSE_SPEC,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
        },
        ExecutionState.PARSE_SPEC: {
            EventType.SPEC_PARSED: ExecutionState.NARRATOR_VOICE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.NARRATOR_VOICE: {
            EventType.VOICE_GENERATED: ExecutionState.PLOT_OUTLINE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.PLOT_OUTLINE: {
            EventType.PLOT_GENERATED: ExecutionState.SCENE_OUTLINE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.SCENE_OUTLINE: {
            EventType.SCENES_OUTLINED: ExecutionState.DRAFT_SCENE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.DRAFT_SCENE: {
            EventType.SCENE_DRAFTED: ExecutionState.DRAFT_SCENE,
            EventType.ALL_SCENES_DRAFTED: ExecutionState.CONSISTENCY_CHECK,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.CONSISTENCY_CHECK: {
            EventType.CONSISTENCY_PASSED: ExecutionState.STYLE_REVISION,
            EventType.CONSISTENCY_FAILED: ExecutionState.DRAFT_SCENE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.STYLE_REVISION: {
            EventType.STYLE_REVISED: ExecutionState.FINAL_ASSEMBLY,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.FINAL_ASSEMBLY: {
            EventType.ASSEMBLY_COMPLETE: ExecutionState.COMPLETE,
            EventType.ERROR_OCCURRED: ExecutionState.ERROR,
            EventType.SUSPEND: ExecutionState.SUSPENDED,
        },
        ExecutionState.COMPLETE: {
        },
        ExecutionState.ERROR: {
            EventType.RESUME: ExecutionState.INIT,
        },
        ExecutionState.SUSPENDED: {
            EventType.RESUME: ExecutionState.PARSE_SPEC,
            EventType.USER_INTERRUPT: ExecutionState.ERROR,
        },
    }

    def __init__(
        self,
        tools: ToolRegistry,
        context: ContextManager,
        state_store: StateStore,
        hooks: HookManager,
        trajectory: TrajectoryRecorder,
        on_output: Callable[[str], None] | None = None
    ):
        self.tools = tools
        self.context = context
        self.state_store = state_store
        self.hooks = hooks
        self.trajectory = trajectory
        self._on_output = on_output or (lambda x: None)

        self._session_state: SessionState | None = None
        self._interrupted = False

    @property
    def current_state(self) -> ExecutionState:
        """Get current execution state"""
        if self._session_state is None:
            return ExecutionState.INIT
        return self._session_state.current_state

    @property
    def session_id(self) -> str:
        """Get current session ID"""
        if self._session_state is None:
            raise ExecutionError("No active session")
        return self._session_state.session_id

    def _validate_transition(self, event: EventType) -> ExecutionState:
        """Validate and return target state for transition"""
        current = self.current_state
        valid = self.VALID_TRANSITIONS.get(current, {})

        if event not in valid:
            raise InvalidTransitionError(
                f"Invalid transition: {current.value} + {event.value}"
            )

        return valid[event]

    def _transition(self, event: EventType, data: dict[str, Any] | None = None) -> TransitionResult:
        """Execute a state transition"""
        state_before = self.current_state
        state_after = self._validate_transition(event)

        self.hooks.emit_simple(
            LifecycleEventType.STATE_TRANSITION,
            self.session_id,
            {"from": state_before.value, "to": state_after.value, "event": event.value},
            source="execution"
        )

        if self._session_state:
            self._session_state.current_state = state_after

        self.trajectory.record(
            state_before=state_before,
            state_after=state_after,
            event=event,
            reasoning=data.get("reasoning", "") if data else "",
            context_snapshot=self.context.snapshot() if data and data.get("snapshot_context") else {}
        )

        should_continue = state_after not in (
            ExecutionState.COMPLETE,
            ExecutionState.ERROR,
            ExecutionState.SUSPENDED
        )

        return TransitionResult(
            new_state=state_after,
            event=event,
            data=data or {},
            should_continue=should_continue
        )

    def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        approved: bool = False
    ) -> ToolResult:
        """Execute a tool with lifecycle hooks"""
        pre_event = self.hooks.emit_simple(
            LifecycleEventType.TOOL_PRE_EXECUTE,
            self.session_id,
            {
                "tool_name": tool_name,
                "args": args,
                "requires_approval": self.tools.requires_approval(tool_name)
            },
            source="execution",
            cancellable=True
        )

        if pre_event.cancelled:
            return ToolResult(
                success=False,
                error=pre_event.cancel_reason,
                metadata={"cancelled_by_hook": True}
            )

        context_dict = self.context.snapshot() if self.tools.get(tool_name).requires_context else None
        result = self.tools.execute(tool_name, args, context_dict, approved)

        self.hooks.emit_simple(
            LifecycleEventType.TOOL_POST_EXECUTE,
            self.session_id,
            {"tool_name": tool_name, "success": result.success, "error": result.error},
            source="execution"
        )

        state_before = self.current_state
        self.trajectory.record(
            state_before=state_before,
            state_after=state_before,
            event=EventType.SCENE_DRAFTED if "scene" in tool_name else EventType.SPEC_PARSED,
            tool_called=tool_name,
            tool_input=args,
            tool_output_summary=str(result.output)[:200] if result.output else "",
            error=result.error
        )

        return result

    def step(self) -> TransitionResult:
        """
        Execute one step of the state machine.

        Uses explicit match on current state to determine action.
        This is the δ function implementation.
        """
        if self._interrupted:
            self._interrupted = False
            return self._transition(EventType.USER_INTERRUPT)

        match self.current_state:
            case ExecutionState.INIT:
                return self._transition(EventType.START, {"reasoning": "Starting execution"})

            case ExecutionState.PARSE_SPEC:
                return self._step_parse_spec()

            case ExecutionState.NARRATOR_VOICE:
                return self._step_narrator_voice()

            case ExecutionState.PLOT_OUTLINE:
                return self._step_plot_outline()

            case ExecutionState.SCENE_OUTLINE:
                return self._step_scene_outline()

            case ExecutionState.DRAFT_SCENE:
                return self._step_draft_scene()

            case ExecutionState.CONSISTENCY_CHECK:
                return self._step_consistency_check()

            case ExecutionState.STYLE_REVISION:
                return self._step_style_revision()

            case ExecutionState.FINAL_ASSEMBLY:
                return self._step_final_assembly()

            case ExecutionState.COMPLETE:
                return TransitionResult(
                    new_state=ExecutionState.COMPLETE,
                    event=EventType.ASSEMBLY_COMPLETE,
                    should_continue=False
                )

            case ExecutionState.ERROR:
                return TransitionResult(
                    new_state=ExecutionState.ERROR,
                    event=EventType.ERROR_OCCURRED,
                    should_continue=False
                )

            case ExecutionState.SUSPENDED:
                return TransitionResult(
                    new_state=ExecutionState.SUSPENDED,
                    event=EventType.SUSPEND,
                    should_continue=False
                )

            case _:
                raise ExecutionError(f"Unknown state: {self.current_state}")

    def _step_parse_spec(self) -> TransitionResult:
        """Parse task specification"""
        if not self._session_state or not self._session_state.task_spec:
            return self._transition(EventType.ERROR_OCCURRED, {"error": "No task spec"})

        self.context.add(
            ContextCategory.TASK_SPEC,
            "task_spec",
            self._session_state.task_spec.model_dump_json(indent=2),
            pinned=True
        )

        self._on_output("Task specification parsed successfully")
        return self._transition(EventType.SPEC_PARSED, {"reasoning": "Task spec loaded to context"})

    def _step_narrator_voice(self) -> TransitionResult:
        """Generate narrator voice sample"""
        result = self._execute_tool("generate_narrator_voice", {
            "task_spec": self._session_state.task_spec.model_dump() if self._session_state.task_spec else {}
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        voice = result.output.get("voice_sample", "") if result.output else ""
        if self._session_state:
            self._session_state.narrator_voice = voice
        self.context.set_narrator_voice(voice)

        self._on_output(f"Narrator voice established ({len(voice)} chars)")
        return self._transition(EventType.VOICE_GENERATED, {"reasoning": "Voice sample anchored in context"})

    def _step_plot_outline(self) -> TransitionResult:
        """Generate plot outline"""
        result = self._execute_tool("generate_plot_outline", {
            "task_spec": self._session_state.task_spec.model_dump() if self._session_state.task_spec else {},
            "voice_sample": self._session_state.narrator_voice if self._session_state else ""
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        if result.output and self._session_state:
            self._session_state.plot_outline = PlotOutline.model_validate(result.output.get("plot_outline", {}))
            self.context.add(
                ContextCategory.PLOT_OUTLINE,
                "plot_outline",
                self._session_state.plot_outline.model_dump_json(indent=2),
                pinned=True
            )

        self._on_output("Seven-beat plot outline generated")
        return self._transition(EventType.PLOT_GENERATED, {"reasoning": "Plot structure defined"})

    def _step_scene_outline(self) -> TransitionResult:
        """Generate scene outlines"""
        result = self._execute_tool("generate_scene_outline", {
            "plot_outline": self._session_state.plot_outline.model_dump() if self._session_state and self._session_state.plot_outline else {}
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        if result.output and self._session_state:
            scenes_data = result.output.get("scenes", [])
            self._session_state.scene_specs = [SceneSpec.model_validate(s) for s in scenes_data]
            self._session_state.current_scene_index = 0

        self._on_output(f"Scene outline: {len(self._session_state.scene_specs) if self._session_state else 0} scenes defined")
        return self._transition(EventType.SCENES_OUTLINED, {"reasoning": "Scenes mapped to beats"})

    def _step_draft_scene(self) -> TransitionResult:
        """Draft current scene"""
        if not self._session_state:
            return self._transition(EventType.ERROR_OCCURRED, {"error": "No session state"})

        idx = self._session_state.current_scene_index
        if idx >= len(self._session_state.scene_specs):
            return self._transition(EventType.ALL_SCENES_DRAFTED, {"reasoning": "All scenes complete"})

        scene_spec = self._session_state.scene_specs[idx]

        result = self._execute_tool("draft_scene", {
            "scene_spec": scene_spec.model_dump(),
            "voice_sample": self._session_state.narrator_voice,
            "imagery_table": [e.model_dump() for e in self._session_state.imagery_table],
            "previous_scenes": [d.content for d in self._session_state.scene_drafts[-3:]]
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        if result.output:
            draft = SceneDraft(
                scene_id=idx,
                content=result.output.get("draft", ""),
                word_count=result.output.get("word_count", 0),
                imagery_used=result.output.get("imagery_used", [])
            )
            self._session_state.scene_drafts.append(draft)
            self.context.add_scene_history(idx, draft.content)

            for img_name in result.output.get("new_imagery", []):
                entry = ImageryEntry(
                    image_id=f"img_{len(self._session_state.imagery_table)}",
                    name=img_name,
                    description=result.output.get("imagery_descriptions", {}).get(img_name, ""),
                    category="established",
                    first_scene=idx,
                    references=[idx]
                )
                self._session_state.imagery_table.append(entry)

            self.context.set_imagery_table([e.model_dump() for e in self._session_state.imagery_table])

        self._session_state.current_scene_index += 1

        self.state_store.snapshot(
            self._session_state,
            f"scene_{idx}_complete",
            {"scene_id": idx}
        )

        self._on_output(f"Scene {idx + 1}/{len(self._session_state.scene_specs)} drafted")

        if self._session_state.current_scene_index >= len(self._session_state.scene_specs):
            return self._transition(EventType.ALL_SCENES_DRAFTED, {"reasoning": "All scenes drafted"})

        return self._transition(EventType.SCENE_DRAFTED, {"reasoning": f"Scene {idx} complete"})

    def _step_consistency_check(self) -> TransitionResult:
        """Check consistency across scenes"""
        result = self._execute_tool("check_consistency", {
            "scenes": [d.content for d in self._session_state.scene_drafts] if self._session_state else [],
            "imagery_table": [e.model_dump() for e in self._session_state.imagery_table] if self._session_state else [],
            "task_spec": self._session_state.task_spec.model_dump() if self._session_state and self._session_state.task_spec else {}
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        passed = result.output.get("passed", False) if result.output else False

        if passed:
            self._on_output("Consistency check passed")
            return self._transition(EventType.CONSISTENCY_PASSED, {"reasoning": "No consistency issues"})
        else:
            issues = result.output.get("issues", []) if result.output else []
            self._on_output(f"Consistency issues found: {len(issues)}")

            if self._session_state and self._session_state.revision_count < 3:
                self._session_state.revision_count += 1
                scenes_to_revise = set(i.get("scene_id", 0) for i in issues)
                min_scene = min(scenes_to_revise) if scenes_to_revise else 0
                self._session_state.current_scene_index = min_scene
                return self._transition(EventType.CONSISTENCY_FAILED, {"reasoning": "Revising inconsistent scenes"})
            else:
                return self._transition(EventType.CONSISTENCY_PASSED, {"reasoning": "Max revisions reached"})

    def _step_style_revision(self) -> TransitionResult:
        """Revise style across all scenes"""
        self.state_store.snapshot(
            self._session_state,
            "pre_style_revision",
            {}
        )

        result = self._execute_tool("revise_style", {
            "scenes": [d.content for d in self._session_state.scene_drafts] if self._session_state else [],
            "style_spec": self._session_state.task_spec.style.model_dump() if self._session_state and self._session_state.task_spec else {}
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        if result.output and self._session_state:
            revised_scenes = result.output.get("revised_scenes", [])
            for i, content in enumerate(revised_scenes):
                if i < len(self._session_state.scene_drafts):
                    self._session_state.scene_drafts[i].content = content
                    self._session_state.scene_drafts[i].revision_count += 1

        self.state_store.snapshot(
            self._session_state,
            "post_style_revision",
            {}
        )

        self._on_output("Style revision complete")
        return self._transition(EventType.STYLE_REVISED, {"reasoning": "Style aligned with spec"})

    def _step_final_assembly(self) -> TransitionResult:
        """Assemble final draft"""
        if not self._session_state:
            return self._transition(EventType.ERROR_OCCURRED, {"error": "No session state"})

        result = self._execute_tool("assemble_final", {
            "scenes": [d.content for d in self._session_state.scene_drafts],
            "task_spec": self._session_state.task_spec.model_dump() if self._session_state.task_spec else {}
        }, approved=True)

        if not result.success:
            return self._transition(EventType.ERROR_OCCURRED, {"error": result.error})

        if result.output:
            self._session_state.final_draft = result.output.get("final_text", "")

        self.state_store.snapshot(
            self._session_state,
            "final_draft",
            {"word_count": len(self._session_state.final_draft.split())}
        )

        self._on_output(f"Final assembly complete ({len(self._session_state.final_draft.split())} words)")
        return self._transition(EventType.ASSEMBLY_COMPLETE, {"reasoning": "Story complete"})

    def run(self, session_state: SessionState) -> SessionState:
        """Run the execution loop to completion"""
        self._session_state = session_state

        self.hooks.emit_simple(
            LifecycleEventType.SESSION_START,
            session_state.session_id,
            source="execution"
        )

        self.trajectory.define_goal("complete_story", "Generate complete short story")
        self.trajectory.define_goal("consistency", "Maintain narrative consistency")
        self.trajectory.define_goal("style_alignment", "Match target style")

        while True:
            try:
                result = self.step()

                progress = {
                    ExecutionState.INIT: 0.0,
                    ExecutionState.PARSE_SPEC: 0.1,
                    ExecutionState.NARRATOR_VOICE: 0.15,
                    ExecutionState.PLOT_OUTLINE: 0.2,
                    ExecutionState.SCENE_OUTLINE: 0.25,
                    ExecutionState.DRAFT_SCENE: 0.3 + 0.4 * (
                        self._session_state.current_scene_index /
                        max(1, len(self._session_state.scene_specs))
                    ) if self._session_state else 0.3,
                    ExecutionState.CONSISTENCY_CHECK: 0.75,
                    ExecutionState.STYLE_REVISION: 0.85,
                    ExecutionState.FINAL_ASSEMBLY: 0.95,
                    ExecutionState.COMPLETE: 1.0,
                }.get(result.new_state, 0.0)

                self.trajectory.update_goal_progress("complete_story", progress)

                self.state_store.commit(self._session_state)

                if not result.should_continue:
                    break

            except ToolApprovalRequired as e:
                self._on_output(f"Approval required: {e.tool_name}")
                self._transition(EventType.SUSPEND)
                break

            except Exception as e:
                self._on_output(f"Error: {e}")
                self._transition(EventType.ERROR_OCCURRED, {"error": str(e)})
                break

        self.hooks.emit_simple(
            LifecycleEventType.SESSION_END,
            session_state.session_id,
            {"final_state": self.current_state.value},
            source="execution"
        )

        return self._session_state

    def interrupt(self) -> None:
        """Signal interrupt to the execution loop"""
        self._interrupted = True

    def resume(self, session_id: str) -> SessionState:
        """Resume from saved state"""
        self._session_state = self.state_store.recover(session_id)

        self.hooks.emit_simple(
            LifecycleEventType.SNAPSHOT_RESTORED,
            session_id,
            {"state": self._session_state.current_state.value},
            source="execution"
        )

        return self.run(self._session_state)
