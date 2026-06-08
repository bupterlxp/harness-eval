"""Critic: evaluate a draft against task constraints and produce feedback.

The critic checks for constraint adherence, prose quality, structure,
emotional nuance (for EQ-bench tasks), role consistency (for roleplay),
and length appropriateness. It returns structured critique that the
revision phase can act on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CritiqueResult:
    score: float = 0.0
    issues: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    revision_focus: list[str] = field(default_factory=list)
    is_prose: bool = True
    meets_length: bool = True
    meets_structure: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "issues": list(self.issues),
            "strengths": list(self.strengths),
            "revision_focus": list(self.revision_focus),
            "is_prose": self.is_prose,
            "meets_length": self.meets_length,
            "meets_structure": self.meets_structure,
            "detail": self.detail,
        }

    @property
    def needs_revision(self) -> bool:
        return self.score < 0.7 or len(self.issues) > 0 or not self.is_prose


# Patterns that indicate non-prose content.
_NON_PROSE_PATTERNS = [
    re.compile(r'^\s*\{', re.MULTILINE),       # starts with JSON
    re.compile(r'^\s*"status"', re.MULTILINE),  # status JSON
    re.compile(r'^\s*```', re.MULTILINE),       # code block
    re.compile(r'^\s*#\s*(task completed|here is|response)', re.IGNORECASE),
    re.compile(r'task completed|see logs|see trajectory|execution summary', re.IGNORECASE),
]

_MIN_PARAGRAPHS = {
    "brief": 1,
    "short": 2,
    "medium": 3,
    "long": 5,
    "flash": 1,
    "drabble": 1,
}


def _count_paragraphs(text: str) -> int:
    return max(1, len([p for p in text.split("\n\n") if p.strip()]))


def _count_words(text: str) -> int:
    return len(text.split())


def _is_prose(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    for pat in _NON_PROSE_PATTERNS:
        if pat.search(stripped[:500]):
            return False
    # If it looks like raw JSON
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            import json
            json.loads(stripped)
            return False
        except Exception:
            pass
    return True


def _check_structure(text: str, structure: list[str]) -> bool:
    if not structure:
        return True
    lower = text.lower()
    found = sum(1 for s in structure if s.lower() in lower)
    return found >= len(structure) * 0.5


def critique_draft(
    draft: str,
    *,
    prompt: str,
    plan: Any,
) -> CritiqueResult:
    """Synchronous critique of a draft against plan constraints."""
    result = CritiqueResult()

    # Check prose quality.
    result.is_prose = _is_prose(draft)
    if not result.is_prose:
        result.issues.append("Output is not prose (appears to be JSON, logs, or metadata).")
        result.revision_focus.append("Rewrite as natural prose, not structured data.")

    # Check length.
    word_count = _count_words(draft)
    para_count = _count_paragraphs(draft)
    length_target = getattr(plan, "length_target", "medium")
    min_paras = _MIN_PARAGRAPHS.get(length_target, 3)

    if para_count < min_paras:
        result.meets_length = False
        result.issues.append(
            f"Draft has {para_count} paragraphs, needs at least {min_paras} for '{length_target}' target."
        )
        result.revision_focus.append("Expand the draft with more detail and development.")

    if word_count < 30:
        result.meets_length = False
        result.issues.append(f"Draft is very short ({word_count} words).")
        result.revision_focus.append("Substantially expand the content.")

    # Check structure if specified.
    structure = getattr(plan, "structure", [])
    if structure:
        result.meets_structure = _check_structure(draft, structure)
        if not result.meets_structure:
            result.issues.append("Draft is missing required structural elements.")
            result.revision_focus.append("Include the required structural elements.")

    # Score calculation.
    score = 0.5  # base
    if result.is_prose:
        score += 0.2
    if result.meets_length:
        score += 0.15
    if result.meets_structure:
        score += 0.1
    if word_count >= 100:
        score += 0.05
    result.score = min(1.0, score)

    return result


async def critique_with_llm(
    draft: str,
    *,
    prompt: str,
    plan: Any,
    llm: Any,
    timeout: float = 60.0,
) -> CritiqueResult:
    """Use the LLM to produce a detailed critique of the draft."""
    # Start with the synchronous checks.
    result = critique_draft(draft, prompt=prompt, plan=plan)

    # Then ask the LLM for deeper critique.
    system = (
        "You are a writing critic. Evaluate the draft against the original task. "
        "Be specific about what needs improvement. Focus on: constraint adherence, "
        "prose quality, structure, tone, and emotional depth if relevant. "
        "Output a JSON object with keys: 'score' (0-1), 'issues' (list of strings), "
        "'strengths' (list of strings), 'revision_focus' (list of specific revision directions)."
    )

    plan_context = ""
    if hasattr(plan, "to_prompt_context"):
        plan_context = plan.to_prompt_context()

    user_msg = (
        f"Original task:\n{prompt}\n\n"
        f"Plan context:\n{plan_context}\n\n"
        f"Draft:\n{draft[:3000]}\n\n"
        "Evaluate this draft and output a JSON critique."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    try:
        resp = await llm.complete(messages, timeout=timeout)
        text = resp.text.strip()
        # Try to parse JSON from the response.
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            import json
            data = json.loads(json_match.group())
            if isinstance(data.get("score"), (int, float)):
                result.score = max(result.score, float(data["score"]))
            if isinstance(data.get("issues"), list):
                result.issues.extend(str(i) for i in data["issues"] if str(i) not in result.issues)
            if isinstance(data.get("strengths"), list):
                result.strengths.extend(str(s) for s in data["strengths"])
            if isinstance(data.get("revision_focus"), list):
                result.revision_focus.extend(str(f) for f in data["revision_focus"])
            result.detail = text
    except Exception:
        # LLM critique is optional; the sync checks still apply.
        pass

    return result
