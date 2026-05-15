from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from ..tools import ToolBase, ToolCallResult, ToolResultStatus
from ..schemas import (
    NarratorProfile, PlotOutline, Scene, ConsistencyReport,
    ImageryEntry, TaskSpec
)
import openai
import os
import json
import re


class NarratorProfileInput(BaseModel):
    task_spec: Dict[str, Any]


class GenerateNarratorProfileTool(ToolBase):
    """Tool to generate narrator profile based on task specification"""

    def __init__(self):
        super().__init__()
        self.name = "generate_narrator_profile"
        self.description = "Generate narrator voice profile based on task specification"
        self.input_schema = NarratorProfileInput
        self.requires_approval = False

    def execute(self, task_spec: Dict[str, Any], **kwargs) -> ToolCallResult:
        """Generate narrator profile using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        prompt = f"""Based on this story task specification, create a narrator profile:

Task Specification:
{json.dumps(task_spec, indent=2)}

Create a 50-100 word voice sample that captures the narrator's voice, and provide core motivation and speaking style.
Return ONLY valid JSON with no extra text:
{{
    "voice_sample": "<50-100 word sample of narrator's voice>",
    "perspective": "{task_spec.get('perspective', 'first_person')}",
    "unreliable": true,
    "core_motivation": "<core motivation/obsession>",
    "speaking_style": {{
        "sentence_length": "<short/medium/long>",
        "punctuation": "<exclamation/dashes/repetition>",
        "tone": "<tense/paranoid/confident/etc>"
    }}
}}
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            content = response.choices[0].message.content
            # Clean up JSON response
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            profile_data = json.loads(content)

            return ToolCallResult(
                status=ToolResultStatus.SUCCESS,
                data=profile_data
            )

        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Failed to generate narrator profile: {str(e)}"
            )


class PlotOutlineInput(BaseModel):
    task_spec: Dict[str, Any]
    narrator_profile: Optional[Dict[str, Any]] = None


class GeneratePlotOutlineTool(ToolBase):
    """Tool to generate plot outline based on task specification"""

    def __init__(self):
        super().__init__()
        self.name = "generate_plot_outline"
        self.description = "Generate plot outline based on task specification and narrator profile"
        self.input_schema = PlotOutlineInput
        self.requires_approval = False

    def execute(self, task_spec: Dict[str, Any], narrator_profile: Optional[Dict[str, Any]] = None, **kwargs) -> ToolCallResult:
        """Generate plot outline using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        prompt = f"""Based on this story task specification and narrator profile, create a detailed plot outline with the following sections:
- setup_beats
- delay_segment (7 nights of buildup)
- climax
- concealment
- exposure
- confession

Task Specification:
{json.dumps(task_spec, indent=2)}

Narrator Profile:
{json.dumps(narrator_profile, indent=2) if narrator_profile else "Not provided"}

Return ONLY valid JSON with no extra text:
{{
    "title": "<story title>",
    "core_tension": "<central conflict>",
    "setup_beats": [<list of setup beats>],
    "delay_segment": [<list of delay segment beats>],
    "climax": [<list of climax beats>],
    "concealment": [<list of concealment beats>],
    "exposure": [<list of exposure beats>],
    "confession": [<list of confession beats>]
}}
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            content = response.choices[0].message.content
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            outline_data = json.loads(content)

            return ToolCallResult(
                status=ToolResultStatus.SUCCESS,
                data=outline_data
            )

        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Failed to generate plot outline: {str(e)}"
            )


class SceneOutlineInput(BaseModel):
    plot_outline: Dict[str, Any]
    task_spec: Dict[str, Any]


class GenerateSceneOutlineTool(ToolBase):
    """Tool to generate scene-level outline from plot outline"""

    def __init__(self):
        super().__init__()
        self.name = "generate_scene_outline"
        self.description = "Generate scene-level outline from plot outline"
        self.input_schema = SceneOutlineInput
        self.requires_approval = False

    def execute(self, plot_outline: Dict[str, Any], task_spec: Dict[str, Any], **kwargs) -> ToolCallResult:
        """Generate scene outlines using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        prompt = f"""Based on this plot outline and task specification, create a scene-level outline with 5-10 scenes.

For each scene, provide:
- scene_id: sequential number
- title: short scene title
- pov: point of view
- time_position: when the scene takes place
- key_imagery: list of key imagery for the scene
- beats: list of key plot beats for the scene

Plot Outline:
{json.dumps(plot_outline, indent=2)}

Task Specification:
{json.dumps(task_spec, indent=2)}

Return ONLY valid JSON with no extra text:
{{
    "scenes": [
        {{
            "scene_id": 1,
            "title": "<scene title>",
            "pov": "{task_spec.get('perspective', 'first_person')}",
            "time_position": "<timing>",
            "key_imagery": [<list of imagery terms>],
            "beats": [<list of plot beats>]
        }},
        ...
    ]
}}
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            content = response.choices[0].message.content
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            scene_data = json.loads(content)

            return ToolCallResult(
                status=ToolResultStatus.SUCCESS,
                data=scene_data
            )

        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Failed to generate scene outline: {str(e)}"
            )


class DraftSceneInput(BaseModel):
    scene: Dict[str, Any]
    context: str
    narrator_voice: str


class DraftSceneTool(ToolBase):
    """Tool to draft a single scene"""

    def __init__(self):
        super().__init__()
        self.name = "draft_scene"
        self.description = "Draft a single scene based on scene outline and context"
        self.input_schema = DraftSceneInput
        self.requires_approval = True

    def execute(self, scene: Dict[str, Any], context: str, narrator_voice: str, **kwargs) -> ToolCallResult:
        """Draft a scene using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        prompt = f"""Write a scene based on the following requirements:

Scene Details:
{json.dumps(scene, indent=2)}

{narrator_voice}

Context:
{context}

Write the full scene content in the voice of the narrator. Include the key imagery specified.
Return ONLY the scene text with no extra commentary:
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                stream=True
            )

            # Stream the response
            full_content = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    full_content += chunk.choices[0].delta.content

            # Extract imagery from the scene
            imagery_prompt = f"""Extract key auditory and thematic imagery terms from this text:

{full_content}

Return ONLY a comma-separated list of imagery terms, no extra text:
"""
            imagery_response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": imagery_prompt}],
                temperature=0.3
            )
            imagery_terms = imagery_response.choices[0].message.content.strip().split(",")
            imagery_entries = [
                ImageryEntry(
                    category="auditory" if "sound" in term.lower() or "noise" in term.lower() or "heart" in term.lower() else "visual",
                    term=term.strip(),
                    context=f"Scene {scene.get('scene_id', 1)}: {scene.get('title', '')}"
                ).dict()
                for term in imagery_terms if term.strip()
            ]

            return ToolCallResult(
                status=ToolResultStatus.SUCCESS,
                data={
                    "content": full_content,
                    "imagery_used": imagery_entries
                }
            )

        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Failed to draft scene: {str(e)}"
            )


class ConsistencyCheckInput(BaseModel):
    scenes: List[str]
    established_imagery: Dict[str, Dict[str, Any]]
    task_spec: Dict[str, Any]


class CheckConsistencyTool(ToolBase):
    """Tool to check consistency of scenes"""

    def __init__(self):
        super().__init__()
        self.name = "check_consistency"
        self.description = "Check consistency of scenes for imagery, timeline, and constraint violations"
        self.input_schema = ConsistencyCheckInput
        self.requires_approval = False

    def execute(self, scenes: List[str], established_imagery: Dict[str, Dict[str, Any]], task_spec: Dict[str, Any], **kwargs) -> ToolCallResult:
        """Check scene consistency using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        scenes_text = "\n\n".join([f"Scene {i+1}:\n{scene}" for i, scene in enumerate(scenes)])

        prompt = f"""Check the following story scenes for consistency:

1. Imagery consistency: Are there any inconsistent or contradictory imagery terms?
2. Timeline consistency: Does the timeline follow the expected progression?
3. Constraint violations: Do any scenes violate the task constraints?

Task Constraints:
{json.dumps(task_spec.get('key_constraints', {}), indent=2)}

Current Established Imagery:
{json.dumps(established_imagery, indent=2)}

Scenes to check:
{scenes_text}

Return ONLY valid JSON with no extra text:
{{
    "consistent": true/false,
    "issues": [<list of general issues>],
    "imagery_discrepancies": [<list of imagery issues>],
    "timeline_discrepancies": [<list of timeline issues>],
    "constraint_violations": [<list of constraint violations>]
}}
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            content = response.choices[0].message.content
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            consistency_data = json.loads(content)

            return ToolCallResult(
                status=ToolResultStatus.SUCCESS,
                data=consistency_data
            )

        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Failed to check consistency: {str(e)}"
            )


class StyleRevisionInput(BaseModel):
    scenes: List[Dict[str, Any]]
    style_requirements: Dict[str, Any]
    narrator_voice: str


class ReviseStyleTool(ToolBase):
    """Tool to revise style of all scenes"""

    def __init__(self):
        super().__init__()
        self.name = "revise_style"
        self.description = "Revise style of scenes to match requirements"
        self.input_schema = StyleRevisionInput
        self.requires_approval = True

    def execute(self, scenes: List[Dict[str, Any]], style_requirements: Dict[str, Any], narrator_voice: str, **kwargs) -> ToolCallResult:
        """Revise scene style using LLM"""
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        revised_scenes = []

        for scene in scenes:
            prompt = f"""Revise this scene to match the following style requirements:

{narrator_voice}

Style Requirements:
{json.dumps(style_requirements, indent=2)}

Original Scene:
{scene.get('content', '')}

Return ONLY the revised scene text with no extra commentary:
"""

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            revised_content = response.choices[0].message.content
            revised_scene = scene.copy()
            revised_scene["content"] = revised_content
            revised_scenes.append(revised_scene)

        return ToolCallResult(
            status=ToolResultStatus.SUCCESS,
            data={"scenes": revised_scenes}
        )


class AssembleFinalInput(BaseModel):
    scenes: List[Dict[str, Any]]
    task_spec: Dict[str, Any]


class AssembleFinalManuscriptTool(ToolBase):
    """Tool to assemble final manuscript from scenes"""

    def __init__(self):
        super().__init__()
        self.name = "assemble_final_manuscript"
        self.description = "Assemble final manuscript from completed scenes"
        self.input_schema = AssembleFinalInput
        self.requires_approval = False

    def execute(self, scenes: List[Dict[str, Any]], task_spec: Dict[str, Any], **kwargs) -> ToolCallResult:
        """Assemble final manuscript"""
        # Combine scene content
        full_text = "\n\n".join([scene.get('content', '') for scene in scenes if scene.get('content')])

        # Generate title
        client = openai.OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )

        model = os.environ.get("MODEL_NAME", "gpt-3.5-turbo")

        title_prompt = f"""Generate a compelling title for this story based on the task specification and content:

Task Specification:
{json.dumps(task_spec, indent=2)}

Content:
{full_text[:500]}...

Return ONLY the title with no extra text:
"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": title_prompt}],
                temperature=0.7
            )

            title = response.choices[0].message.content.strip()
            title = re.sub(r'^"', '', title)
            title = re.sub(r'"$', '', title)

        except Exception:
            title = "Generated Story"

        return ToolCallResult(
            status=ToolResultStatus.SUCCESS,
            data={
                "manuscript": full_text,
                "title": title,
                "scene_count": len(scenes)
            }
        )


class CompareToSampleInput(BaseModel):
    manuscript: str
    sample_path: str


class CompareToSampleTool(ToolBase):
    """Tool to compare generated manuscript to sample story"""

    def __init__(self):
        super().__init__()
        self.name = "compare_to_sample"
        self.description = "Compare generated manuscript to the sample story"
        self.input_schema = CompareToSampleInput
        self.requires_approval = False

    def execute(self, manuscript: str, sample_path: str = "samples/the_tell_tale_heart.txt", **kwargs) -> ToolCallResult:
        """Compare manuscript to sample"""
        if not os.path.exists(sample_path):
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Sample file not found at {sample_path}"
            )

        with open(sample_path, "r", encoding="utf-8") as f:
            sample_text = f.read()

        # Simple word count comparison
        sample_words = len(sample_text.split())
        actual_words = len(manuscript.split())

        return ToolCallResult(
            status=ToolResultStatus.SUCCESS,
            data={
                "sample_word_count": sample_words,
                "actual_word_count": actual_words,
                "word_count_difference": abs(actual_words - sample_words),
                "sample_path": sample_path,
                "summary": f"Word count: {actual_words} vs sample: {sample_words}"
            }
        )