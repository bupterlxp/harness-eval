"""Execution Loop - state-machine driven research agent.

Implements the core FSM with explicit state enum and transition function.
Orchestrates multi-hop iterative retrieval, evidence management,
task decomposition, and output generation.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from harness.state import AgentState, AgentPhase, StateStore, EvidenceCard, SubTask
from harness.tools import ToolRegistry, ToolResult, build_default_registry, generate_uid
from harness.context import ContextManager, chunk_text, compute_relevance_score
from harness.lifecycle import LifecycleManager, HookEvent, build_default_hooks
from harness.evaluation import TrajectoryRecorder


# --- FSM Transition Table ---
# Maps (current_phase, condition) -> next_phase
TRANSITION_TABLE: dict[tuple[AgentPhase, str], AgentPhase] = {
    (AgentPhase.INIT, "ready"): AgentPhase.DECOMPOSE,
    (AgentPhase.INIT, "error"): AgentPhase.FAILED,
    (AgentPhase.DECOMPOSE, "tasks_ready"): AgentPhase.SEARCH,
    (AgentPhase.DECOMPOSE, "error"): AgentPhase.FAILED,
    (AgentPhase.SEARCH, "results_found"): AgentPhase.FETCH,
    (AgentPhase.SEARCH, "no_results"): AgentPhase.ANALYZE,
    (AgentPhase.SEARCH, "error"): AgentPhase.ANALYZE,
    (AgentPhase.FETCH, "content_extracted"): AgentPhase.ANALYZE,
    (AgentPhase.FETCH, "error"): AgentPhase.ANALYZE,
    (AgentPhase.ANALYZE, "gaps_found"): AgentPhase.SEARCH,
    (AgentPhase.ANALYZE, "sufficient"): AgentPhase.SYNTHESIZE,
    (AgentPhase.ANALYZE, "max_rounds"): AgentPhase.SYNTHESIZE,
    (AgentPhase.ANALYZE, "error"): AgentPhase.SYNTHESIZE,
    (AgentPhase.SYNTHESIZE, "outline_ready"): AgentPhase.GENERATE,
    (AgentPhase.SYNTHESIZE, "error"): AgentPhase.GENERATE,
    (AgentPhase.GENERATE, "done"): AgentPhase.COMPLETE,
    (AgentPhase.GENERATE, "error"): AgentPhase.FAILED,
}


def transition(current: AgentPhase, condition: str) -> AgentPhase:
    """Look up the next phase from the transition table."""
    key = (current, condition)
    if key in TRANSITION_TABLE:
        return TRANSITION_TABLE[key]
    # Fallback: if condition is 'error' and not in table, go to FAILED
    if condition == "error":
        return AgentPhase.FAILED
    raise ValueError(f"No transition defined for ({current.value}, {condition})")


class ExecutionLoop:
    """Main execution loop implementing the research agent FSM."""

    def __init__(
        self,
        question: str,
        output_dir: Path,
        max_rounds: int = 4,
        initial_breadth: int = 4,
        mode: str = "auto",
        registry: ToolRegistry | None = None,
    ):
        self._state = AgentState(
            question=question,
            mode=mode,
            max_rounds=max_rounds,
            initial_breadth=initial_breadth,
        )
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._registry = registry or build_default_registry()
        self._context = ContextManager(self._state, self._registry)
        self._lifecycle = LifecycleManager(self._state, timeout_seconds=600.0)
        self._recorder = TrajectoryRecorder(output_dir / "trajectory.jsonl")
        self._store = StateStore(state=self._state, checkpoint_dir=output_dir / "checkpoints")

        build_default_hooks(self._lifecycle)

    @classmethod
    def from_state_store(cls, store: StateStore, output_dir: Path) -> "ExecutionLoop":
        """Resume execution from a checkpoint."""
        loop = cls.__new__(cls)
        loop._state = store.state
        loop._output_dir = output_dir
        loop._output_dir.mkdir(parents=True, exist_ok=True)
        loop._registry = build_default_registry()
        loop._context = ContextManager(loop._state, loop._registry)
        loop._lifecycle = LifecycleManager(loop._state, timeout_seconds=600.0)
        loop._recorder = TrajectoryRecorder(output_dir / "trajectory.jsonl")
        loop._store = store
        build_default_hooks(loop._lifecycle)
        return loop

    async def run(self) -> dict[str, Any]:
        """Execute the main FSM loop until completion or failure."""
        try:
            while self._state.phase not in (AgentPhase.COMPLETE, AgentPhase.FAILED):
                # Timeout check
                if self._lifecycle.check_timeout():
                    await self._lifecycle.emit(HookEvent.ON_TIMEOUT)
                    self._state.phase = AgentPhase.FAILED
                    self._state.error_log.append("Overall timeout exceeded")
                    break

                step_start = time.time()
                self._state.step_count += 1

                # Execute current phase
                condition = await self._execute_phase()

                # Perform transition
                old_phase = self._state.phase
                new_phase = transition(old_phase, condition)
                await self._lifecycle.emit_transition(old_phase, new_phase)
                self._recorder.record_transition(old_phase.value, new_phase.value, condition)
                self._state.phase = new_phase

                # Record step timing
                step_duration = time.time() - step_start
                self._lifecycle.record_step_time(step_duration)

                # Periodic checkpoint
                if self._state.step_count % 3 == 0:
                    self._store.save_checkpoint()
                    await self._lifecycle.emit(HookEvent.ON_CHECKPOINT)

            # Final checkpoint
            self._store.save_checkpoint()

            # Build result
            status = "success" if self._state.phase == AgentPhase.COMPLETE else "failed"
            if self._state.phase == AgentPhase.COMPLETE and not self._state.final_answer:
                status = "partial"

            # Write final output
            if self._state.final_answer:
                answer_path = self._output_dir / "answer.md"
                with open(answer_path, "w", encoding="utf-8") as f:
                    f.write(self._state.final_answer)

            # Finalize trajectory
            stats = self._recorder.get_stats()
            self._recorder.finalize(status, summary=stats)

            await self._lifecycle.emit(HookEvent.ON_COMPLETE)
            await self._registry.close()

            return {
                "status": status,
                "trajectory": str(self._recorder.output_path),
                "steps": self._state.step_count,
                "evidence_cards": len(self._state.evidence_cards),
                "errors": self._state.error_log[-5:] if self._state.error_log else [],
            }

        except Exception as e:
            self._state.error_log.append(f"Fatal: {type(e).__name__}: {e}")
            await self._lifecycle.emit_error(e)
            self._recorder.finalize("failed", summary={"fatal_error": str(e)})
            await self._registry.close()
            return {
                "status": "failed",
                "trajectory": str(self._recorder.output_path),
                "steps": self._state.step_count,
                "evidence_cards": len(self._state.evidence_cards),
                "errors": self._state.error_log[-5:],
            }

    async def _execute_phase(self) -> str:
        """Execute the current phase and return the transition condition."""
        handlers = {
            AgentPhase.INIT: self._phase_init,
            AgentPhase.DECOMPOSE: self._phase_decompose,
            AgentPhase.SEARCH: self._phase_search,
            AgentPhase.FETCH: self._phase_fetch,
            AgentPhase.ANALYZE: self._phase_analyze,
            AgentPhase.SYNTHESIZE: self._phase_synthesize,
            AgentPhase.GENERATE: self._phase_generate,
        }
        handler = handlers.get(self._state.phase)
        if handler is None:
            return "error"
        try:
            return await handler()
        except Exception as e:
            self._state.error_log.append(f"Phase {self._state.phase.value} error: {e}")
            await self._lifecycle.emit_error(e)
            return "error"

    # --- Phase Implementations ---

    async def _phase_init(self) -> str:
        """Initialize: detect question type and set mode."""
        # Auto-detect mode
        if self._state.mode == "auto":
            result = await self._registry.dispatch(
                "llm_json",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify the following question. Is it:\n"
                            "- 'qa': A closed factual question with a specific answer (who, what, when, where, how much)\n"
                            "- 'report': An open exploratory question requiring analysis and synthesis\n"
                            "Return JSON: {\"mode\": \"qa\" or \"report\", \"reason\": \"brief explanation\"}"
                        ),
                    },
                    {"role": "user", "content": self._state.question},
                ],
            )
            if result.success and result.data.get("parsed"):
                detected = result.data["parsed"].get("mode", "report")
                self._state.detected_mode = detected if detected in ("qa", "report") else "report"
            else:
                self._state.detected_mode = "report"

            self._recorder.record_llm_call(
                phase="init",
                purpose="mode_detection",
                input_summary=self._state.question[:100],
                output_summary=f"mode={self._state.detected_mode}",
                duration_ms=result.duration_ms,
                success=result.success,
            )
        else:
            self._state.detected_mode = self._state.mode

        return "ready"

    async def _phase_decompose(self) -> str:
        """Decompose question into sub-tasks using analysis framework."""
        breadth = self._state.initial_breadth
        # Halve breadth for subsequent rounds
        if self._state.current_round > 0:
            breadth = max(2, breadth // (2 ** self._state.current_round))

        prompt = (
            f"You are a research planner. Decompose the following research question into {breadth} "
            f"sub-queries for web search. Use MECE (Mutually Exclusive, Collectively Exhaustive) decomposition.\n\n"
            f"Question: {self._state.question}\n\n"
        )

        if self._state.completed_queries:
            prompt += f"Already searched: {', '.join(self._state.completed_queries[-10:])}\n\n"

        if self._state.evidence_cards:
            summaries = [f"- {c.summary}" for c in self._state.evidence_cards[:10]]
            prompt += f"Evidence already gathered:\n{''.join(summaries)}\n\n"
            prompt += "Focus on gaps in the current evidence. What is still missing or unclear?\n\n"

        prompt += (
            f"Return JSON: {{\"sub_queries\": [\"query1\", \"query2\", ...], "
            f"\"framework\": \"mece\", \"reasoning\": \"brief explanation\"}}"
        )

        result = await self._registry.dispatch(
            "llm_json",
            messages=[{"role": "user", "content": prompt}],
        )

        self._recorder.record_llm_call(
            phase="decompose",
            purpose="task_decomposition",
            input_summary=f"round={self._state.current_round}, breadth={breadth}",
            output_summary=f"generated sub-queries",
            duration_ms=result.duration_ms,
            success=result.success,
        )

        if result.success and result.data.get("parsed"):
            parsed = result.data["parsed"]
            queries = parsed.get("sub_queries", [])
            if isinstance(queries, list) and queries:
                self._state.pending_queries = queries[:breadth]
                self._state.sub_tasks = [
                    SubTask(
                        task_id=f"task_{self._state.current_round}_{i}",
                        query=q,
                        depth=self._state.current_round,
                    )
                    for i, q in enumerate(self._state.pending_queries)
                ]
                return "tasks_ready"

        # Fallback: use question directly
        self._state.pending_queries = [self._state.question]
        self._state.sub_tasks = [
            SubTask(task_id="task_0_0", query=self._state.question, depth=0)
        ]
        return "tasks_ready"

    async def _phase_search(self) -> str:
        """Execute search queries concurrently."""
        if not self._state.pending_queries:
            return "no_results"

        await self._lifecycle.emit(HookEvent.PRE_SEARCH)

        # Run searches concurrently
        async def do_search(query: str) -> tuple[str, ToolResult]:
            result = await self._registry.dispatch("search_web", query=query)
            return query, result

        tasks = [do_search(q) for q in self._state.pending_queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_search_results: list[dict[str, Any]] = []
        for item in results:
            if isinstance(item, Exception):
                self._state.error_log.append(f"Search error: {item}")
                continue
            query, result = item
            self._state.completed_queries.append(query)

            if result.success and result.data:
                for r in result.data:
                    if isinstance(r, dict) and r.get("url"):
                        # Dedup by URL
                        if r["url"] not in self._state.visited_urls:
                            all_search_results.append(r)

                self._recorder.record_search(
                    phase="search",
                    query=query,
                    results=result.data if isinstance(result.data, list) else [],
                    duration_ms=result.duration_ms,
                    success=True,
                )
            else:
                self._recorder.record_search(
                    phase="search",
                    query=query,
                    results=[],
                    duration_ms=result.duration_ms,
                    success=False,
                    error=result.error,
                )

        self._state.pending_queries = []
        self._state.search_results_buffer = all_search_results

        await self._lifecycle.emit(HookEvent.POST_SEARCH)

        if all_search_results:
            return "results_found"
        return "no_results"

    async def _phase_fetch(self) -> str:
        """Fetch content from search results and extract evidence."""
        if not self._state.search_results_buffer:
            return "content_extracted"

        await self._lifecycle.emit(HookEvent.PRE_FETCH)

        # Limit concurrent fetches
        max_fetch = 5
        urls_to_fetch = []
        for r in self._state.search_results_buffer[:max_fetch]:
            url = r.get("url", "")
            if url and url not in self._state.visited_urls:
                urls_to_fetch.append((url, r.get("title", ""), r.get("snippet", "")))

        async def do_fetch(url: str, title: str, snippet: str) -> tuple[str, str, str, ToolResult]:
            result = await self._registry.dispatch("fetch_url", url=url)
            return url, title, snippet, result

        tasks = [do_fetch(u, t, s) for u, t, s in urls_to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item in results:
            if isinstance(item, Exception):
                continue
            url, title, snippet, result = item
            self._state.visited_urls.add(url)

            if not result.success:
                self._recorder.record_fetch(
                    phase="fetch", url=url, content_length=0,
                    duration_ms=result.duration_ms, success=False, error=result.error,
                )
                continue

            content = result.data.get("content", "") if isinstance(result.data, dict) else ""
            if not content or len(content.strip()) < 50:
                continue

            self._recorder.record_fetch(
                phase="fetch", url=url, content_length=len(content),
                duration_ms=result.duration_ms, success=True,
            )

            # Chunk and score
            chunks = chunk_text(content)
            for i, chunk in enumerate(chunks):
                relevance = compute_relevance_score(chunk, self._state.question)
                if relevance < 0.15:
                    continue  # Skip irrelevant chunks

                uid = generate_uid(chunk, url)
                card = EvidenceCard(
                    uid=uid,
                    title=title or url.split("/")[-1],
                    content=chunk,
                    source_url=url,
                    summary=snippet or chunk[:150],
                    tags=self._extract_tags(chunk),
                    quality_score=relevance,
                    chunk_index=i,
                )
                self._context.add_evidence(card)

        self._state.search_results_buffer = []
        await self._lifecycle.emit(HookEvent.POST_FETCH)
        return "content_extracted"

    async def _phase_analyze(self) -> str:
        """Analyze current evidence for gaps and decide next action."""
        self._state.current_round += 1
        await self._lifecycle.emit(HookEvent.ON_ROUND_END)

        # Check termination conditions
        if self._state.current_round >= self._state.max_rounds:
            return "max_rounds"

        if not self._state.evidence_cards:
            # No evidence found at all, try again with different queries
            if self._state.current_round < self._state.max_rounds:
                return "gaps_found"
            return "max_rounds"

        # Ask LLM to analyze gaps
        context_window = self._context.build_context_window(include_metadata=True)
        reminder = self._context.get_near_limit_reminder()

        prompt = (
            f"You are a research analyst. Evaluate the evidence gathered so far for the question:\n"
            f"\"{self._state.question}\"\n\n"
            f"Current evidence ({len(self._state.evidence_cards)} cards):\n"
            f"{context_window[:5000]}\n\n"
        )

        if reminder:
            prompt += f"\n{reminder}\n\n"

        prompt += (
            "Determine:\n"
            "1. Is the evidence sufficient to answer the question comprehensively?\n"
            "2. What gaps remain?\n"
            "3. Are there contradictions that need resolution?\n\n"
            "Return JSON: {\"sufficient\": true/false, \"gaps\": [\"gap1\", ...], "
            "\"contradictions\": [{\"claim_a\": \"...\", \"claim_b\": \"...\", "
            "\"source_a_uid\": \"...\", \"source_b_uid\": \"...\"}], "
            "\"follow_up_queries\": [\"query1\", ...]}"
        )

        result = await self._registry.dispatch(
            "llm_json",
            messages=[{"role": "user", "content": prompt}],
        )

        self._recorder.record_llm_call(
            phase="analyze",
            purpose="gap_analysis",
            input_summary=f"round={self._state.current_round}, cards={len(self._state.evidence_cards)}",
            output_summary="gap analysis complete",
            duration_ms=result.duration_ms,
            success=result.success,
        )

        if result.success and result.data.get("parsed"):
            parsed = result.data["parsed"]

            # Handle contradictions
            contradictions = parsed.get("contradictions", [])
            for contra in contradictions:
                uid_a = contra.get("source_a_uid", "")
                uid_b = contra.get("source_b_uid", "")
                if uid_a and uid_b:
                    for card in self._state.evidence_cards:
                        if card.uid == uid_a and uid_b not in card.contradicts:
                            card.contradicts.append(uid_b)
                        if card.uid == uid_b and uid_a not in card.contradicts:
                            card.contradicts.append(uid_a)

            # Check sufficiency
            if parsed.get("sufficient", False):
                return "sufficient"

            # Set up follow-up queries
            follow_ups = parsed.get("follow_up_queries", [])
            if follow_ups:
                self._state.pending_queries = follow_ups[:self._current_breadth()]
                return "gaps_found"

        # Default: if we have some evidence, proceed to synthesis
        if len(self._state.evidence_cards) >= 3:
            return "sufficient"
        return "gaps_found"

    async def _phase_synthesize(self) -> str:
        """Synthesize evidence into an outline structure."""
        detected_mode = self._state.detected_mode or "report"

        if detected_mode == "qa":
            return await self._synthesize_qa()
        else:
            return await self._synthesize_report()

    async def _synthesize_qa(self) -> str:
        """Synthesize for QA mode: build evidence chain to precise answer."""
        context_window = self._context.build_context_window()
        contradiction_summary = self._context.get_contradiction_summary()

        prompt = (
            f"Based on the evidence below, provide a precise answer to the question:\n"
            f"\"{self._state.question}\"\n\n"
            f"Evidence:\n{context_window}\n\n"
        )
        if contradiction_summary:
            prompt += f"\n{contradiction_summary}\n\n"

        prompt += (
            "Requirements:\n"
            "- Give a direct, precise answer first\n"
            "- Then provide an evidence chain showing how you arrived at the answer\n"
            "- Use numbered citations [N] for each factual claim\n"
            "- If sources disagree, present both positions with citations\n"
            "- Build a reference list of actually-cited sources\n\n"
            "Return JSON: {\"answer\": \"direct answer\", \"evidence_chain\": \"reasoning with [N] citations\", "
            "\"citations\": {\"1\": {\"url\": \"...\", \"title\": \"...\"}, ...}, "
            "\"confidence\": 0.0-1.0, \"contradictions_noted\": true/false}"
        )

        result = await self._registry.dispatch(
            "llm_json",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
        )

        self._recorder.record_llm_call(
            phase="synthesize",
            purpose="qa_synthesis",
            input_summary=f"cards={len(self._state.evidence_cards)}",
            output_summary="QA answer synthesized",
            duration_ms=result.duration_ms,
            success=result.success,
        )

        if result.success and result.data.get("parsed"):
            parsed = result.data["parsed"]
            self._state.outline = [{"type": "qa", "data": parsed}]

            # Store citations
            citations = parsed.get("citations", {})
            for cid, info in citations.items():
                if isinstance(info, dict):
                    self._state.citations[str(cid)] = info.get("url", "")
                elif isinstance(info, str):
                    self._state.citations[str(cid)] = info

        return "outline_ready"

    async def _synthesize_report(self) -> str:
        """Synthesize for report mode: create structured outline."""
        context_window = self._context.build_context_window()
        contradiction_summary = self._context.get_contradiction_summary()

        prompt = (
            f"Create a structured outline for a research report answering:\n"
            f"\"{self._state.question}\"\n\n"
            f"Available evidence ({len(self._state.evidence_cards)} cards):\n"
            f"{context_window[:8000]}\n\n"
        )
        if contradiction_summary:
            prompt += f"\n{contradiction_summary}\n\n"

        prompt += (
            "Requirements:\n"
            "- Create 3-6 main sections with descriptive titles\n"
            "- Each section should map to specific evidence cards (by UID)\n"
            "- Include an introduction and conclusion section\n"
            "- Note which sections should discuss contradictions\n\n"
            "Return JSON: {\"title\": \"report title\", \"sections\": ["
            "{\"heading\": \"...\", \"key_points\": [\"...\"], \"evidence_uids\": [\"...\"], "
            "\"has_contradictions\": false}, ...]}"
        )

        result = await self._registry.dispatch(
            "llm_json",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )

        self._recorder.record_llm_call(
            phase="synthesize",
            purpose="report_outline",
            input_summary=f"cards={len(self._state.evidence_cards)}",
            output_summary="outline created",
            duration_ms=result.duration_ms,
            success=result.success,
        )

        if result.success and result.data.get("parsed"):
            parsed = result.data["parsed"]
            self._state.outline = parsed.get("sections", [])

            # Store report title
            if "title" in parsed:
                self._state.outline.insert(0, {"type": "title", "heading": parsed["title"]})

        return "outline_ready"

    async def _phase_generate(self) -> str:
        """Generate the final output (report or QA answer)."""
        detected_mode = self._state.detected_mode or "report"
        await self._lifecycle.emit(HookEvent.PRE_GENERATE)

        if detected_mode == "qa":
            answer = await self._generate_qa_output()
        else:
            answer = await self._generate_report_output()

        self._state.final_answer = answer
        await self._lifecycle.emit(HookEvent.POST_GENERATE)

        if answer:
            return "done"
        return "error"

    async def _generate_qa_output(self) -> str:
        """Generate formatted QA output."""
        if not self._state.outline:
            return ""

        qa_data = None
        for item in self._state.outline:
            if isinstance(item, dict) and item.get("type") == "qa":
                qa_data = item.get("data", {})
                break

        if not qa_data:
            return ""

        # Format the QA output
        parts = []
        parts.append(f"# Answer\n\n{qa_data.get('answer', 'No answer available.')}\n")
        parts.append(f"\n## Evidence Chain\n\n{qa_data.get('evidence_chain', '')}\n")

        # Add contradiction note
        if qa_data.get("contradictions_noted"):
            parts.append("\n*Note: Sources present conflicting information on some points. See citations for details.*\n")

        # Build reference list
        citations = qa_data.get("citations", {})
        if citations:
            parts.append("\n## References\n")
            for cid, info in sorted(citations.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                if isinstance(info, dict):
                    title = info.get("title", "Source")
                    url = info.get("url", "")
                    parts.append(f"[{cid}] [{title}]({url})\n")
                elif isinstance(info, str):
                    parts.append(f"[{cid}] {info}\n")

        confidence = qa_data.get("confidence", 0.0)
        parts.append(f"\n---\n*Confidence: {confidence:.0%}*\n")

        return "\n".join(parts)

    async def _generate_report_output(self) -> str:
        """Generate full report, section by section."""
        if not self._state.outline:
            # Fallback: generate a simple summary
            return await self._generate_fallback_report()

        context_window = self._context.build_context_window()
        sections_content: list[str] = []
        citation_counter = 1
        citation_map: dict[str, int] = {}  # url -> citation number

        for section in self._state.outline:
            if not isinstance(section, dict):
                continue
            if section.get("type") == "title":
                sections_content.append(f"# {section.get('heading', 'Research Report')}\n")
                continue

            heading = section.get("heading", "Section")
            evidence_uids = section.get("evidence_uids", [])
            key_points = section.get("key_points", [])
            has_contradictions = section.get("has_contradictions", False)

            # Gather relevant evidence for this section
            section_evidence = []
            for card in self._state.evidence_cards:
                if card.uid in evidence_uids:
                    section_evidence.append(card)

            # If no specific UIDs matched, use top cards
            if not section_evidence:
                section_evidence = sorted(
                    self._state.evidence_cards,
                    key=lambda c: c.quality_score,
                    reverse=True,
                )[:5]

            evidence_text = "\n".join(
                f"[{c.uid}] ({c.source_url}): {c.content[:500]}"
                for c in section_evidence
            )

            prompt = (
                f"Write the \"{heading}\" section of a research report on:\n"
                f"\"{self._state.question}\"\n\n"
                f"Key points to cover: {json.dumps(key_points)}\n\n"
                f"Evidence to use:\n{evidence_text}\n\n"
            )

            if has_contradictions:
                prompt += "NOTE: Present contradicting viewpoints explicitly with citations for each position.\n\n"

            prompt += (
                "Requirements:\n"
                "- Write 2-4 paragraphs\n"
                "- Use inline citations [N] for every factual claim\n"
                "- Be analytical, not just descriptive\n"
                "- If sources conflict, present both sides\n"
                "Return the section text only (markdown formatted)."
            )

            result = await self._registry.dispatch(
                "llm_generate",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=2000,
            )

            self._recorder.record_llm_call(
                phase="generate",
                purpose=f"section:{heading}",
                input_summary=f"evidence_count={len(section_evidence)}",
                output_summary=f"section generated",
                duration_ms=result.duration_ms,
                success=result.success,
            )

            if result.success and result.data.get("content"):
                section_text = result.data["content"]

                # Track citations used
                for card in section_evidence:
                    if card.source_url not in citation_map:
                        citation_map[card.source_url] = citation_counter
                        citation_counter += 1

                sections_content.append(f"\n## {heading}\n\n{section_text}\n")
            else:
                sections_content.append(f"\n## {heading}\n\n*Section generation failed.*\n")

        # Build reference list (only actually-cited sources)
        if citation_map:
            sections_content.append("\n## References\n")
            for url, num in sorted(citation_map.items(), key=lambda x: x[1]):
                # Find title for URL
                title = url
                for card in self._state.evidence_cards:
                    if card.source_url == url:
                        title = card.title
                        break
                sections_content.append(f"[{num}] [{title}]({url})\n")

        return "\n".join(sections_content)

    async def _generate_fallback_report(self) -> str:
        """Generate a simple report when outline generation failed."""
        context_window = self._context.build_context_window()

        prompt = (
            f"Write a concise research report answering:\n"
            f"\"{self._state.question}\"\n\n"
            f"Based on the following evidence:\n{context_window[:10000]}\n\n"
            "Requirements:\n"
            "- Include introduction, findings, and conclusion\n"
            "- Use inline citations [N] and build a reference list\n"
            "- If evidence is contradictory, note disagreements\n"
        )

        result = await self._registry.dispatch(
            "llm_generate",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=4000,
        )

        if result.success and result.data.get("content"):
            return result.data["content"]
        return "# Research Report\n\n*Report generation failed. See trajectory for details.*\n"

    # --- Helper Methods ---

    def _current_breadth(self) -> int:
        """Get current breadth (halves per depth level)."""
        b = self._state.initial_breadth
        for _ in range(self._state.current_round):
            b = max(2, b // 2)
        return b

    def _extract_tags(self, text: str) -> list[str]:
        """Extract simple topic tags from text."""
        # Use first few significant words as tags
        words = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", text)
        # Deduplicate and limit
        seen = set()
        tags = []
        for w in words:
            w_lower = w.lower()
            if w_lower not in seen and len(w) > 3:
                seen.add(w_lower)
                tags.append(w)
            if len(tags) >= 5:
                break
        return tags
