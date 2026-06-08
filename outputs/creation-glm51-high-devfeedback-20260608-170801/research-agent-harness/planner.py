"""Planner: question type detection, decomposition, and search query generation.

Called by generated_program.py to break a research question into actionable
sub-questions and web search queries. Pure logic — no I/O, no LLM calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubQuestion:
    question: str
    queries: list[str]
    priority: int = 0
    answer_type: str = "factual"


@dataclass
class ResearchPlan:
    original_question: str
    answer_type: str
    sub_questions: list[SubQuestion]
    max_search_rounds: int = 3


_SHORT_ANSWER_PATTERNS: list[tuple[str, str]] = [
    (r"\bhow many\b", "number"),
    (r"\bhow much\b", "number"),
    (r"\bwhat year\b", "date"),
    (r"\bwhat date\b", "date"),
    (r"\bwhen (did|was|were|will)\b", "date"),
    (r"\bwho (is|was|are|were|did|won|discovered|invented|created|wrote|built|founded)\b", "name"),
    (r"\bwhere (is|was|are|were|did)\b", "location"),
    (r"\bwhat is the (\w+ )?(name|title)\b", "name"),
    (r"\bwhich\b", "choice"),
    (r"\btrue or false\b", "boolean"),
    (r"\byes or no\b", "boolean"),
    (r"\bis it (true|false)\b", "boolean"),
    (r"\bis .+\b(or|and)\b.+\?", "boolean"),
    (r"\b(percentage|percent|proportion|fraction)\b", "number"),
    (r"\b(population|total|count|number of)\b", "number"),
    (r"\bwhat is \d", "number"),
    (r"\bcalculate\b", "number"),
    (r"\bhow (old|long|tall|big|far|fast|deep|high|wide|heavy)\b", "number"),
]


def detect_answer_type(question: str) -> str:
    q = question.lower().strip()
    for pattern, atype in _SHORT_ANSWER_PATTERNS:
        if re.search(pattern, q):
            return atype
    if len(q.split()) <= 6:
        return "factual"
    return "report"


def _generate_queries(question: str) -> list[str]:
    queries = [question.strip()]
    q = question.strip()
    if q.endswith("?"):
        queries.append(q[:-1].strip())
    if q.endswith("?") and len(q.split()) > 4:
        words = q[:-1].split()
        queries.append(" ".join(words[:5]))
        queries.append(" ".join(words[-5:]))
    core = re.sub(r"\b(what|who|where|when|how|which|why|is|are|was|were|did|does|do|the|a|an)\b", " ", q, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip()
    if core and core != q:
        queries.append(core)
    return queries[:4]


def _try_split_compound(question: str) -> list[str]:
    """Try to split a question that contains 'and' into parts."""
    parts = [question]
    for conn in [" and ", ", and "]:
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(p.split(conn))
        parts = new_parts
    if len(parts) <= 1:
        return []
    stripped = [p.strip().rstrip("?.!") for p in parts if p.strip()]
    if len(stripped) < 2:
        return []
    types = [detect_answer_type(p) for p in stripped]
    if len(set(types)) >= 2:
        # Fix incomplete subquestions by prepending context from the first part
        fixed: list[str] = [stripped[0]]
        first_keywords = [w for w in stripped[0].split() if len(w) > 3 and w.lower() not in {
            "what", "who", "where", "when", "how", "which", "that", "this", "with", "from"
        }]
        for part in stripped[1:]:
            if len(part.split()) < 4 and first_keywords:
                part = part + " " + " ".join(first_keywords[-3:])
            fixed.append(part)
        return fixed
    return []


def decompose(question: str, *, max_subquestions: int = 5) -> ResearchPlan:
    answer_type = detect_answer_type(question)
    compound_parts = _try_split_compound(question)

    if compound_parts and len(compound_parts) >= 2:
        sub_questions: list[SubQuestion] = []
        for i, part in enumerate(compound_parts[:max_subquestions]):
            atype = detect_answer_type(part)
            if atype == "report":
                atype = "factual"
            queries = _generate_queries(part)
            sq = SubQuestion(question=part, queries=queries, priority=i, answer_type=atype)
            sub_questions.append(sq)
        return ResearchPlan(
            original_question=question,
            answer_type="report" if len(set(detect_answer_type(p) for p in compound_parts)) >= 2 else answer_type,
            sub_questions=sub_questions,
            max_search_rounds=3,
        )

    if answer_type in ("number", "date", "name", "location", "boolean", "choice", "factual"):
        queries = _generate_queries(question)
        sq = SubQuestion(question=question, queries=queries, priority=0, answer_type=answer_type)
        return ResearchPlan(
            original_question=question,
            answer_type=answer_type,
            sub_questions=[sq],
            max_search_rounds=3,
        )

    connectors = [", and ", ", but ", "; ", ".  ", ". "]
    parts = [question]
    for conn in connectors:
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(p.split(conn))
        parts = new_parts

    if len(parts) <= 1:
        words = question.split()
        if len(words) > 12:
            mid = len(words) // 2
            parts = [" ".join(words[:mid]), " ".join(words[mid:])]

    sub_questions: list[SubQuestion] = []
    for i, part in enumerate(parts[:max_subquestions]):
        part = part.strip().rstrip("?.!")
        if not part:
            continue
        atype = detect_answer_type(part)
        if atype == "report":
            atype = "factual"
        queries = _generate_queries(part)
        sq = SubQuestion(question=part, queries=queries, priority=i, answer_type=atype)
        sub_questions.append(sq)

    if not sub_questions:
        queries = _generate_queries(question)
        sq = SubQuestion(question=question, queries=queries, priority=0, answer_type=answer_type)
        sub_questions.append(sq)

    return ResearchPlan(
        original_question=question,
        answer_type=answer_type,
        sub_questions=sub_questions,
        max_search_rounds=3,
    )


def plan_followup_queries(question: str, evidence_summaries: list[str]) -> list[str]:
    if not evidence_summaries:
        return _generate_queries(question)
    combined = " ".join(evidence_summaries[-3:])
    words = set(re.findall(r"\b[a-zA-Z]{4,}\b", combined.lower()))
    q_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", question.lower()))
    missing = q_words - words
    if missing:
        extra = question + " " + " ".join(missing)
        return [extra]
    return []
