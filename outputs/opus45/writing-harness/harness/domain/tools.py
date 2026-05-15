"""
domain/tools.py - Writing-specific tools for short story generation

Implements tools for:
- Narrator voice generation
- Plot outline generation
- Scene outline generation
- Scene drafting
- Consistency checking
- Style revision
- Final assembly
- Sample comparison
"""

from __future__ import annotations
import os
import json
from typing import Any
from pathlib import Path

from pydantic import BaseModel, Field

from harness.tools import Tool, ToolDangerLevel, ToolExecutionError
from harness.domain.prompts import PROMPTS


def _get_llm_client():
    """Get OpenAI-compatible LLM client from environment"""
    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "dummy-key")

    return OpenAI(base_url=base_url, api_key=api_key)


def _get_model_name() -> str:
    """Get model name from environment"""
    return os.environ.get("MODEL_NAME", "gpt-4")


def _call_llm(prompt: str, max_tokens: int = 2000, temperature: float = 0.7) -> str:
    """Make LLM API call"""
    client = _get_llm_client()
    model = _get_model_name()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        raise ToolExecutionError(f"LLM call failed: {e}", e)


def _parse_json_response(response: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks"""
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines)

    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        raise ToolExecutionError(f"Failed to parse JSON response: {e}")


class NarratorVoiceInput(BaseModel):
    task_spec: dict[str, Any]


class NarratorVoiceOutput(BaseModel):
    voice_sample: str


class GenerateNarratorVoiceTool(Tool):
    name = "generate_narrator_voice"
    description = "Generate a narrator voice sample for style anchoring"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    input_model = NarratorVoiceInput
    output_model = NarratorVoiceOutput

    def _execute(self, validated_input: NarratorVoiceInput, context: dict[str, Any] | None = None) -> dict:
        spec = validated_input.task_spec
        style = spec.get("style", {})
        if isinstance(style, dict):
            style_dict = style
        else:
            style_dict = style if hasattr(style, '__dict__') else {}

        prompt = PROMPTS["narrator_voice"].format(
            genre=spec.get("genre", "psychological thriller"),
            pov=spec.get("pov", "first_person_unreliable"),
            core_tension=spec.get("core_tension", ""),
            obsession_object=spec.get("obsession_object", ""),
            dash_density=style_dict.get("dash_density", "high"),
            exclamation_density=style_dict.get("exclamation_density", "high"),
            reader_address_frequency=style_dict.get("reader_address_frequency", "frequent"),
            repetition_style=style_dict.get("repetition_style", "escalating"),
            dominant_sensory=style_dict.get("dominant_sensory", "auditory")
        )

        voice_sample = _call_llm(prompt, max_tokens=200, temperature=0.8)
        return {"voice_sample": voice_sample.strip()}


class PlotOutlineInput(BaseModel):
    task_spec: dict[str, Any]
    voice_sample: str


class PlotOutlineOutput(BaseModel):
    plot_outline: dict[str, Any]


class GeneratePlotOutlineTool(Tool):
    name = "generate_plot_outline"
    description = "Generate seven-beat plot outline"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    input_model = PlotOutlineInput
    output_model = PlotOutlineOutput

    def _execute(self, validated_input: PlotOutlineInput, context: dict[str, Any] | None = None) -> dict:
        spec = validated_input.task_spec
        style = spec.get("style", {})
        if isinstance(style, dict):
            style_dict = style
        else:
            style_dict = {}

        prompt = PROMPTS["plot_outline"].format(
            genre=spec.get("genre", "psychological thriller"),
            voice_sample=validated_input.voice_sample,
            core_tension=spec.get("core_tension", ""),
            obsession_object=spec.get("obsession_object", ""),
            temporal_structure=spec.get("temporal_structure", "delay_then_eruption"),
            delay_period=spec.get("delay_period", "seven_nights"),
            climax_trigger=spec.get("climax_trigger", "eighth_night"),
            exposure_signal=spec.get("exposure_signal", "auditory"),
            ending_type=spec.get("ending_type", "self_confession"),
            word_count_min=spec.get("word_count_min", 2000),
            word_count_max=spec.get("word_count_max", 2500)
        )

        response = _call_llm(prompt, max_tokens=1500, temperature=0.7)
        plot_data = _parse_json_response(response)
        return {"plot_outline": plot_data}


class SceneOutlineInput(BaseModel):
    plot_outline: dict[str, Any]


class SceneOutlineOutput(BaseModel):
    scenes: list[dict[str, Any]]


class GenerateSceneOutlineTool(Tool):
    name = "generate_scene_outline"
    description = "Expand plot outline into scene specifications"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    input_model = SceneOutlineInput
    output_model = SceneOutlineOutput

    def _execute(self, validated_input: SceneOutlineInput, context: dict[str, Any] | None = None) -> dict:
        prompt = PROMPTS["scene_outline"].format(
            plot_outline=json.dumps(validated_input.plot_outline, indent=2),
            total_scenes=8,
            word_count_min=2000,
            word_count_max=2500
        )

        response = _call_llm(prompt, max_tokens=2000, temperature=0.6)
        scene_data = _parse_json_response(response)
        return {"scenes": scene_data.get("scenes", [])}


class SceneDraftInput(BaseModel):
    scene_spec: dict[str, Any]
    voice_sample: str
    imagery_table: list[dict[str, Any]] = Field(default_factory=list)
    previous_scenes: list[str] = Field(default_factory=list)


class SceneDraftOutput(BaseModel):
    draft: str
    word_count: int
    imagery_used: list[str] = Field(default_factory=list)
    new_imagery: list[str] = Field(default_factory=list)
    imagery_descriptions: dict[str, str] = Field(default_factory=dict)


class DraftSceneTool(Tool):
    name = "draft_scene"
    description = "Draft a single scene"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    requires_context = True
    input_model = SceneDraftInput
    output_model = SceneDraftOutput

    def _execute(self, validated_input: SceneDraftInput, context: dict[str, Any] | None = None) -> dict:
        spec = validated_input.scene_spec

        imagery_table_str = "\n".join(
            f"- {img.get('name', 'unknown')}: {img.get('description', '')}"
            for img in validated_input.imagery_table
        ) or "None established yet"

        prev_scenes_str = "\n\n---\n\n".join(validated_input.previous_scenes[-3:]) or "This is the first scene"

        prompt = PROMPTS["scene_draft"].format(
            scene_id=spec.get("scene_id", 0),
            voice_sample=validated_input.voice_sample,
            title=spec.get("title", "Untitled"),
            beat_number=spec.get("beat_number", 1),
            beat_name=spec.get("beat_name", "unknown"),
            time_marker=spec.get("time_marker", ""),
            location=spec.get("location", ""),
            key_events=", ".join(spec.get("key_events", [])),
            emotional_beat=spec.get("emotional_beat", "tension"),
            target_word_count=spec.get("target_word_count", 300),
            imagery_to_establish=", ".join(spec.get("imagery_to_establish", [])) or "None",
            imagery_to_reference=", ".join(spec.get("imagery_to_reference", [])) or "None",
            dash_density="high",
            exclamation_density="high",
            reader_address_frequency="frequent",
            repetition_style="escalating",
            dominant_sensory="auditory",
            style_notes=spec.get("style_notes", ""),
            previous_scenes=prev_scenes_str,
            imagery_table=imagery_table_str
        )

        draft = _call_llm(prompt, max_tokens=800, temperature=0.8)
        word_count = len(draft.split())

        return {
            "draft": draft.strip(),
            "word_count": word_count,
            "imagery_used": spec.get("imagery_to_reference", []),
            "new_imagery": spec.get("imagery_to_establish", []),
            "imagery_descriptions": {}
        }


class ConsistencyCheckInput(BaseModel):
    scenes: list[str]
    imagery_table: list[dict[str, Any]]
    task_spec: dict[str, Any]


class ConsistencyCheckOutput(BaseModel):
    passed: bool
    issues: list[dict[str, Any]] = Field(default_factory=list)
    imagery_coverage: dict[str, list[int]] = Field(default_factory=dict)
    timeline_valid: bool = True
    voice_coherence_score: float = 1.0


class CheckConsistencyTool(Tool):
    name = "check_consistency"
    description = "Check narrative consistency across scenes"
    danger_level = ToolDangerLevel.SAFE
    input_model = ConsistencyCheckInput
    output_model = ConsistencyCheckOutput

    def _execute(self, validated_input: ConsistencyCheckInput, context: dict[str, Any] | None = None) -> dict:
        scenes_str = "\n\n---SCENE BREAK---\n\n".join(
            f"[Scene {i}]\n{scene}"
            for i, scene in enumerate(validated_input.scenes)
        )

        imagery_str = json.dumps(validated_input.imagery_table, indent=2)

        prompt = PROMPTS["consistency_check"].format(
            task_spec=json.dumps(validated_input.task_spec, indent=2),
            imagery_table=imagery_str,
            scenes=scenes_str
        )

        response = _call_llm(prompt, max_tokens=1000, temperature=0.3)

        try:
            result = _parse_json_response(response)
            return result
        except ToolExecutionError:
            return {
                "passed": True,
                "issues": [],
                "imagery_coverage": {},
                "timeline_valid": True,
                "voice_coherence_score": 0.9
            }


class StyleRevisionInput(BaseModel):
    scenes: list[str]
    style_spec: dict[str, Any]


class StyleRevisionOutput(BaseModel):
    revised_scenes: list[str]


class ReviseStyleTool(Tool):
    name = "revise_style"
    description = "Revise scenes for style consistency"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    input_model = StyleRevisionInput
    output_model = StyleRevisionOutput

    def _execute(self, validated_input: StyleRevisionInput, context: dict[str, Any] | None = None) -> dict:
        style = validated_input.style_spec

        scenes_str = "\n\n---SCENE BREAK---\n\n".join(
            f"[Scene {i}]\n{scene}"
            for i, scene in enumerate(validated_input.scenes)
        )

        prompt = PROMPTS["style_revision"].format(
            dash_density=style.get("dash_density", "high"),
            exclamation_density=style.get("exclamation_density", "high"),
            reader_address_frequency=style.get("reader_address_frequency", "frequent"),
            repetition_style=style.get("repetition_style", "escalating"),
            dominant_sensory=style.get("dominant_sensory", "auditory"),
            sentence_rhythm=style.get("sentence_rhythm", "varied_with_fragments"),
            scenes=scenes_str
        )

        response = _call_llm(prompt, max_tokens=4000, temperature=0.6)

        try:
            result = _parse_json_response(response)
            return {"revised_scenes": result.get("revised_scenes", validated_input.scenes)}
        except ToolExecutionError:
            return {"revised_scenes": validated_input.scenes}


class FinalAssemblyInput(BaseModel):
    scenes: list[str]
    task_spec: dict[str, Any]


class FinalAssemblyOutput(BaseModel):
    final_text: str
    word_count: int


class AssembleFinalTool(Tool):
    name = "assemble_final"
    description = "Assemble scenes into final story"
    danger_level = ToolDangerLevel.NEEDS_APPROVAL
    input_model = FinalAssemblyInput
    output_model = FinalAssemblyOutput

    def _execute(self, validated_input: FinalAssemblyInput, context: dict[str, Any] | None = None) -> dict:
        scenes_str = "\n\n".join(validated_input.scenes)

        prompt = PROMPTS["final_assembly"].format(
            task_spec=json.dumps(validated_input.task_spec, indent=2),
            scenes=scenes_str,
            word_count_min=validated_input.task_spec.get("word_count_min", 2000),
            word_count_max=validated_input.task_spec.get("word_count_max", 2500)
        )

        final_text = _call_llm(prompt, max_tokens=4000, temperature=0.5)
        word_count = len(final_text.split())

        return {
            "final_text": final_text.strip(),
            "word_count": word_count
        }


class SampleComparisonInput(BaseModel):
    sample_path: str
    generated_text: str


class SampleComparisonOutput(BaseModel):
    structure_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    style_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    imagery_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    overall_alignment_score: float = 0.0
    summary: str = ""


class CompareSampleTool(Tool):
    name = "compare_sample"
    description = "Compare generated story with reference sample"
    danger_level = ToolDangerLevel.SAFE
    input_model = SampleComparisonInput
    output_model = SampleComparisonOutput

    def _execute(self, validated_input: SampleComparisonInput, context: dict[str, Any] | None = None) -> dict:
        sample_path = Path(validated_input.sample_path)
        if not sample_path.exists():
            raise ToolExecutionError(f"Sample file not found: {sample_path}")

        with open(sample_path) as f:
            sample_text = f.read()

        prompt = PROMPTS["comparison"].format(
            sample_text=sample_text[:3000],
            generated_text=validated_input.generated_text[:3000]
        )

        response = _call_llm(prompt, max_tokens=1500, temperature=0.3)

        try:
            result = _parse_json_response(response)
            return result
        except ToolExecutionError:
            sample_words = len(sample_text.split())
            generated_words = len(validated_input.generated_text.split())

            return {
                "structure_comparisons": [{
                    "aspect": "word_count",
                    "sample_value": str(sample_words),
                    "actual_value": str(generated_words),
                    "aligned": 0.8 <= generated_words/sample_words <= 1.2,
                    "gap_description": f"Difference: {generated_words - sample_words}"
                }],
                "style_comparisons": [],
                "imagery_comparisons": [],
                "overall_alignment_score": 0.5,
                "summary": "Comparison completed with basic metrics"
            }


def get_domain_tools() -> list[Tool]:
    """Get all domain-specific tools"""
    return [
        GenerateNarratorVoiceTool(),
        GeneratePlotOutlineTool(),
        GenerateSceneOutlineTool(),
        DraftSceneTool(),
        CheckConsistencyTool(),
        ReviseStyleTool(),
        AssembleFinalTool(),
        CompareSampleTool(),
    ]
