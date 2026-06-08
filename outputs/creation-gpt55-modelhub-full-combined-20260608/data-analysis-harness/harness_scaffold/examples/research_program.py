"""research_program -- web_fetch / web_search / evidence, no fabrication.

Demonstrates an evidence-grounded research loop:

1. search for the query (``web_search``),
2. fetch a bounded number of sources (``web_fetch``),
3. record each as a structured *evidence object*
   ``{source, title, snippet, used_for}``,
4. write the evidence list to an ``evidence.json`` artifact, and
5. synthesize a ``response.md`` that cites only collected evidence.

The program REFUSES TO FABRICATE: every claim in the response points at a
collected evidence id. If no evidence can be gathered (e.g. network is
disabled by policy, or the web tools are not installed), it does not invent
sources -- it returns a structured refusal with status ``success`` and an
empty evidence set, making the no-network degradation explicit.

Bounded by ``ctx.policy.max_steps`` and ``max_sources``
(``task.metadata['max_sources']``, default 3).

Run offline (network disabled -> honest refusal):
    python -m harness_scaffold.adapters.cli \
        --task-json <task.json> \
        --program harness_scaffold/examples/research_program.py \
        --out-dir /tmp/research
"""
from __future__ import annotations

from typing import Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import make_result, try_tool

DEFAULT_MAX_SOURCES = 3


def _evidence(source: str, title: str, snippet: str, used_for: str) -> dict:
    return {
        "source": source,
        "title": title,
        "snippet": (snippet or "")[:500],
        "used_for": used_for,
    }


async def _search(ctx, tools, query: str, limit: int) -> "list[dict]":
    """Return a list of {url,title,snippet} via the web_search tool, or []."""
    ok, res = await try_tool(
        ctx, tools, "web_search", {"query": query, "max_results": limit}
    )
    if not ok or res is None or not res.ok or not isinstance(res.data, dict):
        return []
    results = res.data.get("results") or []
    out = []
    for r in results[:limit]:
        if isinstance(r, dict) and r.get("url"):
            out.append(
                {
                    "url": r["url"],
                    "title": r.get("title", r["url"]),
                    "snippet": r.get("snippet", ""),
                }
            )
    return out


async def _fetch_snippet(ctx, tools, url: str) -> Optional[str]:
    ok, res = await try_tool(ctx, tools, "web_fetch", {"url": url})
    if ok and res is not None and res.ok and isinstance(res.data, dict):
        text = res.data.get("text") or res.data.get("content")
        if isinstance(text, str):
            return text
    return None


class ResearchProgram:
    name: str = "research"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: "Optional[object]",
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        query = ctx.task.prompt or ""
        meta = ctx.task.metadata or {}
        max_sources = int(meta.get("max_sources", DEFAULT_MAX_SOURCES))
        max_sources = max(1, min(max_sources, ctx.policy.max_steps))

        evidence: "list[dict]" = []

        # If the network is off or the search tool is missing, we degrade
        # honestly instead of hallucinating sources.
        network_ok = ctx.policy.allow_network and tools.has("web_search")
        if network_ok:
            hits = await _search(ctx, tools, query, max_sources)
            for i, hit in enumerate(hits):
                if ctx.budget.steps_left() <= 0:
                    break
                ctx.step()
                snippet = await _fetch_snippet(ctx, tools, hit["url"]) or hit["snippet"]
                ev = _evidence(
                    source=hit["url"],
                    title=hit["title"],
                    snippet=snippet,
                    used_for=f"answering: {query[:80]}",
                )
                evidence.append(ev)
                ctx.trajectory.log_observation(
                    f"collected evidence #{i + 1}: {hit['url']}", source="web"
                )

        evidence_path = ctx.new_artifact_json("evidence.json", {"evidence": evidence})
        ctx.trajectory.log_artifact("evidence.json", evidence_path, kind="json")

        # Build a cited response strictly from the evidence we actually have.
        lines = [f"# Research: {query}", ""]
        if evidence:
            lines.append("## Findings\n")
            for i, ev in enumerate(evidence, 1):
                lines.append(f"- {ev['snippet'][:200]} [{i}]")
            lines.append("\n## Sources\n")
            for i, ev in enumerate(evidence, 1):
                lines.append(f"[{i}] {ev['title']} -- {ev['source']}")
        else:
            reason = (
                "network access is disabled by policy"
                if not ctx.policy.allow_network
                else "no web search tool is available"
            )
            lines.append(
                "No evidence could be gathered because "
                f"{reason}. To avoid fabrication, this report makes no factual "
                "claims and cites no sources."
            )

        body = "\n".join(lines) + "\n"
        answer_path = ctx.new_artifact_text("response.md", body)
        ctx.trajectory.log_step(1, phase="done")

        return make_result(
            ctx,
            status="success",
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "evidence_count": len(evidence),
                "max_sources": max_sources,
                "network_enabled": ctx.policy.allow_network,
                "refused_fabrication": not evidence,
            },
        )


PROGRAM = ResearchProgram()


def get_program() -> ResearchProgram:
    return PROGRAM
