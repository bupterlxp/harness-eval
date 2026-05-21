"""Execution Loop — state-machine driven execution.

Implements explicit FSM with state enum and transition function.
Drives the entire creative writing process from task analysis to final output.
"""

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from harness.tools import ToolRegistry, ToolResult, create_default_registry
from harness.context import ContextManager, MemoryDeduplicator, estimate_tokens
from harness.state import StateStore, WritingState
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryRecorder


class Phase(str, Enum):
    """FSM states for the creative writing process."""
    INIT = "INIT"
    TASK_ANALYSIS = "TASK_ANALYSIS"
    STYLE_SETUP = "STYLE_SETUP"
    PLANNING = "PLANNING"
    # Longform-specific
    CHAPTER_PLANNING = "CHAPTER_PLANNING"
    DRAFTING = "DRAFTING"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    CONSISTENCY_CHECK = "CONSISTENCY_CHECK"
    # Shortform-specific
    SCENARIO_ANALYSIS = "SCENARIO_ANALYSIS"
    SHORTFORM_DRAFTING = "SHORTFORM_DRAFTING"
    # Common
    CRITIQUE = "CRITIQUE"
    REVISION = "REVISION"
    FINALIZATION = "FINALIZATION"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


# Transition table: current_phase -> next_phase (based on conditions)
TRANSITION_TABLE: dict[Phase, dict[str, Phase]] = {
    Phase.INIT: {
        "start": Phase.TASK_ANALYSIS,
    },
    Phase.TASK_ANALYSIS: {
        "analyzed": Phase.STYLE_SETUP,
        "error": Phase.FAILED,
    },
    Phase.STYLE_SETUP: {
        "longform": Phase.PLANNING,
        "shortform": Phase.SCENARIO_ANALYSIS,
        "error": Phase.FAILED,
    },
    Phase.PLANNING: {
        "outline_complete": Phase.CHAPTER_PLANNING,
        "error": Phase.FAILED,
    },
    Phase.CHAPTER_PLANNING: {
        "chapter_ready": Phase.DRAFTING,
        "error": Phase.FAILED,
    },
    Phase.DRAFTING: {
        "scene_complete": Phase.MEMORY_UPDATE,
        "chapter_complete": Phase.CONSISTENCY_CHECK,
        "error": Phase.FAILED,
    },
    Phase.MEMORY_UPDATE: {
        "updated": Phase.DRAFTING,
        "chapter_done": Phase.CONSISTENCY_CHECK,
    },
    Phase.CONSISTENCY_CHECK: {
        "consistent": Phase.CRITIQUE,
        "violations_found": Phase.REVISION,
        "next_chapter": Phase.CHAPTER_PLANNING,
    },
    Phase.SCENARIO_ANALYSIS: {
        "analyzed": Phase.SHORTFORM_DRAFTING,
        "error": Phase.FAILED,
    },
    Phase.SHORTFORM_DRAFTING: {
        "draft_complete": Phase.CRITIQUE,
        "error": Phase.FAILED,
    },
    Phase.CRITIQUE: {
        "scores_acceptable": Phase.FINALIZATION,
        "needs_revision": Phase.REVISION,
        "max_revisions_reached": Phase.FINALIZATION,
    },
    Phase.REVISION: {
        "revised": Phase.CRITIQUE,
        "length_violation": Phase.REVISION,
        "max_retries": Phase.FINALIZATION,
    },
    Phase.FINALIZATION: {
        "done": Phase.COMPLETE,
    },
    Phase.COMPLETE: {},
    Phase.FAILED: {},
}


@dataclass
class WritingTask:
    """Configuration for a writing task."""
    prompt: str
    mode: Optional[str] = None  # "longform" or "shortform", auto-detected if None
    max_iterations: int = 20
    max_revisions: int = 5
    token_budget: int = 120000
    score_threshold: float = 0.7  # Minimum average score to pass critique
    length_protection_ratio: float = 0.8  # Revision must be >= 80% of original


class ExecutionLoop:
    """State-machine driven execution loop for creative writing."""

    def __init__(self, task: WritingTask, state_store: StateStore,
                 lifecycle: LifecycleManager, recorder: TrajectoryRecorder,
                 output_dir: Path):
        self.task = task
        self.state_store = state_store
        self.lifecycle = lifecycle
        self.recorder = recorder
        self.output_dir = output_dir

        self.tools = create_default_registry()
        self.context_mgr = ContextManager(token_budget=task.token_budget)
        self.deduplicator = MemoryDeduplicator()

        # Internal tracking
        self._revision_retries = 0
        self._max_revision_retries = 3
        self._scenes_written_this_chapter = 0
        self._total_chapters_planned = 0

    def run(self) -> str:
        """Execute the FSM until completion or failure. Returns status string."""
        ws = self.state_store.get_state()
        ws.task_prompt = self.task.prompt

        # If resuming, use stored phase; otherwise start at INIT
        if ws.current_phase == "INIT":
            current_phase = Phase.INIT
        else:
            current_phase = Phase(ws.current_phase)

        iteration = ws.iteration

        while current_phase not in (Phase.COMPLETE, Phase.FAILED):
            # Check termination conditions
            if iteration >= self.task.max_iterations:
                print(f"Max iterations ({self.task.max_iterations}) reached. Finalizing.")
                current_phase = Phase.FINALIZATION

            if self.lifecycle.check_timeout(current_phase.value, iteration):
                print("Timeout reached. Finalizing.")
                current_phase = Phase.FINALIZATION

            # Execute current phase
            self.lifecycle.enter_phase(current_phase.value, iteration)
            ws.current_phase = current_phase.value
            ws.iteration = iteration

            try:
                transition_key = self._execute_phase(current_phase, ws)
            except Exception as e:
                self.lifecycle.handle_failure(e, current_phase.value, iteration)
                transition_key = "error"

            self.lifecycle.exit_phase(current_phase.value, iteration)

            # Transition to next phase
            transitions = TRANSITION_TABLE.get(current_phase, {})
            next_phase = transitions.get(transition_key)

            if next_phase is None:
                # If no valid transition, try to finalize
                if transition_key == "error":
                    current_phase = Phase.FAILED
                else:
                    print(f"No transition for {current_phase}:{transition_key}, finalizing.")
                    current_phase = Phase.FINALIZATION
            else:
                current_phase = next_phase

            # Save checkpoint periodically
            if iteration % 3 == 0:
                cp_path = self.state_store.save_checkpoint(current_phase.value)
                self.lifecycle.notify_checkpoint(current_phase.value, iteration, str(cp_path))

            iteration += 1
            self.state_store.set_state(ws)

        # Final save
        self.state_store.save_checkpoint("final")

        # Determine status
        if current_phase == Phase.COMPLETE:
            status = "success"
        elif ws.current_draft or ws.final_output:
            status = "partial"
        else:
            status = "failed"

        # Write final output
        self._write_final_output(ws, status)

        # Record completion
        self.recorder.record_completion(status, self.lifecycle.get_stats())
        return status

    def _execute_phase(self, phase: Phase, ws: WritingState) -> str:
        """Execute logic for a given phase. Returns transition key."""
        handlers = {
            Phase.INIT: self._phase_init,
            Phase.TASK_ANALYSIS: self._phase_task_analysis,
            Phase.STYLE_SETUP: self._phase_style_setup,
            Phase.PLANNING: self._phase_planning,
            Phase.CHAPTER_PLANNING: self._phase_chapter_planning,
            Phase.DRAFTING: self._phase_drafting,
            Phase.MEMORY_UPDATE: self._phase_memory_update,
            Phase.CONSISTENCY_CHECK: self._phase_consistency_check,
            Phase.SCENARIO_ANALYSIS: self._phase_scenario_analysis,
            Phase.SHORTFORM_DRAFTING: self._phase_shortform_drafting,
            Phase.CRITIQUE: self._phase_critique,
            Phase.REVISION: self._phase_revision,
            Phase.FINALIZATION: self._phase_finalization,
        }
        handler = handlers.get(phase)
        if handler is None:
            return "error"
        return handler(ws)

    # ===== Phase Handlers =====

    def _phase_init(self, ws: WritingState) -> str:
        """Initialize the writing process."""
        return "start"

    def _phase_task_analysis(self, ws: WritingState) -> str:
        """Analyze the task to determine mode, genre, style."""
        result = self._call_tool("analyze_task", ws, prompt=ws.task_prompt)
        if not result.success:
            return "error"

        analysis = result.output
        ws.mode = self.task.mode or analysis.get("mode", "shortform")
        ws.genre = analysis.get("genre", "general fiction")
        ws.style_notes = analysis.get("style_notes", "")

        return "analyzed"

    def _phase_style_setup(self, ws: WritingState) -> str:
        """Set up voice fingerprint and forbidden patterns."""
        # Create voice fingerprint
        result = self._call_tool(
            "create_voice_fingerprint", ws,
            genre=ws.genre, style_notes=ws.style_notes, sample_text="",
        )
        if result.success:
            ws.voice_fingerprint = result.output

        # Generate forbidden patterns
        result = self._call_tool(
            "generate_forbidden_patterns", ws,
            genre=ws.genre, voice_fingerprint=ws.voice_fingerprint[:500],
        )
        if result.success:
            output = result.output
            ws.forbidden_patterns = output.get("forbidden", [])
            ws.pattern_alternatives = output.get("alternatives", {})

        return "longform" if ws.mode == "longform" else "shortform"

    def _phase_planning(self, ws: WritingState) -> str:
        """Create master outline for longform writing."""
        result = self._call_tool(
            "create_master_outline", ws,
            prompt=ws.task_prompt, genre=ws.genre, style_notes=ws.style_notes,
        )
        if not result.success:
            return "error"

        ws.master_outline = result.output

        # Extract structure from outline (estimate chapters)
        # Simple heuristic: count mentions of "chapter" or numbered sections
        outline_lower = ws.master_outline.lower()
        chapter_mentions = outline_lower.count("chapter")
        if chapter_mentions < 3:
            chapter_mentions = max(3, outline_lower.count("act") * 3)
        self._total_chapters_planned = min(chapter_mentions, 12)  # Cap at 12

        return "outline_complete"

    def _phase_chapter_planning(self, ws: WritingState) -> str:
        """Create detailed chapter outline."""
        chapter_num = ws.working_memory.current_chapter + 1

        # Build prior summary from episodic memory
        recent = ws.episodic_memory.get_recent(10)
        prior_summary = " ".join(ep["summary"] for ep in recent) if recent else "Story beginning."

        result = self._call_tool(
            "create_chapter_outline", ws,
            master_outline=ws.master_outline[:3000],
            chapter_num=chapter_num,
            prior_summary=prior_summary[:1000],
            voice_fingerprint=ws.voice_fingerprint[:500],
        )
        if not result.success:
            return "error"

        # Store chapter outline
        if len(ws.chapter_outlines) < chapter_num:
            ws.chapter_outlines.append(result.output)
        else:
            ws.chapter_outlines[chapter_num - 1] = result.output

        ws.working_memory.current_chapter = chapter_num - 1  # 0-indexed
        ws.working_memory.current_scene = 0
        self._scenes_written_this_chapter = 0

        return "chapter_ready"

    def _phase_drafting(self, ws: WritingState) -> str:
        """Write scenes for the current chapter."""
        chapter_idx = ws.working_memory.current_chapter
        scene_idx = ws.working_memory.current_scene

        # Get chapter outline
        if chapter_idx < len(ws.chapter_outlines):
            chapter_outline = ws.chapter_outlines[chapter_idx]
        else:
            return "chapter_complete"

        # Build context for writing
        context_messages = self.context_mgr.build_context(ws)
        context_text = "\n".join(
            m["content"] for m in context_messages if m["role"] == "user"
        )

        # Retrieve relevant distant references
        query = f"chapter {chapter_idx + 1} scene {scene_idx + 1}"
        relevant = self.context_mgr.retrieve_relevant(query, ws)
        if relevant:
            context_text += f"\n\nRelevant references:\n{relevant}"

        # Determine scene outline portion
        scene_outline = self._extract_scene_from_outline(chapter_outline, scene_idx)

        result = self._call_tool(
            "write_scene", ws,
            scene_outline=scene_outline,
            voice_fingerprint=ws.voice_fingerprint[:1000],
            context=context_text[:2000],
            forbidden_patterns=ws.forbidden_patterns[:15],
            target_words=1500,
        )
        if not result.success:
            return "error"

        scene_text = result.output
        ws.drafts.append(scene_text)
        ws.current_draft += "\n\n" + scene_text

        ws.working_memory.current_scene = scene_idx + 1
        self._scenes_written_this_chapter += 1

        # Check if chapter is complete (heuristic: ~3-5 scenes per chapter)
        if self._scenes_written_this_chapter >= 4 or scene_idx >= 3:
            return "chapter_complete"

        return "scene_complete"

    def _phase_memory_update(self, ws: WritingState) -> str:
        """Update memory after writing a scene."""
        if not ws.drafts:
            return "chapter_done"

        latest_scene = ws.drafts[-1]
        chapter = ws.working_memory.current_chapter
        scene = ws.working_memory.current_scene

        result = self._call_tool(
            "update_memory", ws,
            scene_text=latest_scene[:3000],
            chapter=chapter,
            scene=scene,
        )
        if result.success:
            output = result.output
            # Update episodic memory
            ws.episodic_memory.add_episode(
                scene_summary=output.get("summary", ""),
                chapter=chapter,
                scene=scene,
                characters=output.get("character_updates", []),
                key_events=output.get("key_events", []),
            )
            # Update semantic memory
            for char_update in output.get("character_updates", []):
                if isinstance(char_update, dict) and "name" in char_update:
                    char = ws.semantic_memory.add_character(char_update["name"])
                    if char_update.get("emotional_state"):
                        char.emotional_state = char_update["emotional_state"]
                    if char_update.get("location"):
                        char.location = char_update["location"]
                    if char_update.get("new_knowledge"):
                        char.knowledge.append(char_update["new_knowledge"])
                        # Deduplicate
                        char.knowledge = self.deduplicator.compress_knowledge(char.knowledge)

            # Update working memory
            ws.working_memory.scene_context = output.get("summary", "")
            if output.get("new_hooks"):
                ws.working_memory.pending_hooks = output["new_hooks"][-5:]
            if output.get("resolved_hooks"):
                for hook in output["resolved_hooks"]:
                    if hook in ws.semantic_memory.open_loops:
                        ws.semantic_memory.open_loops.remove(hook)
                        ws.semantic_memory.resolved_loops.append(hook)

            # Deduplicate episodic memory
            ws.episodic_memory.recent_scenes = self.deduplicator.deduplicate_episodes(
                ws.episodic_memory.recent_scenes
            )

        # Decide next: more scenes or chapter done
        if self._scenes_written_this_chapter >= 4:
            return "chapter_done"
        return "updated"

    def _phase_consistency_check(self, ws: WritingState) -> str:
        """Check current draft for consistency violations."""
        if not ws.current_draft:
            return "consistent"

        # Build constraint strings
        world_rules = "\n".join(
            f"- [{r.category}] {r.description}"
            for r in ws.semantic_memory.world_rules if r.active
        ) or "No explicit world rules defined."

        char_knowledge = ""
        for name, char in ws.semantic_memory.characters.items():
            if char.knowledge:
                char_knowledge += f"\n{name} knows: {'; '.join(char.knowledge[-5:])}"
        char_knowledge = char_knowledge or "No character knowledge tracked."

        timeline = "\n".join(
            f"- [{e.timestamp_story}] {e.description}"
            for e in ws.semantic_memory.timeline[-10:]
        ) or "No timeline events."

        # Check the most recent draft segment
        check_text = ws.current_draft[-3000:]

        result = self._call_tool(
            "check_consistency", ws,
            text=check_text,
            world_rules=world_rules,
            character_knowledge=char_knowledge,
            timeline=timeline,
        )

        if result.success:
            output = result.output
            violations = output.get("violations", [])
            is_consistent = output.get("is_consistent", True)

            if violations and not is_consistent:
                # Record violations and trigger revision
                ws.revision_briefs.append(
                    "CONSISTENCY FIXES NEEDED:\n" +
                    "\n".join(f"- {v.get('description', str(v))}" for v in violations[:5])
                )
                return "violations_found"

        # Check if more chapters to write
        if (ws.working_memory.current_chapter + 1) < self._total_chapters_planned:
            return "next_chapter"

        return "consistent"

    def _phase_scenario_analysis(self, ws: WritingState) -> str:
        """Analyze short-form scenario."""
        result = self._call_tool("analyze_scenario", ws, prompt=ws.task_prompt)
        if not result.success:
            return "error"

        analysis_text = result.output

        # Parse sections from the analysis
        ws.scenario_analysis = analysis_text

        # Extract emotional map and mental models
        sections = self._split_sections(analysis_text)
        ws.emotional_map = sections.get("emotional_map", analysis_text[:500])
        for key, val in sections.items():
            if "mental" in key.lower() or "model" in key.lower():
                ws.mental_models["all"] = val
                break

        return "analyzed"

    def _phase_shortform_drafting(self, ws: WritingState) -> str:
        """Write short-form / roleplay response."""
        mental_models_text = "\n".join(
            f"{k}: {v}" for k, v in ws.mental_models.items()
        ) if ws.mental_models else ws.scenario_analysis[:500]

        result = self._call_tool(
            "write_shortform", ws,
            scenario_analysis=ws.scenario_analysis[:1500],
            emotional_map=ws.emotional_map[:1000],
            mental_models=mental_models_text[:1000],
            voice_fingerprint=ws.voice_fingerprint[:800],
            forbidden_patterns=ws.forbidden_patterns[:15],
        )
        if not result.success:
            return "error"

        ws.current_draft = result.output
        ws.drafts.append(result.output)
        return "draft_complete"

    def _phase_critique(self, ws: WritingState) -> str:
        """Run adversarial critique on current draft."""
        if not ws.current_draft:
            return "scores_acceptable"

        result = self._call_tool(
            "critique", ws,
            text=ws.current_draft[:4000],
            voice_fingerprint=ws.voice_fingerprint[:500],
            genre=ws.genre,
        )
        if not result.success:
            return "scores_acceptable"  # Skip critique on failure

        output = result.output
        scores = output.get("scores", {})
        ws.critique_scores = scores
        ws.score_history.append(scores)

        # Record metric
        self.recorder.record_metric("critique_scores", scores,
                                    phase="CRITIQUE", iteration=ws.iteration)

        # Check if scores are acceptable
        if scores:
            avg_score = sum(scores.values()) / len(scores)
            self.recorder.record_metric("average_score", avg_score,
                                        phase="CRITIQUE", iteration=ws.iteration)

            if avg_score >= self.task.score_threshold:
                return "scores_acceptable"

            # Check if scores have plateaued (last 3 revisions similar)
            if len(ws.score_history) >= 3:
                recent_avgs = [
                    sum(s.values()) / len(s) for s in ws.score_history[-3:]
                    if s
                ]
                if recent_avgs and max(recent_avgs) - min(recent_avgs) < 0.05:
                    return "scores_acceptable"  # Plateaued

        # Check revision limit
        if ws.revision_count >= self.task.max_revisions:
            return "max_revisions_reached"

        # Build revision brief from critique
        priorities = output.get("revision_priorities", [])
        weaknesses = output.get("weaknesses", [])
        brief_parts = ["REVISION PRIORITIES:"]
        for p in priorities[:5]:
            brief_parts.append(f"- {p}")
        if weaknesses:
            brief_parts.append("\nWEAKNESSES TO ADDRESS:")
            for w in weaknesses[:3]:
                brief_parts.append(f"- {w}")
        ws.revision_briefs.append("\n".join(brief_parts))

        return "needs_revision"

    def _phase_revision(self, ws: WritingState) -> str:
        """Revise draft based on critique."""
        if not ws.revision_briefs:
            return "revised"

        revision_brief = ws.revision_briefs[-1]
        original_length = len(ws.current_draft)

        result = self._call_tool(
            "revise", ws,
            text=ws.current_draft[:6000],
            revision_brief=revision_brief[:1500],
            voice_fingerprint=ws.voice_fingerprint[:800],
            forbidden_patterns=ws.forbidden_patterns[:15],
        )
        if not result.success:
            self._revision_retries += 1
            if self._revision_retries >= self._max_revision_retries:
                return "max_retries"
            return "length_violation"

        revised_text = result.output

        # Length protection: revision must be >= 80% of original
        if len(revised_text) < original_length * self.task.length_protection_ratio:
            self._revision_retries += 1
            if self._revision_retries >= self._max_revision_retries:
                # Keep original if revision keeps shrinking
                return "max_retries"
            # Add instruction to maintain length
            ws.revision_briefs.append(
                revision_brief + "\n\nCRITICAL: Your revision MUST be at least "
                f"{int(self.task.length_protection_ratio * 100)}% the length of "
                "the original. Do NOT cut content — improve it in place."
            )
            return "length_violation"

        ws.current_draft = revised_text
        ws.drafts.append(revised_text)
        ws.revision_count += 1
        self._revision_retries = 0

        return "revised"

    def _phase_finalization(self, ws: WritingState) -> str:
        """Finalize the output."""
        ws.final_output = ws.current_draft

        # Run final AI pattern detection
        if ws.final_output:
            result = self._call_tool(
                "detect_ai_patterns", ws,
                text=ws.final_output[:3000],
            )
            if result.success:
                score = result.output.get("originality_score", 0)
                self.recorder.record_metric("final_originality_score", score,
                                            phase="FINALIZATION", iteration=ws.iteration)

        return "done"

    # ===== Helpers =====

    def _call_tool(self, tool_name: str, ws: WritingState, **kwargs: Any) -> ToolResult:
        """Call a tool with lifecycle hooks."""
        self.lifecycle.pre_tool_call(tool_name, kwargs, ws.current_phase, ws.iteration)

        start = time.time()
        result = self.tools.dispatch(tool_name, **kwargs)
        duration_ms = (time.time() - start) * 1000

        self.lifecycle.post_tool_call(
            tool_name=tool_name,
            input_data=kwargs,
            output_data=result.output,
            phase=ws.current_phase,
            iteration=ws.iteration,
            duration_ms=duration_ms,
            token_usage=result.token_usage,
        )
        return result

    def _extract_scene_from_outline(self, chapter_outline: str, scene_idx: int) -> str:
        """Extract a specific scene's outline from the chapter outline."""
        lines = chapter_outline.split("\n")
        scene_marker = f"scene_{scene_idx + 1}"
        alt_markers = [f"Scene {scene_idx + 1}", f"SCENE {scene_idx + 1}",
                       f"SCENE_ID: {scene_idx + 1}", f"scene {scene_idx + 1}"]

        # Try to find scene boundaries
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            if any(m.lower() in line_lower for m in [scene_marker] + alt_markers):
                start_idx = i
            elif start_idx is not None and any(
                m.lower() in line_lower
                for m in [f"scene_{scene_idx + 2}", f"Scene {scene_idx + 2}",
                          f"SCENE {scene_idx + 2}", f"SCENE_ID: {scene_idx + 2}"]
            ):
                end_idx = i
                break

        if start_idx is not None:
            end_idx = end_idx or len(lines)
            return "\n".join(lines[start_idx:end_idx])

        # Fallback: divide outline evenly
        total_scenes = 4
        chunk_size = max(1, len(lines) // total_scenes)
        start = scene_idx * chunk_size
        end = start + chunk_size
        return "\n".join(lines[start:end]) if start < len(lines) else chapter_outline[:500]

    def _split_sections(self, text: str) -> dict[str, str]:
        """Split analysis text into labeled sections."""
        sections: dict[str, str] = {}
        current_label = ""
        current_content: list[str] = []

        for line in text.split("\n"):
            stripped = line.strip()
            # Detect section headers (numbered or uppercase)
            if (stripped and (stripped[0].isdigit() and "." in stripped[:3]) or
                    stripped.isupper() or
                    stripped.startswith("##") or
                    stripped.endswith(":")):
                if current_label:
                    sections[current_label] = "\n".join(current_content)
                current_label = stripped.lower().rstrip(":").strip("# 0123456789.")
                current_content = []
            else:
                current_content.append(line)

        if current_label:
            sections[current_label] = "\n".join(current_content)

        return sections

    def _write_final_output(self, ws: WritingState, status: str) -> None:
        """Write final output files."""
        # Write the creative output
        output_file = self.output_dir / "output.txt"
        content = ws.final_output or ws.current_draft or "(no output generated)"
        output_file.write_text(content, encoding="utf-8")

        # Write outline if available
        if ws.master_outline:
            outline_file = self.output_dir / "outline.txt"
            outline_file.write_text(ws.master_outline, encoding="utf-8")

        # Write stats
        stats = {
            "status": status,
            "mode": ws.mode,
            "genre": ws.genre,
            "iterations": ws.iteration,
            "revisions": ws.revision_count,
            "drafts_count": len(ws.drafts),
            "final_length_chars": len(ws.final_output),
            "final_length_words": len(ws.final_output.split()),
            "score_history": ws.score_history,
            "lifecycle_stats": self.lifecycle.get_stats(),
        }
        stats_file = self.output_dir / "stats.json"
        import json
        stats_file.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
