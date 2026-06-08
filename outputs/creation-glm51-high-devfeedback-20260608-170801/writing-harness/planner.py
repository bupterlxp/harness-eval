"""Planner: parse writing task prompts into structured plans.

Extracts genre, style, tone, length, structure, characters, constraints,
and audience from the raw task prompt, then produces a compact outline
the drafting phase can follow.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WritingPlan:
    genre: str = "general"
    style: str = ""
    tone: str = ""
    audience: str = ""
    length_target: str = "medium"
    structure: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    role: str = ""
    outline: str = ""
    is_eqbench: bool = False
    is_roleplay: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "style": self.style,
            "tone": self.tone,
            "audience": self.audience,
            "length_target": self.length_target,
            "structure": list(self.structure),
            "characters": list(self.characters),
            "constraints": list(self.constraints),
            "role": self.role,
            "outline": self.outline,
            "is_eqbench": self.is_eqbench,
            "is_roleplay": self.is_roleplay,
        }

    def to_prompt_context(self) -> str:
        parts: list[str] = []
        if self.genre and self.genre != "general":
            parts.append(f"Genre: {self.genre}")
        if self.style:
            parts.append(f"Style: {self.style}")
        if self.tone:
            parts.append(f"Tone: {self.tone}")
        if self.audience:
            parts.append(f"Audience: {self.audience}")
        if self.role:
            parts.append(f"Role: {self.role}")
        if self.length_target:
            parts.append(f"Length: {self.length_target}")
        if self.structure:
            parts.append(f"Structure: {' > '.join(self.structure)}")
        if self.characters:
            parts.append(f"Characters: {', '.join(self.characters)}")
        if self.constraints:
            parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in self.constraints))
        if self.outline:
            parts.append(f"Outline:\n{self.outline}")
        return "\n".join(parts)


# Keywords that signal EQ-bench / emotional intelligence tasks.
_EQ_KEYWORDS = [
    "emotional", "empathy", "eq", "emotion", "feelings", "perspective",
    "theory of mind", "inner thought", "motivation", "relationship",
    "conflict resolution", "comfort", "support", "vulnerable", "distress",
]

_ROLEPLAY_KEYWORDS = [
    "role-play", "roleplay", "pretend you are", "act as", "you are a",
    "imagine you are", "in character", "as a character", "speak as",
    "respond as", "persona",
]

_GENRE_MAP = {
    "sci-fi": "science fiction", "scifi": "science fiction",
    "fantasy": "fantasy", "horror": "horror", "mystery": "mystery",
    "romance": "romance", "thriller": "thriller", "comedy": "comedy",
    "drama": "drama", "poetry": "poetry", "essay": "essay",
    "blog": "blog post", "letter": "letter", "diary": "diary entry",
    "web novel": "web novel", "flash fiction": "flash fiction",
    "short story": "short story", "novel": "novel",
}

_LENGTH_MAP = {
    "brief": "brief (1-2 paragraphs)", "short": "short (3-5 paragraphs)",
    "medium": "medium (6-12 paragraphs)", "long": "long (13+ paragraphs)",
    "flash": "flash (under 500 words)", "drabble": "drabble (exactly 100 words)",
}


def _detect_genre(prompt: str) -> str:
    lower = prompt.lower()
    for key, genre in _GENRE_MAP.items():
        if key in lower:
            return genre
    return "general"


def _detect_length(prompt: str) -> str:
    lower = prompt.lower()
    if "flash" in lower or "micro" in lower:
        return _LENGTH_MAP.get("flash", "flash")
    if "drabble" in lower:
        return _LENGTH_MAP.get("drabble", "drabble")
    if "brief" in lower or "one paragraph" in lower or "1 paragraph" in lower:
        return _LENGTH_MAP.get("brief", "brief")
    if "short" in lower and "story" not in lower:
        return _LENGTH_MAP.get("short", "short")
    if "long" in lower or "detailed" in lower or "extended" in lower or "chapter" in lower:
        return _LENGTH_MAP.get("long", "long")
    return "medium"


def _detect_eqbench(prompt: str) -> bool:
    lower = prompt.lower()
    return any(kw in lower for kw in _EQ_KEYWORDS)


def _detect_roleplay(prompt: str) -> bool:
    lower = prompt.lower()
    return any(kw in lower for kw in _ROLEPLAY_KEYWORDS)


def _extract_constraints(prompt: str) -> list[str]:
    constraints: list[str] = []
    # Match numbered or bulleted constraint lists.
    for m in re.finditer(r"(?:^|\n)\s*(?:\d+[\.\)]|[-*])\s+(.+)", prompt):
        line = m.group(1).strip()
        if line and len(line) > 3:
            constraints.append(line)
    # Match explicit constraint phrases.
    for m in re.finditer(r"(?:must|should|need to|required|ensure|avoid|do not|don't|never|always)\s+(.+?)(?:[.;\n]|$)", prompt, re.IGNORECASE):
        line = m.group(0).strip()
        if line and len(line) > 5 and line not in constraints:
            constraints.append(line)
    return constraints[:10]


def _extract_characters(prompt: str) -> list[str]:
    chars: list[str] = []
    # Look for named characters (capitalized names preceded by character/name keywords).
    for m in re.finditer(r"(?:character|protagonist|hero|named?|called)\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", prompt):
        name = m.group(1).strip()
        if name and name not in chars:
            chars.append(name)
    return chars[:5]


def _extract_role(prompt: str) -> str:
    for pattern in [
        r"(?:pretend you are|act as|you are a|imagine you are|speak as|respond as)\s+(.+?)(?:[.;,\n]|$)",
    ]:
        m = re.search(pattern, prompt, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def plan_from_prompt(prompt: str) -> WritingPlan:
    """Build a WritingPlan from the raw task prompt."""
    plan = WritingPlan(
        genre=_detect_genre(prompt),
        length_target=_detect_length(prompt),
        is_eqbench=_detect_eqbench(prompt),
        is_roleplay=_detect_roleplay(prompt),
        constraints=_extract_constraints(prompt),
        characters=_extract_characters(prompt),
        role=_extract_role(prompt),
    )
    return plan


async def build_outline_with_llm(
    plan: WritingPlan,
    prompt: str,
    llm: Any,
    *,
    timeout: float = 60.0,
) -> WritingPlan:
    """Use the LLM to refine the plan with an outline."""
    system = (
        "You are a writing planner. Given a writing task, produce a concise "
        "outline with 3-8 bullet points. Output ONLY the outline, no preamble. "
        "Each bullet should be a single sentence describing a section or beat."
    )
    context = plan.to_prompt_context()
    user_msg = (
        f"Writing task:\n{prompt}\n\n"
        f"Detected context:\n{context}\n\n"
        "Produce a concise outline for this writing task."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    resp = await llm.complete(messages, timeout=timeout)
    plan.outline = resp.text.strip()
    return plan
