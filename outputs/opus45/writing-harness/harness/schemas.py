"""
schemas.py - All Pydantic models for the harness

Defines: state enums, events, trajectory records, tool IO schemas,
task specifications, scenes, and imagery entries.
"""

from __future__ import annotations
from enum import Enum
from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field


class ExecutionState(str, Enum):
    """State machine states for E (Execution Loop)"""
    INIT = "init"
    PARSE_SPEC = "parse_spec"
    NARRATOR_VOICE = "narrator_voice"
    PLOT_OUTLINE = "plot_outline"
    SCENE_OUTLINE = "scene_outline"
    DRAFT_SCENE = "draft_scene"
    CONSISTENCY_CHECK = "consistency_check"
    STYLE_REVISION = "style_revision"
    FINAL_ASSEMBLY = "final_assembly"
    COMPLETE = "complete"
    ERROR = "error"
    SUSPENDED = "suspended"


class EventType(str, Enum):
    """Event types that trigger state transitions"""
    START = "start"
    SPEC_PARSED = "spec_parsed"
    VOICE_GENERATED = "voice_generated"
    PLOT_GENERATED = "plot_generated"
    SCENES_OUTLINED = "scenes_outlined"
    SCENE_DRAFTED = "scene_drafted"
    ALL_SCENES_DRAFTED = "all_scenes_drafted"
    CONSISTENCY_PASSED = "consistency_passed"
    CONSISTENCY_FAILED = "consistency_failed"
    STYLE_REVISED = "style_revised"
    ASSEMBLY_COMPLETE = "assembly_complete"
    ERROR_OCCURRED = "error_occurred"
    SUSPEND = "suspend"
    RESUME = "resume"
    USER_INTERRUPT = "user_interrupt"


class ToolDangerLevel(str, Enum):
    """Danger classification for tools"""
    SAFE = "safe"
    NEEDS_APPROVAL = "needs_approval"


class StyleSpec(BaseModel):
    """Style specification for writing"""
    dash_density: str = Field(default="high", description="Frequency of em-dashes")
    exclamation_density: str = Field(default="high", description="Frequency of exclamation marks")
    reader_address_frequency: str = Field(default="frequent", description="How often to address reader directly")
    repetition_style: str = Field(default="escalating", description="Pattern of word/phrase repetition")
    dominant_sensory: str = Field(default="auditory", description="Primary sensory mode (auditory/visual/etc)")
    sentence_rhythm: str = Field(default="varied_with_fragments", description="Sentence length pattern")


class TaskSpec(BaseModel):
    """Complete task specification parsed from user input"""
    genre: str = Field(..., description="Genre (e.g., 'psychological thriller', 'gothic')")
    word_count_min: int = Field(default=2000, description="Minimum word count")
    word_count_max: int = Field(default=2500, description="Maximum word count")
    pov: str = Field(default="first_person_unreliable", description="Point of view")
    core_tension: str = Field(..., description="Central dramatic tension")
    obsession_object: str = Field(..., description="The irrational fixation object")
    temporal_structure: str = Field(default="delay_then_eruption", description="Time structure pattern")
    delay_period: str = Field(default="seven_nights", description="Duration of delay/stalking period")
    climax_trigger: str = Field(default="eighth_night", description="What triggers the climax")
    concealment_method: str = Field(default="", description="How the crime is hidden")
    exposure_signal: str = Field(default="auditory", description="Sensory signal that causes breakdown")
    ending_type: str = Field(default="self_confession", description="How the story ends")
    style: StyleSpec = Field(default_factory=StyleSpec)
    raw_input: str = Field(default="", description="Original user input text")


class ImageryEntry(BaseModel):
    """An entry in the imagery table tracking established images"""
    image_id: str = Field(..., description="Unique identifier for this image")
    name: str = Field(..., description="Short name (e.g., 'vulture_eye', 'heartbeat')")
    description: str = Field(..., description="Full description of the image")
    category: str = Field(..., description="Category: obsession_object / sensory_signal / metaphor / setting")
    first_scene: int = Field(..., description="Scene index where first introduced")
    references: list[int] = Field(default_factory=list, description="Scene indices where referenced")
    metaphor_chain: list[str] = Field(default_factory=list, description="Related metaphors in chain")


class PlotBeat(BaseModel):
    """A single beat in the seven-beat plot structure"""
    beat_number: int = Field(..., ge=1, le=7)
    name: str = Field(..., description="Beat name (e.g., 'obsession_establishment')")
    description: str = Field(..., description="What happens in this beat")
    target_word_ratio: float = Field(..., description="Target proportion of total word count")
    key_imagery: list[str] = Field(default_factory=list, description="Key images to establish/reference")
    emotional_arc: str = Field(default="", description="Emotional trajectory in this beat")


class PlotOutline(BaseModel):
    """Seven-beat plot outline"""
    beats: list[PlotBeat] = Field(..., min_length=7, max_length=7)
    obsession_object: str
    trigger_event: str
    concealment_method: str
    exposure_signal: str
    confession_moment: str


class SceneSpec(BaseModel):
    """Specification for a single scene"""
    scene_id: int = Field(..., description="Scene index (0-based)")
    beat_number: int = Field(..., description="Which plot beat this belongs to")
    title: str = Field(..., description="Short scene title")
    pov: str = Field(default="narrator", description="POV character")
    time_marker: str = Field(default="", description="When this scene occurs")
    location: str = Field(default="", description="Where this scene occurs")
    key_events: list[str] = Field(default_factory=list, description="Main events in scene")
    imagery_to_establish: list[str] = Field(default_factory=list, description="New images to introduce")
    imagery_to_reference: list[str] = Field(default_factory=list, description="Existing images to callback")
    target_word_count: int = Field(default=300, description="Target words for this scene")
    emotional_beat: str = Field(default="", description="Emotional note to hit")
    style_notes: str = Field(default="", description="Specific style instructions for this scene")


class SceneDraft(BaseModel):
    """A drafted scene"""
    scene_id: int
    content: str
    word_count: int
    imagery_used: list[str] = Field(default_factory=list)
    revision_count: int = Field(default=0)


class ConsistencyIssue(BaseModel):
    """A consistency problem found during checking"""
    issue_type: str = Field(..., description="Type: imagery_drift / timeline_error / voice_shift / reference_missing")
    severity: str = Field(..., description="critical / warning / suggestion")
    scene_id: int
    description: str
    suggested_fix: str = Field(default="")


class ConsistencyReport(BaseModel):
    """Report from consistency checking"""
    passed: bool
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    imagery_coverage: dict[str, list[int]] = Field(default_factory=dict, description="Image -> scenes where used")
    timeline_valid: bool = Field(default=True)
    voice_coherence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class ComparisonDimension(BaseModel):
    """A single dimension of comparison with sample"""
    dimension: str = Field(..., description="structure / style / imagery")
    aspect: str = Field(..., description="Specific aspect being compared")
    sample_value: str = Field(..., description="Value in reference sample")
    actual_value: str = Field(..., description="Value in generated output")
    aligned: bool = Field(..., description="Whether values align")
    gap_description: str = Field(default="", description="Description of gap if not aligned")
    component_attribution: str = Field(default="", description="Which component (E/T/C/S/L/V) is responsible")


class ComparisonReport(BaseModel):
    """Full comparison report with sample"""
    structure_comparisons: list[ComparisonDimension] = Field(default_factory=list)
    style_comparisons: list[ComparisonDimension] = Field(default_factory=list)
    imagery_comparisons: list[ComparisonDimension] = Field(default_factory=list)
    trajectory_comparisons: list[ComparisonDimension] = Field(default_factory=list)
    overall_alignment_score: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = Field(default="")


class TrajectoryEntry(BaseModel):
    """V3-level trajectory record with intermediate reasoning and context snapshot"""
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: str
    step_number: int
    state_before: ExecutionState
    state_after: ExecutionState
    event: EventType
    tool_called: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output_summary: str = Field(default="")
    reasoning: str = Field(default="", description="Intermediate reasoning for this step")
    context_snapshot: dict[str, Any] = Field(default_factory=dict, description="Relevant context state")
    goal_progress: dict[str, float] = Field(default_factory=dict, description="Progress on sub-goals (0-1)")
    error: str | None = None


class SessionState(BaseModel):
    """Complete session state for persistence"""
    session_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    current_state: ExecutionState = Field(default=ExecutionState.INIT)
    task_spec: TaskSpec | None = None
    narrator_voice: str = Field(default="")
    plot_outline: PlotOutline | None = None
    scene_specs: list[SceneSpec] = Field(default_factory=list)
    scene_drafts: list[SceneDraft] = Field(default_factory=list)
    imagery_table: list[ImageryEntry] = Field(default_factory=list)
    current_scene_index: int = Field(default=0)
    consistency_reports: list[ConsistencyReport] = Field(default_factory=list)
    final_draft: str = Field(default="")
    revision_count: int = Field(default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSchema(BaseModel):
    """Schema definition for a tool"""
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    danger_level: ToolDangerLevel = Field(default=ToolDangerLevel.SAFE)
    requires_context: bool = Field(default=False)


class ToolResult(BaseModel):
    """Result from tool execution"""
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HookEvent(BaseModel):
    """Event passed to lifecycle hooks"""
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.now)
    session_id: str
    state: ExecutionState
    data: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    """Request for user approval"""
    request_id: str
    tool_name: str
    tool_args: dict[str, Any]
    reason: str
    risk_description: str
