"""Scaffold-native research harness program."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result
from harness_scaffold.tools.registry import ToolRegistry


MAX_QUERIES = 6
MAX_SEARCH_RESULTS_PER_QUERY = 5
MAX_EVIDENCE_ITEMS = 12
MAX_FETCH_CHARS = 6000
MAX_CONTEXT_CHARS = 18000


class GeneratedHarnessProgram:
    name = "research_agent"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        question = (ctx.task.prompt or "").strip()
        errors: list[str] = []
        degraded = False
        if not question:
            errors.append("No research question was provided.")
            return await self._write_failure(ctx, question, errors)

        mode = _classify_mode(question)
        queries = await self._plan_queries(ctx, llm, question, mode)
        ctx.trajectory.log_observation(
            f"planned {len(queries)} search queries for {mode['answer_type']} answer",
            source=self.name,
        )

        evidence, search_errors = await self._collect_evidence(ctx, tools, queries)
        errors.extend(search_errors)
        evidence = _rank_and_prune_evidence(evidence)
        sources = _sources_from_evidence(evidence)

        if not evidence:
            errors.append("No retrievable evidence was found; refusing to fabricate an answer.")
            return await self._write_partial(
                ctx,
                question,
                mode,
                queries,
                evidence,
                sources,
                errors,
                "I could not produce a grounded answer because no searchable or fetchable evidence was available.",
            )

        answer, synthesis_degraded = await self._synthesize(ctx, llm, question, mode, evidence)
        degraded = degraded or synthesis_degraded
        verification = await self._verify(ctx, llm, question, answer, evidence)
        degraded = degraded or bool(verification.get("degraded"))
        if synthesis_degraded:
            errors.append("LLM synthesis failed or was unavailable; used extractive evidence fallback.")
        if verification.get("degraded"):
            errors.append(str(verification.get("note") or "LLM verification degraded."))
        if not verification.get("grounded", True):
            errors.append(str(verification.get("note") or "Self-verification found unsupported claims."))

        status = "success" if verification.get("grounded", True) and not degraded else "partial"
        answer_path, answer_json_path, evidence_path, sources_path = _write_artifacts(
            ctx,
            question,
            mode,
            answer,
            queries,
            evidence,
            sources,
            verification,
            errors,
            status,
        )
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="done", note=status)
        return make_result(
            ctx,
            status=status,  # type: ignore[arg-type]
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "status": status,
                "answer_json_path": str(answer_json_path),
                "evidence_path": str(evidence_path),
                "sources_path": str(sources_path),
                "evidence_count": len(evidence),
                "source_count": len(sources),
                "queries": queries,
                "errors": errors,
                "verification": verification,
            },
        )

    async def _write_failure(
        self,
        ctx: RuntimeContext,
        question: str,
        errors: list[str],
    ) -> HarnessResult:
        mode = _classify_mode(question)
        answer = "No answer could be produced because the input question was empty."
        answer_path, answer_json_path, evidence_path, sources_path = _write_artifacts(
            ctx,
            question,
            mode,
            answer,
            [],
            [],
            [],
            {"grounded": False, "note": "empty question"},
            errors,
            "failed",
        )
        return make_result(
            ctx,
            status="failed",
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "answer_json_path": str(answer_json_path),
                "evidence_path": str(evidence_path),
                "sources_path": str(sources_path),
                "errors": errors,
            },
        )

    async def _write_partial(
        self,
        ctx: RuntimeContext,
        question: str,
        mode: dict[str, str],
        queries: list[str],
        evidence: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        errors: list[str],
        answer: str,
    ) -> HarnessResult:
        answer_path, answer_json_path, evidence_path, sources_path = _write_artifacts(
            ctx,
            question,
            mode,
            answer,
            queries,
            evidence,
            sources,
            {"grounded": False, "note": "no evidence"},
            errors,
            "partial",
        )
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="done", note="partial")
        return make_result(
            ctx,
            status="partial",  # type: ignore[arg-type]
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "status": "partial",
                "answer_json_path": str(answer_json_path),
                "evidence_path": str(evidence_path),
                "sources_path": str(sources_path),
                "evidence_count": len(evidence),
                "source_count": len(sources),
                "queries": queries,
                "errors": errors,
                "missing_dependencies": _missing_dependency_errors(errors),
            },
        )

    async def _plan_queries(
        self,
        ctx: RuntimeContext,
        llm: Optional[object],
        question: str,
        mode: dict[str, str],
    ) -> list[str]:
        ctx.step()
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="plan", note="query planning")
        fallback = _fallback_queries(question)
        if llm is None:
            return fallback
        prompt = (
            "Generate concise web search queries for the research question. "
            "Prefer primary sources, official pages, papers, or reputable references. "
            "Return JSON only as {\"queries\":[...]} with at most 6 strings.\n\n"
            f"Question: {question}\nExpected answer type: {mode['answer_type']}"
        )
        try:
            ctx.trajectory.log_llm_call(model=getattr(llm, "model", None), num_messages=1, step=ctx.budget.steps_used)
            response = await llm.complete(
                [{"role": "user", "content": prompt}],
                timeout=min(ctx.policy.max_llm_seconds or 60.0, 60.0),
                temperature=0,
                max_tokens=500,
            )
            ctx.trajectory.log_llm_result(model=getattr(response, "model", None), usage=getattr(response, "usage", None), text_preview=response.text[:500], step=ctx.budget.steps_used)
            parsed = _extract_json(response.text)
            queries = parsed.get("queries") if isinstance(parsed, dict) else None
            if isinstance(queries, list):
                merged = _unique_strings([str(q) for q in queries] + fallback)
                return merged[:MAX_QUERIES]
        except Exception as exc:  # noqa: BLE001
            ctx.trajectory.log_error({"stage": "query_planning", "message": f"{type(exc).__name__}: {exc}"}, step=ctx.budget.steps_used)
        return fallback

    async def _collect_evidence(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        queries: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        evidence: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        if not tools.has("web_search"):
            return [], ["web_search tool is unavailable"]
        if not tools.has("web_fetch"):
            return [], ["web_fetch tool is unavailable"]

        for query in queries[:MAX_QUERIES]:
            if ctx.budget.steps_left() <= 3 or len(evidence) >= MAX_EVIDENCE_ITEMS:
                break
            ctx.step()
            ctx.trajectory.log_step(ctx.budget.steps_used, phase="search", note=query)
            search_result = await tools.get("web_search").execute(
                ctx,
                {"query": query, "max_results": MAX_SEARCH_RESULTS_PER_QUERY},
            )
            if not search_result.ok:
                errors.append(_tool_error_message("web_search", query, search_result))
                continue
            data = search_result.data if isinstance(search_result.data, dict) else {}
            for item in data.get("results") or []:
                if len(evidence) >= MAX_EVIDENCE_ITEMS or ctx.budget.steps_left() <= 1:
                    break
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls or _is_low_quality_source(url):
                    continue
                seen_urls.add(url)
                title = str(item.get("title") or _domain(url) or "Untitled source")
                snippet = str(item.get("snippet") or "").strip()
                fetched_text = ""
                if url.startswith(("http://", "https://", "file://")):
                    ctx.step()
                    ctx.trajectory.log_step(ctx.budget.steps_used, phase="read", note=url)
                    fetch_result = await tools.get("web_fetch").execute(ctx, {"url": url})
                    if fetch_result.ok and isinstance(fetch_result.data, dict):
                        fetched_text = str(
                            fetch_result.data.get("text")
                            or fetch_result.data.get("content")
                            or ""
                        )
                    elif not snippet:
                        errors.append(_tool_error_message("web_fetch", url, fetch_result))
                excerpt = _best_excerpt(fetched_text, snippet, query)
                if not excerpt:
                    continue
                evidence.append(
                    {
                        "id": f"E{len(evidence) + 1}",
                        "query": query,
                        "url": url,
                        "title": title,
                        "excerpt": excerpt,
                        "retrieval_time": datetime.now(timezone.utc).isoformat(),
                        "why_relevant": _why_relevant(query, title, excerpt),
                        "supports": "potentially relevant evidence for answering the research question",
                        "contradicts": "",
                        "source_domain": _domain(url),
                        "source_type": _source_type(url, title),
                    }
                )
        return evidence, errors

    async def _synthesize(
        self,
        ctx: RuntimeContext,
        llm: Optional[object],
        question: str,
        mode: dict[str, str],
        evidence: list[dict[str, Any]],
    ) -> tuple[str, bool]:
        ctx.step()
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="synthesize", note=mode["mode"])
        packed = _pack_evidence(evidence)
        if llm is None:
            return _extractive_answer(question, mode, evidence), False
        instruction = (
            "Answer the research question using only the evidence below. "
            "Cite factual claims with evidence IDs like [E1]. "
            "For closed factual questions, give a short direct answer first, then one brief evidence sentence. "
            "If evidence is insufficient or conflicting, say so explicitly. Do not cite sources not provided.\n\n"
            f"Question: {question}\n"
            f"Answer mode: {mode['mode']}\n"
            f"Expected answer type: {mode['answer_type']}\n\n"
            f"Evidence:\n{packed}"
        )
        try:
            ctx.trajectory.log_llm_call(model=getattr(llm, "model", None), num_messages=1, step=ctx.budget.steps_used)
            response = await llm.complete(
                [{"role": "user", "content": instruction}],
                timeout=min(ctx.policy.max_llm_seconds or 90.0, 90.0),
                temperature=0,
                max_tokens=1200 if mode["mode"] == "direct" else 2200,
            )
            ctx.trajectory.log_llm_result(model=getattr(response, "model", None), usage=getattr(response, "usage", None), text_preview=response.text[:500], step=ctx.budget.steps_used)
            text = response.text.strip()
            if text:
                return text, False
        except Exception as exc:  # noqa: BLE001
            ctx.trajectory.log_error({"stage": "synthesis", "message": f"{type(exc).__name__}: {exc}"}, step=ctx.budget.steps_used)
        return _extractive_answer(question, mode, evidence), True

    async def _verify(
        self,
        ctx: RuntimeContext,
        llm: Optional[object],
        question: str,
        answer: str,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ctx.step()
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="verify", note="grounding check")
        cited_ids = set(re.findall(r"\[E(\d+)\]", answer))
        valid_ids = {str(i + 1) for i in range(len(evidence))}
        if not cited_ids:
            return {"grounded": False, "note": "answer contains no evidence citations", "cited_ids": []}
        invalid = sorted(cited_ids - valid_ids)
        if invalid:
            return {"grounded": False, "note": f"answer cites unknown evidence IDs: {invalid}", "cited_ids": sorted(cited_ids)}
        if llm is None:
            return {"grounded": True, "degraded": False, "note": "citation IDs are present; LLM verifier unavailable", "cited_ids": sorted(cited_ids)}
        prompt = (
            "Check whether the answer is supported by the evidence. Return JSON only: "
            "{\"grounded\": true/false, \"note\": \"...\", \"unsupported_claims\": []}.\n\n"
            f"Question: {question}\n\nAnswer:\n{answer}\n\nEvidence:\n{_pack_evidence(evidence)}"
        )
        try:
            ctx.trajectory.log_llm_call(model=getattr(llm, "model", None), num_messages=1, step=ctx.budget.steps_used)
            response = await llm.complete(
                [{"role": "user", "content": prompt}],
                timeout=min(ctx.policy.max_llm_seconds or 60.0, 60.0),
                temperature=0,
                max_tokens=500,
            )
            ctx.trajectory.log_llm_result(model=getattr(response, "model", None), usage=getattr(response, "usage", None), text_preview=response.text[:500], step=ctx.budget.steps_used)
            parsed = _extract_json(response.text)
            if isinstance(parsed, dict) and isinstance(parsed.get("grounded"), bool):
                parsed["cited_ids"] = sorted(cited_ids)
                return parsed
        except Exception as exc:  # noqa: BLE001
            ctx.trajectory.log_error({"stage": "verification", "message": f"{type(exc).__name__}: {exc}"}, step=ctx.budget.steps_used)
        return {"grounded": True, "degraded": True, "note": "citation check passed; LLM verifier failed or was unavailable", "cited_ids": sorted(cited_ids)}


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM


def _classify_mode(question: str) -> dict[str, str]:
    q = question.strip().lower()
    direct_patterns = [
        r"^(who|what|when|where|which|how many|how much|name)\b",
        r"\b(multiple[- ]choice|choose|answer with|short answer|exact)\b",
    ]
    answer_type = "report"
    mode = "report"
    if any(re.search(p, q) for p in direct_patterns) and len(question) < 280:
        answer_type = "closed factual"
        mode = "direct"
    if any(word in q for word in ("compare", "analyze", "summarize", "explain", "evaluate")):
        answer_type = "structured report"
        mode = "structured"
    if "date" in q or "year" in q:
        answer_type = "date"
    elif "number" in q or "how many" in q or "how much" in q:
        answer_type = "number"
    elif q.startswith("who"):
        answer_type = "person or organization"
    return {"mode": mode, "answer_type": answer_type}


def _fallback_queries(question: str) -> list[str]:
    base = re.sub(r"\s+", " ", question).strip(" ?\n\t")
    variants = [
        base,
        f"{base} official source",
        f"{base} primary source",
        f"{base} reference",
    ]
    quoted_entities = re.findall(r"[A-Z][A-Za-z0-9&.'-]+(?:\s+[A-Z][A-Za-z0-9&.'-]+){1,5}", question)
    variants.extend(f"{entity} {base}" for entity in quoted_entities[:2])
    return _unique_strings(variants)[:MAX_QUERIES]


def _unique_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            out.append(normalized)
    return out


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except Exception:  # noqa: BLE001
        pass
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None


def _tool_error_message(tool_name: str, target: str, result: Any) -> str:
    raw = getattr(result, "error", None) or getattr(result, "data", None) or getattr(result, "metadata", None)
    if isinstance(raw, dict):
        message = raw.get("message") or raw.get("error") or json.dumps(raw, ensure_ascii=False)[:400]
    else:
        message = str(raw or "unknown error")[:400]
    return f"{tool_name} failed for {target}: {message}"


def _best_excerpt(text: str, snippet: str, query: str) -> str:
    text = _clean_text(text)[:MAX_FETCH_CHARS]
    snippet = _clean_text(snippet)
    if not text:
        return snippet[:1200]
    query_terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]{4,}", query)[:10]]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        clean = sentence.strip()
        if len(clean) < 40:
            continue
        low = clean.lower()
        score = sum(1 for term in query_terms if term in low)
        scored.append((score, clean))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    chosen = [s for score, s in scored[:4] if score > 0] or [s for _, s in scored[:3]]
    excerpt = " ".join(chosen).strip() or text[:1200]
    if snippet and snippet not in excerpt:
        excerpt = f"{snippet} {excerpt}"
    return excerpt[:1600]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _why_relevant(query: str, title: str, excerpt: str) -> str:
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9]{4,}", query)]
    haystack = f"{title} {excerpt}".lower()
    matches = [term for term in terms if term in haystack][:6]
    if matches:
        return "Matches query terms: " + ", ".join(matches)
    return "Search result returned for the query and contains a usable excerpt."


def _is_low_quality_source(url: str) -> bool:
    domain = _domain(url)
    low_quality_domains = (
        "youtube.com",
        "youtu.be",
        "instagram.com",
        "facebook.com",
        "tiktok.com",
        "pinterest.com",
        "x.com",
        "twitter.com",
    )
    return any(domain == d or domain.endswith(f".{d}") for d in low_quality_domains)


def _source_type(url: str, title: str) -> str:
    domain = _domain(url)
    lowered = f"{domain} {title}".lower()
    if domain.endswith(".gov") or domain.endswith(".mil"):
        return "government/official"
    if "~" in url:
        return "web"
    if domain.endswith(".edu") or "journal" in lowered or "doi" in lowered or "arxiv" in lowered:
        return "academic"
    if any(token in lowered for token in ("official", "documentation", "docs")):
        return "official"
    if any(token in lowered for token in ("wikipedia", "britannica", "encyclopedia")):
        return "reference"
    return "web"


def _domain(url: str) -> str:
    try:
        return (urlsplit(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _rank_and_prune_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(item: dict[str, Any]) -> tuple[int, int]:
        source_type = item.get("source_type")
        priority = {"government/official": 5, "official": 4, "academic": 4, "reference": 2, "web": 1}.get(str(source_type), 1)
        return priority, len(str(item.get("excerpt") or ""))

    ranked = sorted(evidence, key=score, reverse=True)[:MAX_EVIDENCE_ITEMS]
    for i, item in enumerate(ranked, 1):
        item["id"] = f"E{i}"
    return ranked


def _sources_from_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "query": item.get("query", ""),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "excerpt": item.get("excerpt", ""),
            "retrieval_time": item.get("retrieval_time", ""),
            "relevance_notes": item.get("why_relevant", ""),
            "source_type": item.get("source_type", ""),
        }
        for item in evidence
    ]


def _pack_evidence(evidence: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    used = 0
    for item in evidence:
        chunk = (
            f"[{item['id']}] {item.get('title', '')}\n"
            f"URL: {item.get('url', '')}\n"
            f"Type: {item.get('source_type', '')}\n"
            f"Excerpt: {item.get('excerpt', '')}\n"
        )
        if used + len(chunk) > MAX_CONTEXT_CHARS:
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n".join(chunks)


def _short_direct_answer(question: str, evidence_item: dict[str, Any]) -> str:
    q = question.lower()
    excerpt = str(evidence_item.get("excerpt") or "")
    title = str(evidence_item.get("title") or "")
    text = f"{title}. {excerpt}"
    if q.startswith("what is the capital") or " capital of " in q:
        match = re.search(r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ' -]{1,60})\s+is\s+the\s+capital\b", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"capital of [A-Z][A-Za-zÀ-ÖØ-öø-ÿ' -]+\s+is\s+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ' -]{1,60})", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"capital of [A-Z][A-Za-zÀ-ÖØ-öø-ÿ' -]+,\s+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ' -]{1,60})\s+is\b", text)
        if match:
            return match.group(1).strip()
    if q.startswith("when"):
        match = re.search(r"\b(?:\d{1,2}\s+[A-Z][a-z]+\s+)?\d{4}\b", text)
        if match:
            return match.group(0)
    if q.startswith("how many") or q.startswith("how much"):
        match = re.search(r"\b\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|trillion|percent|%))?\b", text, re.I)
        if match:
            return match.group(0)
    return ""


def _extractive_answer(question: str, mode: dict[str, str], evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "Insufficient retrieved evidence to answer the question."
    first = evidence[0]
    if mode["mode"] == "direct":
        short = _short_direct_answer(question, first)
        excerpt = str(first.get("excerpt") or "").strip()
        sentence = re.split(r"(?<=[.!?])\s+", excerpt)[0][:500]
        if short:
            return f"{short}. Evidence: {sentence} [{first['id']}]"
        return f"Based on the retrieved evidence, the best-supported answer is: {sentence} [{first['id']}]"
    lines = [f"## Answer\n\nThe retrieved evidence supports the following grounded summary for: {question}\n"]
    for item in evidence[:6]:
        excerpt = str(item.get("excerpt") or "")[:500]
        lines.append(f"- {excerpt} [{item['id']}]")
    return "\n".join(lines)


def _write_artifacts(
    ctx: RuntimeContext,
    question: str,
    mode: dict[str, str],
    answer: str,
    queries: list[str],
    evidence: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    verification: dict[str, Any],
    errors: list[str],
    status: str,
) -> tuple[Any, Any, Any, Any]:
    answer_md = _format_answer_md(question, answer, evidence, verification, errors, status)
    answer_path = ctx.new_artifact_text("answer.md", answer_md, kind="answer")
    answer_json_path = ctx.new_artifact_json(
        "answer.json",
        {
            "status": status,
            "question": question,
            "mode": mode,
            "answer": answer,
            "citations": sorted(set(re.findall(r"\[E\d+\]", answer))),
            "verification": verification,
            "errors": errors,
        },
        kind="answer_json",
    )
    evidence_path = ctx.new_artifact_json(
        "evidence.json",
        {
            "question": question,
            "queries": queries,
            "evidence": evidence,
            "errors": errors,
        },
        kind="evidence",
    )
    sources_path = ctx.new_artifact_json(
        "sources.json",
        {"sources": sources, "source_count": len(sources)},
        kind="sources",
    )
    return answer_path, answer_json_path, evidence_path, sources_path


def _format_answer_md(
    question: str,
    answer: str,
    evidence: list[dict[str, Any]],
    verification: dict[str, Any],
    errors: list[str],
    status: str,
) -> str:
    lines = [f"# Answer", "", f"**Question:** {question}", "", answer.strip(), ""]
    if evidence:
        lines.extend(["## Evidence", ""])
        for item in evidence:
            lines.append(f"- [{item['id']}] {item.get('title', '')} — {item.get('url', '')}")
            lines.append(f"  - {item.get('why_relevant', '')}")
    lines.extend(["", "## Verification", "", f"Status: {status}", f"Grounded: {verification.get('grounded')}"])
    if verification.get("note"):
        lines.append(f"Note: {verification.get('note')}")
    if errors:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines).strip() + "\n"


def _missing_dependency_errors(errors: list[str]) -> list[str]:
    return [error for error in errors if "unavailable" in error.lower() or "dependency" in error.lower() or "backend" in error.lower()]
