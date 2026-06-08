"""Scaffold-native research-agent harness.

Accepts a research question, performs information retrieval, evaluates sources,
organizes evidence, and produces grounded answers or structured reports.

Implements GeneratedHarnessProgram.run(ctx, tools, llm) on top of
harness_scaffold.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.adapters.bmk_io import EVIDENCE_JSON
from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result, try_tool
from harness_scaffold.tools.registry import ToolRegistry

from evidence import EvidenceStore, score_relevance
from planner import ResearchPlan, SubQuestion, decompose, detect_answer_type, plan_followup_queries
from verifier import check_answer_groundedness, check_short_answer, extract_final_answer

MAX_EVIDENCE_ITEMS = 40
MAX_CONTEXT_CHARS = 16000
MAX_FETCH_PER_QUERY = 3
SYSTEM_PROMPT = (
    "You are a precise research assistant. Answer questions using ONLY the "
    "provided evidence. Cite evidence using [E001] style references. "
    "If the evidence is insufficient, say so explicitly. "
    "Do not fabricate information. Be concise and factual."
)


class GeneratedHarnessProgram:
    name = "research_agent"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        for k, v in (ctx.task.metadata or {}).items():
            if k not in ctx.metadata:
                ctx.metadata[k] = v
        question = ctx.task.prompt.strip()
        if not question:
            return self._fail(ctx, "No research question provided.", ErrorCode.CONTRACT_ERROR)

        plan = decompose(question)
        ctx.trajectory.log_info(
            "plan_created",
            answer_type=plan.answer_type,
            num_subquestions=len(plan.sub_questions),
        )

        evidence = EvidenceStore()
        search_available, _ = await try_tool(ctx, tools, "web_search", {"query": "__probe__"})
        fetch_available, _ = await try_tool(ctx, tools, "web_fetch", {"url": "__probe__"})

        if not search_available and not fetch_available:
            ctx.trajectory.log_info("no_search_tools", note="falling back to LLM-only mode")
            if llm is None:
                return self._fail(
                    ctx,
                    "No search tools and no LLM available. Cannot research.",
                    ErrorCode.DEPENDENCY_ERROR,
                )

        search_round = 0
        answer = ""
        for round_idx in range(plan.max_search_rounds):
            if ctx.budget.exceeded():
                ctx.trajectory.log_info("budget_exceeded", round=round_idx)
                break
            ctx.check_abort(stage="research_loop")
            search_round += 1
            ctx.step()

            for sq in plan.sub_questions:
                if ctx.budget.exceeded():
                    break
                await self._search_subquestion(ctx, tools, sq, evidence, search_available)
                if len(evidence.items) >= MAX_EVIDENCE_ITEMS:
                    break

            if len(evidence.items) > 0 and fetch_available:
                await self._fetch_top_sources(ctx, tools, evidence)

            for item in evidence.items:
                item.relevance_score = score_relevance(question, item)

            if llm is not None and len(evidence.items) > 0:
                evidence_context = evidence.compress_for_context(MAX_CONTEXT_CHARS)
                answer = await self._synthesize(ctx, llm, question, plan, evidence_context)
                if not answer.strip():
                    ctx.trajectory.log_info("llm_empty_response", round=round_idx)
                    continue
                ground = check_answer_groundedness(answer, [it.id for it in evidence.items], evidence)
                if ground["groundedness"] >= 0.5:
                    ctx.trajectory.log_info("answer_synthesized", round=round_idx, groundedness=round(ground["groundedness"], 2))
                    break
                else:
                    ctx.trajectory.log_info("answer_low_groundedness", round=round_idx, groundedness=round(ground["groundedness"], 2))
                    followup = plan_followup_queries(question, [it.excerpt for it in evidence.get_top(5)])
                    for fq in followup[:2]:
                        await self._do_search(ctx, tools, fq, evidence, search_available)
            elif llm is not None and len(evidence.items) == 0:
                ctx.trajectory.log_info("no_evidence_llm_fallback", round=round_idx)
                answer = await self._synthesize(ctx, llm, question, plan, "No evidence was retrieved from search.")
                if answer.strip():
                    break

        no_answer = False
        if not answer and llm is not None:
            evidence_context = evidence.compress_for_context(MAX_CONTEXT_CHARS) if evidence.items else "No evidence collected."
            answer = await self._synthesize(ctx, llm, question, plan, evidence_context)
        elif not answer and evidence.items:
            answer = self._build_evidence_only_answer(question, evidence)
        elif not answer:
            answer = "Unable to produce an answer: no LLM available and no evidence collected."
            no_answer = True

        if not answer.strip():
            if evidence.items:
                answer = self._build_evidence_only_answer(question, evidence)
            else:
                answer = "Unable to produce an answer: LLM call failed and no evidence collected."
            no_answer = True
        elif answer.startswith("Unable to produce") or answer.startswith("Insufficient evidence"):
            no_answer = True

        final_answer = answer
        if plan.answer_type in ("number", "date", "name", "location", "boolean", "choice", "factual"):
            short = extract_final_answer(answer, plan.answer_type)
            if short:
                final_answer = short

        final_status = "partial" if (no_answer or len(evidence.items) == 0) else "success"

        answer_path = ctx.new_artifact_text("answer.md", self._format_answer(final_answer, plan, evidence))
        ctx.new_artifact_text("response.md", final_answer)
        ctx.new_artifact_json("answer.json", {
            "answer": final_answer,
            "answer_type": plan.answer_type,
            "question": question,
        })

        evidence_data = evidence.to_json()
        ctx.new_artifact_json(EVIDENCE_JSON, evidence_data)
        sources_data = [
            {"id": e["id"], "query": e["query"], "url": e["url"], "title": e["title"], "excerpt": e["excerpt"][:300], "relevance_score": e["relevance_score"]}
            for e in evidence_data
        ]
        ctx.new_artifact_json("sources.json", sources_data)

        result_json = {
            "status": final_status,
            "trajectory": "trajectory.jsonl",
            "answer_path": "answer.md",
            "evidence_path": EVIDENCE_JSON,
            "answer_type": plan.answer_type,
            "evidence_count": len(evidence.items),
            "search_rounds": search_round,
        }
        ctx.new_artifact_json("result.json", result_json)
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="done", note="research_complete")

        return make_result(
            ctx,
            status=final_status,
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "answer_type": plan.answer_type,
                "evidence_count": len(evidence.items),
                "search_rounds": search_round,
            },
        )

    async def _search_subquestion(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        sq: SubQuestion,
        evidence: EvidenceStore,
        search_available: bool,
    ) -> None:
        for query in sq.queries:
            if len(evidence.items) >= MAX_EVIDENCE_ITEMS:
                break
            await self._do_search(ctx, tools, query, evidence, search_available)

    async def _do_search(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        query: str,
        evidence: EvidenceStore,
        search_available: bool,
    ) -> None:
        if not search_available:
            return
        ok, res = await try_tool(ctx, tools, "web_search", {
            "query": query,
            "max_results": 5,
        })
        if not ok or res is None or not res.ok:
            ctx.trajectory.log_info("search_failed", query=query)
            return
        data = res.data
        if not isinstance(data, dict):
            return
        results = data.get("results", [])
        now = time.time()
        evidence.search_results_to_evidence(query, results, retrieval_time=now)
        ctx.trajectory.log_info("search_completed", query=query, results=len(results))

    async def _fetch_top_sources(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        evidence: EvidenceStore,
    ) -> None:
        top = evidence.get_top(MAX_FETCH_PER_QUERY)
        for item in top:
            if not item.url or item.url.startswith("file://"):
                continue
            if item.excerpt and len(item.excerpt) > 200:
                continue
            ok, res = await try_tool(ctx, tools, "web_fetch", {"url": item.url})
            if ok and res is not None and res.ok and isinstance(res.data, dict):
                content = res.data.get("content", "")
                if content and len(content) > len(item.excerpt):
                    item.excerpt = content[:1000]
                    item.relevance_score = score_relevance(ctx.task.prompt, item)
                ctx.trajectory.log_info("fetch_completed", url=item.url, content_len=len(content))
            else:
                ctx.trajectory.log_info("fetch_failed", url=item.url)
            if ctx.budget.exceeded():
                break

    async def _synthesize(
        self,
        ctx: RuntimeContext,
        llm: Any,
        question: str,
        plan: ResearchPlan,
        evidence_context: str,
    ) -> str:
        ctx.trajectory.log_llm_call(model=getattr(llm, "model", "unknown"))

        if plan.answer_type in ("number", "date", "name", "location", "boolean", "choice", "factual"):
            prompt = self._build_short_answer_prompt(question, plan.answer_type, evidence_context)
        else:
            prompt = self._build_report_prompt(question, evidence_context)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        messages = self._merge_messages(messages)

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = await llm.complete(messages, timeout=ctx.policy.max_llm_seconds)
                ctx.trajectory.log_llm_result(
                    model=response.model,
                    usage=response.usage,
                    text_preview=response.text[:500] if response.text else "",
                )
                return response.text or ""
            except Exception as exc:
                ctx.trajectory.log_error({
                    "error_code": ErrorCode.LLM_ERROR.value,
                    "message": f"LLM synthesis failed (attempt {attempt + 1}/{max_retries + 1}): {exc}",
                    "stage": "synthesize",
                })
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    return ""

    def _build_short_answer_prompt(self, question: str, answer_type: str, evidence: str) -> str:
        type_hints = {
            "number": "a single number",
            "date": "a specific date",
            "name": "a specific name",
            "location": "a specific location",
            "boolean": "yes or no",
            "choice": "one of the options",
            "factual": "a concise factual answer",
        }
        hint = type_hints.get(answer_type, "a concise factual answer")
        return (
            f"Question: {question}\n\n"
            f"Evidence:\n{evidence}\n\n"
            f"Based ONLY on the evidence above, provide {hint}. "
            f"If the evidence does not contain the answer, say 'Insufficient evidence'. "
            f"Cite evidence using [E001] format. "
            f"Put your final answer on the first line."
        )

    def _build_report_prompt(self, question: str, evidence: str) -> str:
        return (
            f"Question: {question}\n\n"
            f"Evidence:\n{evidence}\n\n"
            f"Based on the evidence above, write a well-structured answer. "
            f"Cite every factual claim using [E001] format. "
            f"If sources disagree, note the conflict and choose the best-supported answer. "
            f"If the evidence is insufficient for any part, say so explicitly. "
            f"Start with a direct answer, then provide supporting details."
        )

    @staticmethod
    def _merge_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for msg in messages:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(dict(msg))
        if merged and merged[-1]["role"] == "assistant":
            merged.append({"role": "user", "content": "Continue."})
        if not merged or merged[-1]["role"] != "user":
            merged.append({"role": "user", "content": "Please provide the answer."})
        return merged

    def _format_answer(self, answer: str, plan: ResearchPlan, evidence: EvidenceStore) -> str:
        lines = [
            f"# Research Answer\n",
            f"**Question:** {plan.original_question}\n",
            f"**Answer Type:** {plan.answer_type}\n",
            f"## Answer\n",
            answer,
            f"\n## Sources ({len(evidence.items)} items)\n",
        ]
        for item in evidence.get_top(10):
            lines.append(f"- [{item.id}] {item.title} — {item.url}")
        return "\n".join(lines)

    @staticmethod
    def _build_evidence_only_answer(question: str, evidence: EvidenceStore) -> str:
        top = evidence.get_top(5)
        if not top:
            return "Insufficient evidence to answer the question."
        parts: list[str] = [f"Based on available evidence for: {question}\n"]
        for item in top:
            parts.append(f"- [{item.id}] {item.excerpt[:300]}")
        return "\n".join(parts)

    def _fail(self, ctx: RuntimeContext, message: str, error_code: ErrorCode) -> HarnessResult:
        error_obj = {
            "error_code": error_code.value,
            "message": message,
            "stage": self.name,
        }
        ctx.trajectory.log_error(error_obj)
        ctx.new_artifact_json("result.json", {
            "status": "failed",
            "trajectory": "trajectory.jsonl",
            "error": message,
        })
        ans = ctx.new_artifact_text("response.md", f"# Research Failed\n\n{message}\n")
        return make_result(ctx, status=error_code.value, answer_path=ans, metadata={"program": self.name, "error": message})


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
