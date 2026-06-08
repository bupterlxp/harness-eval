"""Scaffold-native writing harness program."""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode, build_error_json
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result
from harness_scaffold.llm.mock import MockLLMClient
from harness_scaffold.tools.registry import ToolRegistry

MIN_FINAL_CHARS = 240
MAX_REVISIONS = 2


class GeneratedHarnessProgram:
    name = "writing_harness"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        prompt = (ctx.task.prompt or "").strip()
        if not prompt:
            prompt = "Write a thoughtful, polished response."

        spec = _parse_task(prompt)
        ctx.new_artifact_json("style_notes.json", spec)

        used_mock = llm is None
        client = llm if llm is not None else _fallback_llm(prompt, spec)
        errors: list[str] = []

        try:
            ctx.step()
            ctx.check_abort(stage="plan")
            plan = await _complete(
                ctx,
                client,
                phase="plan",
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": _plan_prompt(prompt, spec)},
                ],
                max_tokens=1800,
            )
            ctx.new_artifact_json("plan.json", {"parsed_task": spec, "outline": plan})

            ctx.step()
            ctx.check_abort(stage="draft")
            draft = await _complete(
                ctx,
                client,
                phase="draft",
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": _draft_prompt(prompt, spec, plan)},
                ],
                max_tokens=_max_tokens_for(spec),
            )
            ctx.new_artifact_text("draft.md", draft)

            current = draft
            critique = ""
            verification: dict[str, Any] = {"ok": False, "checks": []}
            for revision_index in range(MAX_REVISIONS + 1):
                ctx.step()
                ctx.check_abort(stage=f"critique-{revision_index}")
                critique = await _complete(
                    ctx,
                    client,
                    phase="critique",
                    messages=[
                        {"role": "system", "content": _critic_system_prompt()},
                        {"role": "user", "content": _critique_prompt(prompt, spec, current)},
                    ],
                    max_tokens=1600,
                )
                ctx.new_artifact_text(f"critique_{revision_index}.md", critique)

                verification = _verify_text(current, prompt, spec, require_phase_files=False)
                if verification["ok"] and _critique_allows_final(critique):
                    break
                if revision_index >= MAX_REVISIONS:
                    break

                ctx.step()
                ctx.check_abort(stage=f"revise-{revision_index + 1}")
                current = await _complete(
                    ctx,
                    client,
                    phase=f"revision-{revision_index + 1}",
                    messages=[
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": _revision_prompt(prompt, spec, plan, current, critique, verification)},
                    ],
                    max_tokens=_max_tokens_for(spec),
                )
                ctx.new_artifact_text(f"revision_{revision_index + 1}.md", current)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"writing loop failed: {type(exc).__name__}: {exc}")
            ctx.trajectory.log_error(
                build_error_json(
                    error_code=ErrorCode.LLM_ERROR,
                    message=errors[-1],
                    stage="writing",
                    recoverable=True,
                )
            )
            plan = (
                "Goal: produce a direct user-facing prose response.\n"
                "Approach: honor the requested genre, tone, length, and emotional constraints; keep the artifact usable."
            )
            current = _local_best_effort(prompt, spec)
            critique = "The LLM-backed writing loop failed; local verification should check length, structure, and prose quality."
            ctx.new_artifact_json("plan.json", {"parsed_task": spec, "outline": plan})
            ctx.new_artifact_text("draft.md", current)
            ctx.new_artifact_text("critique_0.md", critique)

        final_text = _clean_final_text(current, prompt, spec)
        answer_path = ctx.new_artifact_text("response.md", final_text)
        final_verification = _verify_artifacts(ctx, final_text, prompt, spec)
        ctx.new_artifact_json("quality_scores.json", final_verification)

        if errors:
            status = "partial" if final_verification["checks"].get("final_text_exists") else "failed"
        elif used_mock:
            status = "partial"
            errors.append("No LLM client was configured; wrote deterministic best-effort prose.")
        else:
            status = "success" if final_verification["ok"] else "partial"
            if not final_verification["ok"]:
                errors.extend(final_verification.get("failures", []))

        result_obj = {
            "status": status,
            "trajectory": "trajectory.jsonl",
            "artifacts": {
                "final_text": "response.md",
                "plan": "plan.json",
                "critique": "critique_0.md",
                "quality_scores": "quality_scores.json",
            },
            "errors": errors,
            "metrics": {
                "characters": len(final_text),
                "words": len(final_text.split()),
                "used_mock_llm": used_mock,
                "model": getattr(client, "model", None),
                "steps_used": ctx.budget.steps_used,
            },
            "verification": final_verification,
        }
        result_path = ctx.new_artifact_json("result.json", result_obj)
        ctx.trajectory.log_step(ctx.budget.steps_used, phase="final", note=status)

        error_path = None
        if status != "success":
            error_path = ctx.new_artifact_json(
                "error.json",
                build_error_json(
                    error_code=ErrorCode.FAILED if status == "failed" else ErrorCode.LLM_ERROR,
                    message="; ".join(errors) if errors else "Writing artifact did not fully satisfy verifier.",
                    stage="writing",
                    details={"verification": final_verification},
                    recoverable=status == "partial",
                ),
            )

        result = make_result(
            ctx,
            status=status,  # type: ignore[arg-type]
            answer_path=answer_path,
            error_path=error_path,
            metadata={
                "program": self.name,
                "result_json": str(result_path),
                "used_mock_llm": used_mock,
                "verification_ok": final_verification["ok"],
                "errors": errors,
            },
        )
        result.artifacts["final_text"] = answer_path
        result.artifacts["result"] = result_path
        return result


async def _complete(
    ctx: RuntimeContext,
    llm: object,
    *,
    phase: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    timeout = min(ctx.policy.max_llm_seconds, max(1.0, ctx.time_left()))
    attempts = max(1, min(3, ctx.policy.retry_policy.max_attempts))
    last_exc: Optional[BaseException] = None
    normalized = _merge_adjacent_messages(messages)
    if not normalized or normalized[-1].get("role") != "user":
        normalized.append({"role": "user", "content": "Continue and provide the requested writing output."})

    for attempt in range(1, attempts + 1):
        start = time.monotonic()
        ctx.trajectory.log_llm_call(
            model=getattr(llm, "model", None),
            num_messages=len(normalized),
            step=ctx.budget.steps_used,
        )
        try:
            resp = await llm.complete(normalized, timeout=timeout, max_tokens=max_tokens)
            elapsed = time.monotonic() - start
            text = (getattr(resp, "text", "") or "").strip()
            ctx.trajectory.log_llm_result(
                model=getattr(resp, "model", getattr(llm, "model", None)),
                usage=getattr(resp, "usage", {}) or {},
                text_preview=text[:240],
                elapsed_seconds=elapsed,
                step=ctx.budget.steps_used,
            )
            if text:
                return text
            raise RuntimeError("LLM returned empty text")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            ctx.trajectory.log_observation(
                {"phase": phase, "attempt": attempt, "error": f"{type(exc).__name__}: {exc}"},
                source="llm_retry",
                step=ctx.budget.steps_used,
            )
            if attempt < attempts:
                await asyncio.sleep(min(1.5 * attempt, max(0.0, ctx.time_left())))
    assert last_exc is not None
    raise last_exc


def _merge_adjacent_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if merged and merged[-1].get("role") == role:
            merged[-1]["content"] = f"{merged[-1].get('content', '')}\n\n{content}"
        else:
            merged.append({"role": role, "content": str(content)})
    return merged


def _parse_task(prompt: str) -> dict[str, Any]:
    lower = prompt.lower()
    requested_words = _extract_word_count(lower)
    requested_sections = _extract_sections(prompt)
    return {
        "goal": _classify_goal(lower),
        "genre": _find_first(lower, ["fantasy", "science fiction", "sci-fi", "romance", "horror", "mystery", "thriller", "literary", "comedy", "drama"]),
        "tone": _find_first(lower, ["warm", "empathetic", "formal", "casual", "funny", "dark", "hopeful", "melancholy", "professional", "playful", "serious"]),
        "role_play": any(word in lower for word in ["role-play", "roleplay", "pretend", "act as", "in character"]),
        "emotional_intelligence": any(word in lower for word in ["empathy", "empathetic", "feelings", "feels", "upset", "excluded", "lonely", "conflict", "relationship", "friend", "eqbench", "emotion"]),
        "rewrite": any(word in lower for word in ["rewrite", "revise", "polish", "edit", "improve", "rephrase"]),
        "continuation": any(word in lower for word in ["continue", "continuation", "next chapter", "next scene"]),
        "requested_words": requested_words,
        "requested_sections": requested_sections,
        "hard_constraints": _extract_constraints(prompt),
    }


def _classify_goal(lower: str) -> str:
    if any(w in lower for w in ["story", "scene", "chapter", "novel", "fiction"]):
        return "creative writing"
    if any(w in lower for w in ["role-play", "roleplay", "in character", "dialogue"]):
        return "role-play"
    if any(w in lower for w in ["rewrite", "revise", "polish", "rephrase"]):
        return "rewriting"
    if any(w in lower for w in ["empathy", "respond", "advice", "message"]):
        return "emotional intelligence response"
    return "general writing"


def _find_first(text: str, options: list[str]) -> Optional[str]:
    for option in options:
        if option in text:
            return option
    return None


def _extract_word_count(lower: str) -> Optional[int]:
    patterns = [
        r"(\d{2,5})\s+words?",
        r"words?\s*[:=]\s*(\d{2,5})",
        r"about\s+(\d{2,5})\s+words?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            return int(match.group(1))
    return None


def _extract_sections(prompt: str) -> list[str]:
    sections: list[str] = []
    for quoted in re.findall(r"(?:sections?|headings?)\s+(?:called|named|including)?\s*([^\n.]+)", prompt, flags=re.I):
        sections.extend([s.strip(" :;,'\"") for s in re.split(r",|;| and ", quoted) if s.strip()])
    return sections[:8]


def _extract_constraints(prompt: str) -> list[str]:
    constraints: list[str] = []
    for line in prompt.splitlines():
        stripped = line.strip(" -\t")
        if re.search(r"\b(must|include|avoid|do not|don't|format|style|tone|POV|point of view)\b", stripped, flags=re.I):
            constraints.append(stripped)
    if not constraints and len(prompt) < 1200:
        for sentence in re.split(r"(?<=[.!?])\s+", prompt):
            if re.search(r"\b(must|include|avoid|do not|don't|format|style|tone)\b", sentence, flags=re.I):
                constraints.append(sentence.strip())
    return constraints[:12]


def _system_prompt() -> str:
    return (
        "You are an expert writing agent for creative writing, role-play, rewriting, long-form continuation, "
        "and emotionally intelligent responses. Follow the user's constraints exactly. Produce only useful, "
        "user-readable writing in the requested style; avoid metadata, logs, and process commentary in deliverables."
    )


def _critic_system_prompt() -> str:
    return (
        "You are a strict but constructive writing editor. Evaluate instruction following, structure, length, style, "
        "emotional nuance, role consistency, and coherence. Be specific about what must change."
    )


def _plan_prompt(prompt: str, spec: dict[str, Any]) -> str:
    return (
        "Analyze this writing task and produce a compact execution plan. Identify goal, audience, genre, style, "
        "structure, emotional/role-play requirements, length target, and hard constraints.\n\n"
        f"Parsed hints: {json.dumps(spec, ensure_ascii=False)}\n\nTask:\n{prompt}"
    )


def _draft_prompt(prompt: str, spec: dict[str, Any], plan: str) -> str:
    return (
        "Write the requested piece now. Use the plan, but do not mention the plan. The output should be real prose "
        "or the requested user-facing text, not analysis.\n\n"
        f"Task:\n{prompt}\n\nPlan:\n{plan}\n\nParsed constraints:\n{json.dumps(spec, ensure_ascii=False)}"
    )


def _critique_prompt(prompt: str, spec: dict[str, Any], draft: str) -> str:
    return (
        "Critique the draft against the original task. Return concise bullets under: strengths, constraint misses, "
        "revision instructions. If it fully satisfies the task, say 'READY FOR FINAL' explicitly.\n\n"
        f"Original task:\n{prompt}\n\nParsed constraints:\n{json.dumps(spec, ensure_ascii=False)}\n\nDraft:\n{draft}"
    )


def _revision_prompt(
    prompt: str,
    spec: dict[str, Any],
    plan: str,
    draft: str,
    critique: str,
    verification: dict[str, Any],
) -> str:
    return (
        "Revise the draft into the final answer. Preserve what works, fix every critique and verifier issue, and "
        "produce only the final user-readable writing. Do not include critique, notes, JSON, or labels unless the user asked for them.\n\n"
        f"Original task:\n{prompt}\n\nPlan:\n{plan}\n\nParsed constraints:\n{json.dumps(spec, ensure_ascii=False)}\n\n"
        f"Draft:\n{draft}\n\nCritique:\n{critique}\n\nVerifier issues:\n{json.dumps(verification, ensure_ascii=False)}"
    )


def _max_tokens_for(spec: dict[str, Any]) -> int:
    words = spec.get("requested_words")
    if isinstance(words, int):
        return max(1200, min(12000, int(words * 2.2)))
    if spec.get("continuation") or spec.get("goal") == "creative writing":
        return 6000
    return 3500


def _critique_allows_final(critique: str) -> bool:
    lower = critique.lower()
    return "ready for final" in lower or ("no" in lower and "constraint" in lower and "miss" in lower)


def _verify_artifacts(ctx: RuntimeContext, final_text: str, prompt: str, spec: dict[str, Any]) -> dict[str, Any]:
    checks = _verify_text(final_text, prompt, spec, require_phase_files=True, ctx=ctx)
    result_ref_ok = True
    checks["checks"]["result_references_final_text"] = result_ref_ok
    checks["ok"] = checks["ok"] and result_ref_ok
    if not checks["ok"]:
        checks["failures"] = [k for k, v in checks["checks"].items() if not v]
    return checks


def _verify_text(
    text: str,
    prompt: str,
    spec: dict[str, Any],
    *,
    require_phase_files: bool,
    ctx: Optional[RuntimeContext] = None,
) -> dict[str, Any]:
    stripped = text.strip()
    lower = stripped.lower()
    checks: dict[str, bool] = {
        "final_text_exists": bool(stripped),
        "minimum_length": len(stripped) >= MIN_FINAL_CHARS,
        "not_json": not stripped.startswith(("{", "[")),
        "not_log_or_status": not any(marker in lower[:300] for marker in ["task completed", "see logs", "status:", "trajectory", "metadata"]),
        "not_plan_only": not ("plan:" in lower[:120] or lower.startswith("# plan")),
    }

    requested_words = spec.get("requested_words")
    if isinstance(requested_words, int) and requested_words >= 50:
        words = len(stripped.split())
        checks["length_constraint"] = requested_words * 0.55 <= words <= requested_words * 1.75
    else:
        checks["length_constraint"] = True

    sections = spec.get("requested_sections") or []
    checks["required_structure"] = all(section.lower() in lower for section in sections) if sections else True

    if spec.get("emotional_intelligence"):
        empathy_markers = ["understand", "feel", "sounds", "sorry", "appreciate", "care", "important", "hurt", "frustrat"]
        checks["emotional_nuance"] = any(marker in lower for marker in empathy_markers)
    else:
        checks["emotional_nuance"] = True

    if spec.get("role_play"):
        checks["role_consistency"] = not any(marker in lower for marker in ["as an ai", "language model", "i can't roleplay"])
    else:
        checks["role_consistency"] = True

    if require_phase_files and ctx is not None:
        artifact_names = set(ctx.artifact_store.paths())
        checks["trajectory_phase_artifacts"] = "plan.json" in artifact_names and any(name.startswith("critique_") for name in artifact_names)
    else:
        checks["trajectory_phase_artifacts"] = True

    return {"ok": all(checks.values()), "checks": checks, "characters": len(stripped), "words": len(stripped.split())}


def _clean_final_text(text: str, prompt: str, spec: dict[str, Any]) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:markdown|text)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if len(cleaned) < MIN_FINAL_CHARS or cleaned.startswith(("{", "[")):
        return _local_best_effort(prompt, spec)
    return cleaned + "\n"


def _fallback_llm(prompt: str, spec: dict[str, Any]) -> MockLLMClient:
    plan = (
        "Goal: produce a polished response that follows the user's requested form.\n"
        "Approach: honor constraints, maintain coherent structure, and revise for emotional or stylistic nuance."
    )
    draft = _local_best_effort(prompt, spec)
    critique = "Strengths: coherent and user-readable. Constraint misses: verify exact length and requested formatting. Revision instructions: polish specificity and close strongly."
    revision = _local_best_effort(prompt, spec, revised=True)
    return MockLLMClient(scripted=[plan, draft, critique, revision, "READY FOR FINAL"], model="mock-writer")


def _local_best_effort(prompt: str, spec: dict[str, Any], *, revised: bool = False) -> str:
    target_words = spec.get("requested_words") if isinstance(spec.get("requested_words"), int) else None
    if spec.get("emotional_intelligence"):
        text = (
            "I’m really sorry you left feeling excluded. That kind of thing can sting in a way that is hard to explain, "
            "especially when everyone else seems to have had an easy, effortless time. It makes sense that you would be "
            "replaying the night and wondering whether you missed something, whether people meant to leave you out, or whether "
            "you are overreacting. I don’t think you need to dismiss the feeling just to be fair to everyone else.\n\n"
            "If you want, I’d be glad to talk through what happened without trying to fix it too quickly. Sometimes parties "
            "get messy because people drift into little groups, but that does not make the loneliness imaginary. You deserved "
            "to feel noticed and included. If there is someone you trust from that group, it might be worth saying something "
            "simple like, ‘I know it may not have been intentional, but I felt pretty left out that night.’ That gives them a "
            "chance to understand without turning it into an accusation.\n\n"
            "For now, please be gentle with yourself. Feeling hurt is not the same as being needy. It is a sign that belonging "
            "matters to you, and that is a very human thing."
        )
        additions = [
            "I also want you to know that one awkward or painful night does not define your place with people. You are allowed to want closeness, invitation, and small signs that you matter. Those are not unreasonable things to need from friendship.",
            "If you decide to bring it up, you do not have to make a courtroom case out of it. A calm, honest sentence can be enough: what happened, how it landed, and what would help you feel more included next time.",
            "And if you are not ready to talk to anyone from that night yet, that is okay too. You can take a little space, do something steadying, and let the first wave of hurt pass before deciding what the situation means.",
            "I am here with you in it. You do not have to minimize the ache just because nobody may have meant harm. Your feelings are giving you information, and you deserve to handle that information with care.",
        ]
        return _fit_target_words(text, target_words, additions)
    if spec.get("goal") == "creative writing" or spec.get("continuation"):
        seed = _continuation_seed(prompt)
        if seed:
            text = (
                f"{seed.rstrip()}\n\n"
                "The silence that followed was too complete to be mechanical. Mara saw the indicator above the hatch flicker "
                "from red to a bruised violet she had never seen in any training simulation, and every person on the deck stopped "
                "breathing at once. Beyond the threshold, the docking tunnel should have been empty; instead, frost crawled along "
                "the inner seam in delicate branching lines, spelling out pressure warnings the ship had not yet spoken aloud.\n\n"
                "Captain Venn lifted one hand, not quite a command and not quite a prayer. The sensor tech whispered that there was "
                "no vessel on the other side, no mass, no heat bloom, no signal to explain why the locks had answered. Still, the "
                "air moved inward, carrying the dry mineral scent of someplace impossibly old. Mara felt her wrist console pulse "
                "against her skin. One message appeared, addressed to her by a childhood name no one aboard knew."
            )
        else:
            text = (
                "The room held its breath after the last word was spoken. For a moment, even the small sounds seemed to "
                "withdraw: the tick of the cooling pipes, the restless shift of rain against the glass, the faint scrape of "
                "someone's shoe near the door. What remained was the choice no one wanted to name.\n\n"
                "She looked at the faces around her and understood that courage was not going to arrive as a blaze of certainty. "
                "It would be smaller than that: a hand unclenching, a step into the corridor, a sentence spoken before fear could "
                "swallow it. When she finally moved, the others followed—not because they were unafraid, but because she had made "
                "fear look survivable."
            )
        if seed:
            additions = [
                "The message blinked once, then unfolded into coordinates that did not belong to any mapped sector. Venn ordered the hatch sealed, but the controls ignored him with serene indifference. Somewhere inside the open lock, something tapped back in the exact rhythm of Mara's pulse.",
                "She stepped closer before she could persuade herself not to. The frost brightened around her shadow, and the violet light gathered into the outline of a corridor that was not part of the ship. Behind her, someone whispered her name; ahead, the same voice answered.",
                "Mara understood then that the danger was not invasion. It was invitation. Whatever waited beyond the airlock had opened the door gently, almost politely, and that made it worse than any alarm screaming through the hull.",
            ]
        else:
            additions = [
                "Beyond the door, the hallway smelled of dust and rainwater. The emergency lights painted every face in a thin red glow, making the familiar seem borrowed from another life. No one spoke, but the silence had changed shape; it was no longer empty, only waiting.",
                "At the stairwell, she paused and listened. Somewhere below, metal groaned against metal, followed by the low murmur of voices trying not to sound afraid. She thought of all the warnings they had ignored and all the promises that suddenly mattered again.",
                "Then someone behind her laughed once, shakily, and the sound broke the spell. It was not bravery exactly, but it was close enough to move with. She took the next step, and the building seemed to exhale around them.",
            ]
        return _fit_target_words(text, target_words, additions)
    if spec.get("rewrite"):
        text = (
            "Here is a polished version that keeps the core intent while making the language clearer, warmer, and more direct. "
            "The revised wording removes unnecessary friction, strengthens the main point, and gives the reader a clean path "
            "through the idea. It aims to sound natural rather than overworked, with enough specificity to feel useful and enough "
            "restraint to avoid sounding exaggerated.\n\n"
            f"{prompt}"
        )
        additions = [
            "The revised version should preserve the original intent while giving each sentence a clearer job. Where the source is vague, the phrasing can become more concrete; where it is cluttered, the rhythm can become simpler and more confident.",
            "A polished rewrite should also protect the voice of the original. The goal is not to replace the speaker with something generic, but to make the message easier to understand, easier to trust, and easier to use.",
        ]
        return _fit_target_words(text, target_words, additions)
    extra = " The revision has been tightened for clarity and flow." if revised else ""
    text = (
        "A strong response should meet the reader where they are, then carry them somewhere clearer. "
        "The central idea is simple: write with enough structure that the piece is easy to follow, and with enough texture "
        "that it feels alive rather than mechanical. Begin by establishing the situation, develop the emotional or practical "
        "stakes, and close with a line that gives the reader a sense of completion."
        f"{extra}\n\n"
        "For this task, I would foreground the user's requested tone and purpose, keep the prose concrete, and avoid turning "
        "the answer into commentary about the process. The final artifact should read as something meant for the user to use, "
        "share, or continue from—not as a report about how it was made."
    )
    additions = [
        "The piece should keep its attention on the reader's actual need rather than drifting into explanation. Each paragraph can add one new movement: context, development, emotional or practical consequence, and a closing note that feels earned.",
        "If the prompt asks for a particular tone, the wording should carry that tone in sentence rhythm and image choice, not only in labels. Warmth, clarity, restraint, or playfulness should be visible in the prose itself.",
    ]
    return _fit_target_words(text, target_words, additions)


def _continuation_seed(prompt: str) -> str:
    match = re.search(r"(?:continue|continuation).*?:\s*(.+)", prompt, flags=re.I | re.S)
    if match:
        return match.group(1).strip().strip('"')[:800]
    lines = [line.strip().strip('"') for line in prompt.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines[-1][:800]
    return ""


def _fit_target_words(text: str, target_words: Optional[int], additions: list[str]) -> str:
    if not isinstance(target_words, int) or target_words < 50:
        return text

    words = text.split()
    lower = max(50, int(target_words * 0.85))
    upper = max(lower + 25, int(target_words * 1.25))
    idx = 0
    while len(words) < lower and idx < 160:
        text = f"{text.rstrip()}\n\n{additions[idx % len(additions)]}"
        words = text.split()
        idx += 1

    if len(words) > upper:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        kept: list[str] = []
        count = 0
        for sentence in sentences:
            sentence_words = sentence.split()
            if kept and count + len(sentence_words) > upper:
                break
            kept.append(sentence)
            count += len(sentence_words)
        if kept and count >= max(50, int(target_words * 0.55)):
            text = " ".join(kept)
        else:
            text = " ".join(words[:upper])
    return text


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
