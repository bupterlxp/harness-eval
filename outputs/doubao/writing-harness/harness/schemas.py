from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class StoryGenre(str, Enum):
    PSYCHOLOGICAL_THRILLER = "psychological_thriller"
    GOTHIC = "gothic"
    HORROR = "horror"
    MYSTERY = "mystery"
    FANTASY = "fantasy"
    LITERARY = "literary"


class Perspective(str, Enum):
    FIRST_PERSON = "first_person"
    SECOND_PERSON = "second_person"
    THIRD_PERSON_LIMITED = "third_person_limited"
    THIRD_PERSON_OMNISCIENT = "third_person_omniscient"


class ImageryEntry(BaseModel):
    category: str = Field(description="Category of imagery (e.g., 'auditory', 'visual', 'tactile')")
    term: str = Field(description="Specific imagery term/phrase")
    context: str = Field(description="Where this imagery was first introduced")
    usage_count: int = Field(default=1, description="Number of times this imagery has been used")


class Scene(BaseModel):
    scene_id: int = Field(description="Unique identifier for the scene")
    title: str = Field(description="Short title/description of the scene")
    pov: Perspective = Field(description="Point of view for this scene")
    time_position: str = Field(description="Timing of the scene (e.g., 'midnight, 8th night')")
    key_imagery: List[str] = Field(default_factory=list, description="Key imagery for this scene")
    beats: List[str] = Field(default_factory=list, description="Key plot beats for this scene")
    content: Optional[str] = Field(default=None, description="Generated content for the scene")


class PlotOutline(BaseModel):
    title: str = Field(description="Story title")
    core_tension: str = Field(description="Central conflict/tension")
    setup_beats: List[str] = Field(default_factory=list, description="Setup/introduction beats")
    delay_segment: List[str] = Field(default_factory=list, description="Delayed buildup beats (7 nights)")
    climax: List[str] = Field(default_factory=list, description="Climax/homicide beats")
    concealment: List[str] = Field(default_factory=list, description="Aftermath/concealment beats")
    exposure: List[str] = Field(default_factory=list, description="Confrontation/exposure beats")
    confession: List[str] = Field(default_factory=list, description="Final confession beats")


class TaskSpec(BaseModel):
    genre: List[StoryGenre] = Field(description="Story genres")
    length_words: tuple[int, int] = Field(description="Target word count range")
    perspective: Perspective = Field(description="Narrative perspective")
    core_tension: str = Field(description="Central conflict/tension")
    key_constraints: Dict[str, Any] = Field(default_factory=dict, description="Key story constraints")
    style_requirements: Dict[str, Any] = Field(default_factory=dict, description="Style guidelines")
    raw_input: str = Field(default="", description="Original raw task input")


class NarratorProfile(BaseModel):
    voice_sample: str = Field(description="50-100 word sample of narrator's voice")
    perspective: Perspective = Field(description="Narrative perspective")
    unreliable: bool = Field(default=True, description="Whether narrator is unreliable")
    core_motivation: str = Field(description="Core motivation/obsession")
    speaking_style: Dict[str, Any] = Field(default_factory=dict, description="Style characteristics")


class ConsistencyReport(BaseModel):
    consistent: bool = Field(default=True, description="Whether content is consistent")
    issues: List[str] = Field(default_factory=list, description="List of consistency issues found")
    imagery_discrepancies: List[str] = Field(default_factory=list, description="Imagery consistency issues")
    timeline_discrepancies: List[str] = Field(default_factory=list, description="Timeline inconsistencies")
    constraint_violations: List[str] = Field(default_factory=list, description="Violations of key constraints")


class GenerationState(str, Enum):
    INITIALIZED = "initialized"
    PARSED_TASK = "parsed_task"
    GENERATED_NARRATOR = "generated_narrator"
    GENERATED_PLOT = "generated_plot"
    GENERATED_SCENES = "generated_scenes"
    DRAFTING_SCENES = "drafting_scenes"
    CHECKING_CONSISTENCY = "checking_consistency"
    REVISING_STYLE = "revising_style"
    ASSEMBLING_FINAL = "assembling_final"
    COMPLETED = "completed"
    FAILED = "failed"


class TrajectoryEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    state: GenerationState
    step_description: str
    context_snapshot: Optional[Dict[str, Any]] = None
    tool_call: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None


class SessionInfo(BaseModel):
    session_id: UUID = Field(description="Unique session identifier")
    start_time: datetime = Field(default_factory=datetime.now)
    last_updated: datetime = Field(default_factory=datetime.now)
    current_state: GenerationState = GenerationState.INITIALIZED
    task_spec: Optional[TaskSpec] = None
    current_scene_id: int = Field(default=0)


class DiffReportEntry(BaseModel):
    category: str = Field(description="Category of diff (structure, style, imagery)")
    sample_feature: str = Field(description="Feature from the sample story")
    actual_performance: str = Field(description="Actual performance in generated story")
    difference: str = Field(description="Description of differences")
    component_responsible: Optional[str] = Field(default=None, description="Which component caused the difference")


class DiffReport(BaseModel):
    total_entries: int = Field(default=0)
    matching_entries: int = Field(default=0)
    differing_entries: List[DiffReportEntry] = Field(default_factory=list)
    summary: str = Field(default="", description="Summary of the diff report")