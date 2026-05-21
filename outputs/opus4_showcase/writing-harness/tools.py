"""Tool Registry — tool registration and dispatch with input/output schemas.

Provides tools for the creative writing agent: planning, drafting,
critique, revision, memory management, style control, and consistency checking.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from openai import OpenAI


@dataclass
class ToolSchema:
    """Schema for a tool's input and output."""
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool invocation."""
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    token_usage: int = 0


# Type alias for tool functions
ToolFunction = Callable[..., ToolResult]


class ToolRegistry:
    """Registry for all writing tools with dispatch capability."""

    def __init__(self):
        self._tools: dict[str, ToolFunction] = {}
        self._schemas: dict[str, ToolSchema] = {}
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.environ.get("OPENAI_API_KEY", ""),
            )
        return self._client

    def _get_model(self) -> str:
        return os.environ.get("MODEL_NAME", "gpt-4o")

    def register(self, name: str, func: ToolFunction, schema: ToolSchema) -> None:
        """Register a tool with its schema."""
        self._tools[name] = func
        self._schemas[name] = schema

    def dispatch(self, name: str, **kwargs: Any) -> ToolResult:
        """Dispatch a tool call by name."""
        if name not in self._tools:
            return ToolResult(
                tool_name=name, success=False, output=None,
                error=f"Unknown tool: {name}",
            )
        try:
            return self._tools[name](**kwargs)
        except Exception as e:
            return ToolResult(
                tool_name=name, success=False, output=None,
                error=f"Tool execution error: {str(e)}",
            )

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_schema(self, name: str) -> Optional[ToolSchema]:
        return self._schemas.get(name)

    def _llm_call(self, messages: list[dict[str, str]],
                  max_tokens: int = 4000, temperature: float = 0.7) -> tuple[str, int]:
        """Make an LLM call and return (response_text, token_usage)."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._get_model(),
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        usage = response.usage.total_tokens if response.usage else 0
        return text, usage

    # ===== Planning Tools =====

    def tool_analyze_task(self, prompt: str) -> ToolResult:
        """Analyze the writing task and determine mode, genre, style."""
        messages = [
            {"role": "system", "content": (
                "You are a writing task analyzer. Given a writing prompt, determine:\n"
                "1. mode: 'longform' (novel/novella/multi-chapter) or 'shortform' (scene/roleplay/flash fiction)\n"
                "2. genre: the primary genre\n"
                "3. style_notes: key style requirements\n"
                "4. voice_hints: tone, register, narrative perspective\n"
                "5. estimated_length: word count estimate\n\n"
                "Respond in JSON format with these exact keys."
            )},
            {"role": "user", "content": prompt},
        ]
        text, usage = self._llm_call(messages, max_tokens=1000, temperature=0.3)
        try:
            # Extract JSON from response
            result = self._extract_json(text)
        except (json.JSONDecodeError, ValueError):
            result = {"mode": "shortform", "genre": "general", "style_notes": "",
                      "voice_hints": "", "estimated_length": 2000, "raw": text}
        return ToolResult(tool_name="analyze_task", success=True, output=result, token_usage=usage)

    def tool_create_master_outline(self, prompt: str, genre: str,
                                   style_notes: str) -> ToolResult:
        """Create master outline for long-form: world, plot spine, character arcs."""
        messages = [
            {"role": "system", "content": (
                "You are a master story architect. Create a comprehensive master outline with:\n"
                "1. WORLD: Setting, rules, atmosphere, time period\n"
                "2. PLOT SPINE: 3-act structure with key turning points\n"
                "3. CHARACTER ARCS: For each major character — want, need, flaw, arc trajectory\n"
                "4. THEMES: Central themes and how they manifest\n"
                "5. STRUCTURE: Number of chapters/volumes, estimated pacing\n\n"
                "Be specific and concrete. This outline drives everything else."
            )},
            {"role": "user", "content": (
                f"Genre: {genre}\nStyle: {style_notes}\n\nPrompt: {prompt}"
            )},
        ]
        text, usage = self._llm_call(messages, max_tokens=3000, temperature=0.7)
        return ToolResult(tool_name="create_master_outline", success=True, output=text, token_usage=usage)

    def tool_create_chapter_outline(self, master_outline: str, chapter_num: int,
                                    prior_summary: str, voice_fingerprint: str) -> ToolResult:
        """Create detailed chapter outline with structured scene nodes."""
        messages = [
            {"role": "system", "content": (
                "You are a scene architect. Create a detailed chapter outline with:\n"
                "For each scene:\n"
                "- SCENE_ID: numbering\n"
                "- POV: whose perspective\n"
                "- LOCATION: where\n"
                "- CHARACTERS: who is present\n"
                "- GOAL: what must this scene accomplish\n"
                "- CONFLICT: what tension drives the scene\n"
                "- OUTCOME: how it ends (try/fail, yes-but, no-and)\n"
                "- HOOKS: what questions does it raise\n"
                "- TONE: emotional register\n"
                "- ESTIMATED_WORDS: target length\n\n"
                "Ensure each scene advances the story and connects to the next."
            )},
            {"role": "user", "content": (
                f"Master Outline:\n{master_outline}\n\n"
                f"Chapter {chapter_num}\n"
                f"Prior events summary: {prior_summary}\n"
                f"Voice: {voice_fingerprint}"
            )},
        ]
        text, usage = self._llm_call(messages, max_tokens=2500, temperature=0.6)
        return ToolResult(tool_name="create_chapter_outline", success=True, output=text, token_usage=usage)

    def tool_analyze_scenario(self, prompt: str) -> ToolResult:
        """For shortform: analyze scenario and create emotional map."""
        messages = [
            {"role": "system", "content": (
                "Analyze this roleplay/short-form scenario. Provide:\n"
                "1. SCENARIO_ANALYSIS: What is happening, who is involved, what's at stake\n"
                "2. EMOTIONAL_MAP: The emotional landscape — what each participant feels, "
                "wants, fears. Map the tension dynamics.\n"
                "3. MENTAL_MODELS: Theory of mind for each participant — what do they "
                "know/not know, what are they assuming, what are their blind spots\n"
                "4. RESPONSE_STRATEGY: How to craft a response that is psychologically "
                "grounded, specific (not generic), and emotionally authentic\n\n"
                "Be concrete and specific. Avoid abstractions."
            )},
            {"role": "user", "content": prompt},
        ]
        text, usage = self._llm_call(messages, max_tokens=2000, temperature=0.5)
        return ToolResult(tool_name="analyze_scenario", success=True, output=text, token_usage=usage)

    # ===== Style Tools =====

    def tool_create_voice_fingerprint(self, genre: str, style_notes: str,
                                      sample_text: str = "") -> ToolResult:
        """Create a voice fingerprint document for style control."""
        messages = [
            {"role": "system", "content": (
                "Create a detailed VOICE FINGERPRINT document that defines the writing style. Include:\n"
                "1. SYNTAX PATTERNS: Sentence length distribution, clause structure, "
                "paragraph rhythm\n"
                "2. VOCABULARY: Register level, domain-specific terms, preferred word classes\n"
                "3. RHYTHM: Pacing patterns, use of fragments vs. complex sentences, "
                "paragraph transitions\n"
                "4. NARRATIVE DISTANCE: Close/distant, interiority level, "
                "showing-vs-telling ratio\n"
                "5. SENSORY EMPHASIS: Which senses dominate, how sensory detail is deployed\n"
                "6. DIALOGUE STYLE: Tag usage, dialect markers, subtext approach\n"
                "7. FIGURATIVE LANGUAGE: Metaphor density, simile style, preferred domains\n\n"
                "Make it actionable — a writer should be able to imitate this voice from "
                "the fingerprint alone."
            )},
            {"role": "user", "content": (
                f"Genre: {genre}\nStyle notes: {style_notes}\n"
                f"Sample (if any): {sample_text[:2000] if sample_text else 'None provided'}"
            )},
        ]
        text, usage = self._llm_call(messages, max_tokens=2000, temperature=0.6)
        return ToolResult(tool_name="create_voice_fingerprint", success=True, output=text, token_usage=usage)

    def tool_detect_ai_patterns(self, text: str) -> ToolResult:
        """Detect common AI/LLM writing patterns in text."""
        # Rule-based detection first
        ai_patterns = {
            "generic_adverbs": r"\b(suddenly|very|really|extremely|absolutely|literally|actually)\b",
            "formulaic_openings": r"^(As |In the |The [a-z]+ was |It was a )",
            "telling_not_showing": r"\b(felt|realized|understood|knew that|was aware)\b",
            "empty_intensifiers": r"\b(quite|rather|somewhat|fairly|pretty much)\b",
            "ai_filler": r"\b(delve|tapestry|testament|landscape|multifaceted|comprehensive)\b",
            "said_bookisms": r"\b(exclaimed|proclaimed|declared|uttered|vocalized)\b",
            "purple_prose": r"\b(ethereal|luminescent|resplendent|effervescent|gossamer)\b",
        }

        findings: dict[str, list[str]] = {}
        for pattern_name, regex in ai_patterns.items():
            matches = re.findall(regex, text, re.MULTILINE | re.IGNORECASE)
            if matches:
                findings[pattern_name] = matches[:5]  # Cap at 5 examples

        # LLM-based detection for subtler patterns
        if len(text) > 200:
            messages = [
                {"role": "system", "content": (
                    "You are an AI-text detector focused on creative writing. "
                    "Identify subtle LLM writing habits:\n"
                    "- Paragraph structures that always follow the same template\n"
                    "- Lack of genuine surprise or subverted expectations\n"
                    "- Over-explanation (not trusting the reader)\n"
                    "- Emotional tells without physical grounding\n"
                    "- Symmetrical sentence structures\n"
                    "- Generic rather than specific details\n\n"
                    "List each issue found with a brief example from the text. "
                    "If the writing is good, say so."
                )},
                {"role": "user", "content": text[:3000]},
            ]
            analysis, usage = self._llm_call(messages, max_tokens=1000, temperature=0.3)
            findings["llm_analysis"] = [analysis]
        else:
            usage = 0

        score = max(0.0, 1.0 - (len(findings) * 0.15))
        return ToolResult(
            tool_name="detect_ai_patterns", success=True,
            output={"findings": findings, "originality_score": score},
            token_usage=usage,
        )

    def tool_generate_forbidden_patterns(self, genre: str, voice_fingerprint: str) -> ToolResult:
        """Generate a forbidden patterns list with alternatives."""
        messages = [
            {"role": "system", "content": (
                "Generate a FORBIDDEN PATTERNS list for this writing project. "
                "For each forbidden pattern, provide a better alternative approach.\n\n"
                "Format as JSON array of objects with keys: 'pattern', 'reason', 'alternative'\n"
                "Include at least 15 patterns covering:\n"
                "- Generic adverbs and intensifiers\n"
                "- AI-typical phrases and sentence structures\n"
                "- Telling-not-showing constructions\n"
                "- Cliche openings and transitions\n"
                "- Genre-specific cliches\n"
                "- Overused figurative language"
            )},
            {"role": "user", "content": f"Genre: {genre}\nVoice: {voice_fingerprint[:1000]}"},
        ]
        text, usage = self._llm_call(messages, max_tokens=2000, temperature=0.5)
        try:
            patterns = self._extract_json(text)
            if isinstance(patterns, list):
                forbidden = [p.get("pattern", "") for p in patterns if p.get("pattern")]
                alternatives = {p["pattern"]: p.get("alternative", "") for p in patterns if p.get("pattern")}
            else:
                forbidden = []
                alternatives = {}
        except (json.JSONDecodeError, ValueError):
            forbidden = [
                "suddenly", "very", "really", "felt a wave of",
                "couldn't help but", "a sense of", "in that moment",
                "little did they know", "it was as if",
            ]
            alternatives = {p: "use specific action/detail instead" for p in forbidden}

        return ToolResult(
            tool_name="generate_forbidden_patterns", success=True,
            output={"forbidden": forbidden, "alternatives": alternatives},
            token_usage=usage,
        )

    # ===== Drafting Tools =====

    def tool_write_scene(self, scene_outline: str, voice_fingerprint: str,
                         context: str, forbidden_patterns: list[str],
                         target_words: int = 1500) -> ToolResult:
        """Write a single scene based on outline and style constraints."""
        forbidden_text = "\n".join(f"- NEVER use: '{p}'" for p in forbidden_patterns[:20])
        messages = [
            {"role": "system", "content": (
                "You are a master fiction writer. Write the scene described below.\n\n"
                "RULES:\n"
                "- Show, don't tell. Use concrete sensory details.\n"
                "- Vary sentence length. Mix short punches with longer flowing sentences.\n"
                "- Ground emotions in physical sensation and action.\n"
                "- Dialogue should have subtext — characters rarely say exactly what they mean.\n"
                "- Every paragraph must earn its place.\n"
                "- Trust the reader. Don't over-explain.\n\n"
                f"VOICE:\n{voice_fingerprint[:1500]}\n\n"
                f"FORBIDDEN PATTERNS:\n{forbidden_text}\n\n"
                f"TARGET LENGTH: ~{target_words} words"
            )},
            {"role": "user", "content": (
                f"SCENE OUTLINE:\n{scene_outline}\n\n"
                f"CONTEXT (what came before):\n{context[:2000]}"
            )},
        ]
        text, usage = self._llm_call(messages, max_tokens=max(2000, target_words * 2), temperature=0.8)
        return ToolResult(tool_name="write_scene", success=True, output=text, token_usage=usage)

    def tool_write_shortform(self, scenario_analysis: str, emotional_map: str,
                             mental_models: str, voice_fingerprint: str,
                             forbidden_patterns: list[str]) -> ToolResult:
        """Write short-form / roleplay response with emotional intelligence."""
        forbidden_text = "\n".join(f"- NEVER: '{p}'" for p in forbidden_patterns[:15])
        messages = [
            {"role": "system", "content": (
                "Write a psychologically grounded creative response. Structure:\n"
                "1. INTERNAL: What the character thinks/feels (specific, embodied)\n"
                "2. UNDERSTANDING: How they read the other participants\n"
                "3. RESPONSE: The in-character action/dialogue\n\n"
                "RULES:\n"
                "- No platitudes or generic empathy\n"
                "- Emotions are physical — ground them in the body\n"
                "- Subtext over text — what's unsaid matters\n"
                "- Specific details over vague impressions\n"
                "- Each character has a distinct psychology\n\n"
                f"VOICE:\n{voice_fingerprint[:1000]}\n\n"
                f"FORBIDDEN:\n{forbidden_text}"
            )},
            {"role": "user", "content": (
                f"SCENARIO:\n{scenario_analysis}\n\n"
                f"EMOTIONAL MAP:\n{emotional_map}\n\n"
                f"MENTAL MODELS:\n{mental_models}"
            )},
        ]
        text, usage = self._llm_call(messages, max_tokens=3000, temperature=0.8)
        return ToolResult(tool_name="write_shortform", success=True, output=text, token_usage=usage)

    # ===== Critique and Revision Tools =====

    def tool_critique(self, text: str, voice_fingerprint: str, genre: str) -> ToolResult:
        """Run adversarial critique panel on text."""
        messages = [
            {"role": "system", "content": (
                "You are a panel of adversarial critics reviewing creative writing. "
                "Score the text on these dimensions (0.0-1.0) and provide specific feedback:\n\n"
                "1. VOCABULARY (0-1): Precision, variety, appropriateness to register\n"
                "2. SENTENCE_STRUCTURE (0-1): Variety, rhythm, flow\n"
                "3. NARRATIVE (0-1): Plot advancement, pacing, tension\n"
                "4. EMOTION (0-1): Authenticity, specificity, resonance\n"
                "5. DIALOGUE (0-1): Naturalness, subtext, character distinction\n"
                "6. AI_FLAVOR (0-1): 1.0 = completely human-sounding, 0.0 = obviously AI\n"
                "7. CONSISTENCY (0-1): Internal logic, character consistency, world rules\n\n"
                "Respond in JSON with keys: scores (dict of dimension:float), "
                "strengths (list), weaknesses (list), revision_priorities (list ranked by importance)"
            )},
            {"role": "user", "content": (
                f"Genre: {genre}\nVoice target: {voice_fingerprint[:500]}\n\n"
                f"TEXT TO CRITIQUE:\n{text[:4000]}"
            )},
        ]
        text_response, usage = self._llm_call(messages, max_tokens=2000, temperature=0.4)
        try:
            result = self._extract_json(text_response)
        except (json.JSONDecodeError, ValueError):
            result = {
                "scores": {"vocabulary": 0.6, "sentence_structure": 0.6,
                           "narrative": 0.6, "emotion": 0.6, "dialogue": 0.6,
                           "ai_flavor": 0.5, "consistency": 0.7},
                "strengths": [],
                "weaknesses": ["Could not parse critique"],
                "revision_priorities": ["Retry critique"],
                "raw": text_response,
            }
        return ToolResult(tool_name="critique", success=True, output=result, token_usage=usage)

    def tool_revise(self, text: str, revision_brief: str,
                    voice_fingerprint: str, forbidden_patterns: list[str]) -> ToolResult:
        """Revise text based on critique feedback."""
        forbidden_text = "\n".join(f"- '{p}'" for p in forbidden_patterns[:15])
        messages = [
            {"role": "system", "content": (
                "You are a skilled editor revising creative writing. Apply the revision brief "
                "while maintaining the voice and improving quality.\n\n"
                "CRITICAL RULES:\n"
                "- Your revision must be AT LEAST 80% the length of the original\n"
                "- Preserve what works — only change what the brief targets\n"
                "- Maintain narrative continuity\n"
                "- Apply voice fingerprint consistently\n"
                "- Avoid all forbidden patterns\n\n"
                f"VOICE:\n{voice_fingerprint[:1000]}\n\n"
                f"FORBIDDEN PATTERNS:\n{forbidden_text}"
            )},
            {"role": "user", "content": (
                f"REVISION BRIEF:\n{revision_brief}\n\n"
                f"TEXT TO REVISE:\n{text}"
            )},
        ]
        revised, usage = self._llm_call(messages, max_tokens=max(2000, len(text) // 3), temperature=0.7)
        return ToolResult(tool_name="revise", success=True, output=revised, token_usage=usage)

    # ===== Consistency Tools =====

    def tool_check_consistency(self, text: str, world_rules: str,
                               character_knowledge: str, timeline: str) -> ToolResult:
        """Check text for consistency violations against world rules and canon."""
        messages = [
            {"role": "system", "content": (
                "You are a continuity editor. Check the text for:\n"
                "1. WORLD RULE VIOLATIONS: Does anything contradict established rules?\n"
                "2. CHARACTER KNOWLEDGE ERRORS: Does any character know something "
                "they shouldn't (or not know something they should)?\n"
                "3. TIMELINE ISSUES: Any temporal impossibilities or contradictions?\n"
                "4. INTERNAL CONTRADICTIONS: Does the text contradict itself?\n\n"
                "Respond in JSON: {violations: [{type, description, severity}], "
                "is_consistent: bool}"
            )},
            {"role": "user", "content": (
                f"WORLD RULES:\n{world_rules}\n\n"
                f"CHARACTER KNOWLEDGE:\n{character_knowledge}\n\n"
                f"TIMELINE:\n{timeline}\n\n"
                f"TEXT TO CHECK:\n{text[:3000]}"
            )},
        ]
        text_response, usage = self._llm_call(messages, max_tokens=1500, temperature=0.2)
        try:
            result = self._extract_json(text_response)
        except (json.JSONDecodeError, ValueError):
            result = {"violations": [], "is_consistent": True, "raw": text_response}
        return ToolResult(tool_name="check_consistency", success=True, output=result, token_usage=usage)

    def tool_update_memory(self, scene_text: str, chapter: int, scene: int) -> ToolResult:
        """Extract memory updates from a completed scene."""
        messages = [
            {"role": "system", "content": (
                "Extract structured information from this scene for memory storage.\n"
                "Return JSON with:\n"
                "- summary: one-sentence scene summary\n"
                "- key_events: list of important plot events\n"
                "- character_updates: [{name, emotional_state, new_knowledge, location}]\n"
                "- timeline_events: [{description, story_time}]\n"
                "- new_hooks: list of unresolved questions/tensions introduced\n"
                "- resolved_hooks: list of previously open questions answered"
            )},
            {"role": "user", "content": scene_text[:3000]},
        ]
        text_response, usage = self._llm_call(messages, max_tokens=1500, temperature=0.3)
        try:
            result = self._extract_json(text_response)
        except (json.JSONDecodeError, ValueError):
            result = {
                "summary": scene_text[:100],
                "key_events": [],
                "character_updates": [],
                "timeline_events": [],
                "new_hooks": [],
                "resolved_hooks": [],
            }
        return ToolResult(tool_name="update_memory", success=True, output=result, token_usage=usage)

    # ===== Utility =====

    def _extract_json(self, text: str) -> Any:
        """Extract JSON from LLM response text."""
        # Try direct parse first
        text = text.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Try to find JSON block in markdown code fence
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1).strip())

        # Try to find first { or [ and parse from there
        for i, ch in enumerate(text):
            if ch in "{[":
                try:
                    return json.loads(text[i:])
                except json.JSONDecodeError:
                    continue

        raise ValueError(f"No JSON found in response: {text[:200]}")


def create_default_registry() -> ToolRegistry:
    """Create and populate the default tool registry with all tools."""
    registry = ToolRegistry()

    # Register all tools with schemas
    registry.register("analyze_task", registry.tool_analyze_task, ToolSchema(
        name="analyze_task",
        description="Analyze writing task to determine mode, genre, style",
        input_schema={"prompt": "str"},
        output_schema={"mode": "str", "genre": "str", "style_notes": "str"},
    ))

    registry.register("create_master_outline", registry.tool_create_master_outline, ToolSchema(
        name="create_master_outline",
        description="Create master outline with world, plot spine, character arcs",
        input_schema={"prompt": "str", "genre": "str", "style_notes": "str"},
        output_schema={"outline": "str"},
    ))

    registry.register("create_chapter_outline", registry.tool_create_chapter_outline, ToolSchema(
        name="create_chapter_outline",
        description="Create detailed chapter outline with scene nodes",
        input_schema={"master_outline": "str", "chapter_num": "int", "prior_summary": "str", "voice_fingerprint": "str"},
        output_schema={"outline": "str"},
    ))

    registry.register("analyze_scenario", registry.tool_analyze_scenario, ToolSchema(
        name="analyze_scenario",
        description="Analyze short-form scenario for emotional mapping",
        input_schema={"prompt": "str"},
        output_schema={"analysis": "str"},
    ))

    registry.register("create_voice_fingerprint", registry.tool_create_voice_fingerprint, ToolSchema(
        name="create_voice_fingerprint",
        description="Create voice fingerprint document for style control",
        input_schema={"genre": "str", "style_notes": "str", "sample_text": "str"},
        output_schema={"fingerprint": "str"},
    ))

    registry.register("detect_ai_patterns", registry.tool_detect_ai_patterns, ToolSchema(
        name="detect_ai_patterns",
        description="Detect AI/LLM writing patterns in text",
        input_schema={"text": "str"},
        output_schema={"findings": "dict", "originality_score": "float"},
    ))

    registry.register("generate_forbidden_patterns", registry.tool_generate_forbidden_patterns, ToolSchema(
        name="generate_forbidden_patterns",
        description="Generate forbidden patterns list with alternatives",
        input_schema={"genre": "str", "voice_fingerprint": "str"},
        output_schema={"forbidden": "list", "alternatives": "dict"},
    ))

    registry.register("write_scene", registry.tool_write_scene, ToolSchema(
        name="write_scene",
        description="Write a single scene based on outline and constraints",
        input_schema={"scene_outline": "str", "voice_fingerprint": "str", "context": "str",
                      "forbidden_patterns": "list", "target_words": "int"},
        output_schema={"scene_text": "str"},
    ))

    registry.register("write_shortform", registry.tool_write_shortform, ToolSchema(
        name="write_shortform",
        description="Write short-form/roleplay response with emotional intelligence",
        input_schema={"scenario_analysis": "str", "emotional_map": "str",
                      "mental_models": "str", "voice_fingerprint": "str",
                      "forbidden_patterns": "list"},
        output_schema={"response": "str"},
    ))

    registry.register("critique", registry.tool_critique, ToolSchema(
        name="critique",
        description="Run adversarial critique panel on text",
        input_schema={"text": "str", "voice_fingerprint": "str", "genre": "str"},
        output_schema={"scores": "dict", "strengths": "list", "weaknesses": "list", "revision_priorities": "list"},
    ))

    registry.register("revise", registry.tool_revise, ToolSchema(
        name="revise",
        description="Revise text based on critique feedback",
        input_schema={"text": "str", "revision_brief": "str", "voice_fingerprint": "str", "forbidden_patterns": "list"},
        output_schema={"revised_text": "str"},
    ))

    registry.register("check_consistency", registry.tool_check_consistency, ToolSchema(
        name="check_consistency",
        description="Check text for consistency violations",
        input_schema={"text": "str", "world_rules": "str", "character_knowledge": "str", "timeline": "str"},
        output_schema={"violations": "list", "is_consistent": "bool"},
    ))

    registry.register("update_memory", registry.tool_update_memory, ToolSchema(
        name="update_memory",
        description="Extract memory updates from completed scene",
        input_schema={"scene_text": "str", "chapter": "int", "scene": "int"},
        output_schema={"summary": "str", "key_events": "list", "character_updates": "list"},
    ))

    return registry
