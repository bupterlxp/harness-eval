"""Tool Registry module for creative writing tools.

Provides tools for plot planning, scene drafting, consistency checking,
and revision operations. Each tool has a defined input/output schema.
"""

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI


def get_llm_client() -> OpenAI:
    """Get configured OpenAI client."""
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )


def get_model_name() -> str:
    """Get model name from environment."""
    return os.environ.get("MODEL_NAME", "gpt-4")


def call_llm(prompt: str, system_prompt: str = "", temperature: float = 0.7) -> str:
    """Call LLM with given prompts."""
    client = get_llm_client()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=get_model_name(),
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


@dataclass
class ToolInput:
    """Base class for tool inputs."""
    pass


@dataclass
class ToolOutput:
    """Base class for tool outputs."""
    success: bool = True
    error: str = ""


@dataclass
class ParseTaskInput(ToolInput):
    """Input for task parsing."""
    prompt: str = ""


@dataclass
class ParseTaskOutput(ToolOutput):
    """Output from task parsing."""
    genre: str = ""
    premise: str = ""
    target_words: int = 1000
    pov: str = "third-person-limited"
    style_directives: list[str] = field(default_factory=list)
    structural_constraints: list[str] = field(default_factory=list)


@dataclass
class PlanPlotInput(ToolInput):
    """Input for plot planning."""
    premise: str = ""
    genre: str = ""
    target_words: int = 1000
    structural_constraints: list[str] = field(default_factory=list)


@dataclass
class PlanPlotOutput(ToolOutput):
    """Output from plot planning."""
    beats: list[str] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    character_arcs: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class DraftSceneInput(ToolInput):
    """Input for scene drafting."""
    scene_id: int = 0
    scene_summary: str = ""
    target_words: int = 500
    context_injection: str = ""
    prior_content: str = ""


@dataclass
class DraftSceneOutput(ToolOutput):
    """Output from scene drafting."""
    content: str = ""
    word_count: int = 0
    entities_mentioned: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CheckConsistencyInput(ToolInput):
    """Input for consistency checking."""
    scene_content: str = ""
    scene_id: int = 0
    entity_registry: dict[str, Any] = field(default_factory=dict)
    prior_content: str = ""
    style_anchor: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckConsistencyOutput(ToolOutput):
    """Output from consistency checking."""
    is_consistent: bool = True
    issues: list[str] = field(default_factory=list)
    entity_updates: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "none"


@dataclass
class ReviseSceneInput(ToolInput):
    """Input for scene revision."""
    scene_content: str = ""
    scene_id: int = 0
    revision_type: str = "fix_issues"
    issues: list[str] = field(default_factory=list)
    context_injection: str = ""
    target_words: int | None = None


@dataclass
class ReviseSceneOutput(ToolOutput):
    """Output from scene revision."""
    revised_content: str = ""
    word_count: int = 0
    changes_made: list[str] = field(default_factory=list)


class WritingTool(ABC):
    """Abstract base class for writing tools."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(self, input_data: ToolInput) -> ToolOutput:
        """Execute the tool with given input."""
        pass

    def get_schema(self) -> dict[str, Any]:
        """Get the tool's input/output schema."""
        return {
            "name": self.name,
            "description": self.description,
        }


class ParseTaskTool(WritingTool):
    """Parses natural language task description into structured TaskSpec."""

    name = "parse_task"
    description = "Parse a natural language writing task into structured specification"

    def execute(self, input_data: ParseTaskInput) -> ParseTaskOutput:
        system_prompt = """You are a writing task parser. Extract structured information from natural language writing requests.

Output a JSON object with these fields:
- genre: the story genre (e.g., "psychological thriller", "romance", "sci-fi")
- premise: the core story premise or seed idea
- target_words: target word count (default 1000 if not specified)
- pov: narrative point of view ("first-person", "third-person-limited", "third-person-omniscient")
- style_directives: list of style requirements
- structural_constraints: list of structural requirements (e.g., "must have a twist")

Output ONLY valid JSON, no other text."""

        prompt = f"Parse this writing task:\n\n{input_data.prompt}"

        try:
            response = call_llm(prompt, system_prompt, temperature=0.3)
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"^```(?:json)?\n?", "", response)
                response = re.sub(r"\n?```$", "", response)

            data = json.loads(response)
            return ParseTaskOutput(
                success=True,
                genre=data.get("genre", "general fiction"),
                premise=data.get("premise", input_data.prompt),
                target_words=data.get("target_words", 1000),
                pov=data.get("pov", "third-person-limited"),
                style_directives=data.get("style_directives", []),
                structural_constraints=data.get("structural_constraints", []),
            )
        except Exception as e:
            return ParseTaskOutput(
                success=False,
                error=str(e),
                premise=input_data.prompt,
            )


class PlanPlotTool(WritingTool):
    """Plans plot structure with beats and scenes."""

    name = "plan_plot"
    description = "Generate plot beats and scene breakdown from premise"

    def execute(self, input_data: PlanPlotInput) -> PlanPlotOutput:
        num_scenes = max(3, input_data.target_words // 400)

        system_prompt = f"""You are a story planner specializing in {input_data.genre}.

Create a plot structure with:
1. Story beats (key plot points)
2. Scene breakdown ({num_scenes} scenes for ~{input_data.target_words} words)
3. Character arcs

Structural requirements to incorporate:
{json.dumps(input_data.structural_constraints, ensure_ascii=False)}

Output a JSON object with:
- beats: list of story beat strings
- scenes: list of objects with "id" (int) and "summary" (str describing the scene)
- character_arcs: object mapping character names to list of arc points

Output ONLY valid JSON."""

        prompt = f"""Genre: {input_data.genre}
Premise: {input_data.premise}
Target word count: {input_data.target_words}

Create a compelling plot structure."""

        try:
            response = call_llm(prompt, system_prompt, temperature=0.7)
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"^```(?:json)?\n?", "", response)
                response = re.sub(r"\n?```$", "", response)

            data = json.loads(response)
            scenes = data.get("scenes", [])
            for i, scene in enumerate(scenes):
                if "id" not in scene:
                    scene["id"] = i

            return PlanPlotOutput(
                success=True,
                beats=data.get("beats", []),
                scenes=scenes,
                character_arcs=data.get("character_arcs", {}),
            )
        except Exception as e:
            default_scenes = [
                {"id": 0, "summary": "Opening - establish setting and character"},
                {"id": 1, "summary": "Rising action - introduce conflict"},
                {"id": 2, "summary": "Climax and resolution"},
            ]
            return PlanPlotOutput(
                success=False,
                error=str(e),
                beats=["Setup", "Confrontation", "Resolution"],
                scenes=default_scenes,
            )


class DraftSceneTool(WritingTool):
    """Drafts a single scene with context injection."""

    name = "draft_scene"
    description = "Generate content for a single scene"

    def execute(self, input_data: DraftSceneInput) -> DraftSceneOutput:
        system_prompt = """You are a creative fiction writer. Write the scene content directly.

CRITICAL RULES:
1. Follow the style anchor EXACTLY - match POV, tense, tone
2. Maintain consistency with established entities and their attributes
3. Build on prior content naturally
4. Hit approximately the target word count
5. Write ONLY the scene prose, no meta-commentary or scene headers

Output the scene content directly, nothing else."""

        prompt = f"""{input_data.context_injection}

## Task
Write Scene {input_data.scene_id}: {input_data.scene_summary}
Target: approximately {input_data.target_words} words

Write the scene now:"""

        try:
            response = call_llm(prompt, system_prompt, temperature=0.8)
            content = response.strip()

            word_count = len(content.split())

            return DraftSceneOutput(
                success=True,
                content=content,
                word_count=word_count,
            )
        except Exception as e:
            return DraftSceneOutput(success=False, error=str(e))


class CheckConsistencyTool(WritingTool):
    """Checks scene for consistency issues."""

    name = "check_consistency"
    description = "Check scene content for consistency with prior content and entity registry"

    def execute(self, input_data: CheckConsistencyInput) -> CheckConsistencyOutput:
        system_prompt = """You are a continuity editor. Check for:

1. ENTITY DRIFT: Character attributes changing (eye color, name spelling, etc.)
2. TIMELINE ISSUES: Temporal inconsistencies
3. STYLE DRIFT: Deviation from established voice/POV/tense
4. REFERENCE DRIFT: Contradictions with prior content

Output JSON with:
- is_consistent: boolean
- issues: list of specific issue strings
- entity_updates: list of {entity, attribute, value} for new entities/attributes found
- severity: "none", "minor", "major"

Be thorough but don't flag stylistic choices as errors.
Output ONLY valid JSON."""

        context = f"""## Established Entities
{json.dumps(input_data.entity_registry, ensure_ascii=False, indent=2)}

## Style Anchor
{json.dumps(input_data.style_anchor, ensure_ascii=False, indent=2)}

## Prior Content (for reference)
{input_data.prior_content[-3000:] if input_data.prior_content else "(This is the first scene)"}

## Scene to Check (Scene {input_data.scene_id})
{input_data.scene_content}"""

        try:
            response = call_llm(context, system_prompt, temperature=0.3)
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"^```(?:json)?\n?", "", response)
                response = re.sub(r"\n?```$", "", response)

            data = json.loads(response)
            return CheckConsistencyOutput(
                success=True,
                is_consistent=data.get("is_consistent", True),
                issues=data.get("issues", []),
                entity_updates=data.get("entity_updates", []),
                severity=data.get("severity", "none"),
            )
        except Exception as e:
            return CheckConsistencyOutput(
                success=False,
                error=str(e),
                is_consistent=True,
            )


class ReviseSceneTool(WritingTool):
    """Revises a scene to fix issues or adjust style/length."""

    name = "revise_scene"
    description = "Revise scene content to fix issues or adjust parameters"

    def execute(self, input_data: ReviseSceneInput) -> ReviseSceneOutput:
        revision_instructions = {
            "fix_issues": "Fix the specific consistency issues listed below while preserving the scene's strengths.",
            "expand": "Expand the scene with more detail, sensory information, and character interiority.",
            "compress": "Tighten the prose, remove redundancy, make every word count.",
            "style_adjust": "Adjust the style to better match the style anchor while keeping content.",
            "pacing": "Adjust pacing - vary sentence length, add/remove beats as needed.",
        }

        instruction = revision_instructions.get(
            input_data.revision_type,
            "Improve the scene while maintaining consistency."
        )

        system_prompt = f"""You are a skilled fiction editor. {instruction}

RULES:
1. Follow the style anchor exactly
2. Fix all listed issues
3. Preserve what works well
4. Output ONLY the revised scene prose, no commentary"""

        issues_text = "\n".join(f"- {issue}" for issue in input_data.issues) if input_data.issues else "No specific issues"

        prompt = f"""{input_data.context_injection}

## Issues to Fix
{issues_text}

## Current Scene Content
{input_data.scene_content}

{"## Target Word Count: " + str(input_data.target_words) if input_data.target_words else ""}

Revise the scene now:"""

        try:
            response = call_llm(prompt, system_prompt, temperature=0.7)
            revised_content = response.strip()
            word_count = len(revised_content.split())

            return ReviseSceneOutput(
                success=True,
                revised_content=revised_content,
                word_count=word_count,
                changes_made=[f"Applied {input_data.revision_type} revision"],
            )
        except Exception as e:
            return ReviseSceneOutput(success=False, error=str(e))


class ExtractEntitiesBatchTool(WritingTool):
    """Extracts entities from scene content."""

    name = "extract_entities"
    description = "Extract character and entity information from scene content"

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        system_prompt = """Extract entities (characters, places, objects) with their attributes from the text.

Output JSON with:
- entities: list of {name, type, attributes: {attribute: value}}

Focus on physical descriptions, names, and distinguishing features.
Output ONLY valid JSON."""

        try:
            response = call_llm(
                f"Extract entities from:\n\n{input_data.get('content', '')}",
                system_prompt,
                temperature=0.3,
            )
            response = response.strip()
            if response.startswith("```"):
                response = re.sub(r"^```(?:json)?\n?", "", response)
                response = re.sub(r"\n?```$", "", response)

            data = json.loads(response)
            return {"success": True, "entities": data.get("entities", [])}
        except Exception as e:
            return {"success": False, "error": str(e), "entities": []}


class ToolRegistry:
    """Registry of available writing tools."""

    def __init__(self):
        self._tools: dict[str, WritingTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register all default writing tools."""
        tools = [
            ParseTaskTool(),
            PlanPlotTool(),
            DraftSceneTool(),
            CheckConsistencyTool(),
            ReviseSceneTool(),
            ExtractEntitiesBatchTool(),
        ]
        for tool in tools:
            self._tools[tool.name] = tool

    def register(self, tool: WritingTool) -> None:
        """Register a custom tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> WritingTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def execute(self, tool_name: str, input_data: ToolInput | dict) -> ToolOutput | dict:
        """Execute a tool by name."""
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")
        return tool.execute(input_data)

    def get_schemas(self) -> list[dict[str, Any]]:
        """Get schemas for all registered tools."""
        return [tool.get_schema() for tool in self._tools.values()]
