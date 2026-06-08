"""Verifier: self-verification of answers against collected evidence.

Called by generated_program.py after synthesis. Pure logic — no I/O, no LLM.
The LLM-based verification is done via the main program loop.
"""
from __future__ import annotations

import re
from typing import Any


def check_answer_groundedness(answer: str, evidence_ids: list[str], evidence_store: Any) -> dict[str, Any]:
    cited = set(re.findall(r"\[E(\d+)\]", answer))
    available = {item.id for item in evidence_store.items}
    valid_cited = set()
    for c in cited:
        full_id = f"E{c}"
        if full_id in available:
            valid_cited.add(full_id)
    invalid_cited = {f"E{c}" for c in cited} - valid_cited
    claims = re.split(r'(?<=[.!?])\s+', answer)
    ungrounded_claims = 0
    for claim in claims:
        has_cite = bool(re.search(r"\[E\d+\]", claim))
        if has_cite:
            continue
        if len(claim.split()) > 8 and not claim.startswith("#") and not claim.startswith("-"):
            ungrounded_claims += 1
    return {
        "cited_evidence": sorted(valid_cited),
        "invalid_citations": sorted(invalid_cited),
        "total_claims": len(claims),
        "ungrounded_claims": ungrounded_claims,
        "groundedness": 1.0 - (ungrounded_claims / max(len(claims), 1)),
    }


def _strip_citations(text: str) -> str:
    return re.sub(r"\[E\d+\]", "", text)


def check_short_answer(answer: str, expected_type: str) -> dict[str, Any]:
    answer = _strip_citations(answer).strip()
    if expected_type == "number":
        nums = re.findall(r"\b[\d,]+(?:\.\d+)?\b", answer)
        nums = [n for n in nums if n.replace(",", "").replace(".", "").isdigit() and len(n.replace(",", "").replace(".", "")) > 0]
        if nums:
            best = max(nums, key=lambda n: len(n.replace(",", "").replace(".", "")))
            val = best.replace(",", "").rstrip(".")
            return {"valid": True, "extracted": val, "type": "number"}
        return {"valid": False, "reason": "no number found in answer"}
    if expected_type == "date":
        date_patterns = [
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}\b",
            r"\b\d{1,2}/\d{1,2}/\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b(?!E\d)\d{4}\b",
        ]
        for pat in date_patterns:
            m = re.search(pat, answer, re.I)
            if m:
                return {"valid": True, "extracted": m.group(), "type": "date"}
        return {"valid": False, "reason": "no date found in answer"}
    if expected_type == "boolean":
        lower = answer.lower()
        if "yes" in lower or "true" in lower:
            return {"valid": True, "extracted": "yes", "type": "boolean"}
        if "no" in lower or "false" in lower:
            return {"valid": True, "extracted": "no", "type": "boolean"}
        return {"valid": False, "reason": "no boolean found in answer"}
    if expected_type in ("name", "location"):
        lines = answer.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-") or line.startswith("["):
                continue
            if len(line) < 100:
                return {"valid": True, "extracted": line.rstrip("."), "type": expected_type}
        return {"valid": False, "reason": f"no clear {expected_type} found in answer"}
    return {"valid": True, "type": expected_type}


def extract_final_answer(answer: str, answer_type: str) -> str:
    if answer_type in ("number", "date", "name", "location", "boolean", "choice", "factual"):
        result = check_short_answer(answer, answer_type)
        if result.get("valid") and result.get("extracted"):
            return str(result["extracted"])
    lines = answer.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if answer_type in ("number", "date", "name", "location"):
            if len(line) < 150:
                return line.rstrip(".")
    return answer.strip()[:500]
