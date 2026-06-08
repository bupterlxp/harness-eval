"""Scaffold-native generated harness program for writing tasks.

Implements a multi-phase writing pipeline:
  1. Parse the task prompt into a structured plan
  2. Build an outline (via LLM if available)
  3. Draft the writing
  4. Critique the draft against task constraints
  5. Revise (up to MAX_REVISIONS times)
  6. Verify final artifacts
  7. Write result.json and trajectory

Uses harness_scaffold runtime for execution, LLM calls, artifact writing,
and trajectory logging.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result
from harness_scaffold.llm.client import LLMClient, LLMResponse
from harness_scaffold.llm.mock import MockLLMClient
from harness_scaffold.llm.openai_like import OpenAILikeClient
from harness_scaffold.tools.registry import ToolRegistry

from planner import WritingPlan, plan_from_prompt, build_outline_with_llm
from critic import critique_draft, critique_with_llm
from verifier import verify_artifacts

MAX_REVISIONS = 2


class DirectURLClient(LLMClient):
    """LLM client for endpoints where the base URL is the completions endpoint.

    Some providers (e.g. bytedance) embed auth in the URL itself and don't use
    the standard /v1/chat/completions path. This client POSTs directly to the
    provided URL without appending any path.
    """

    name = "direct_url"

    def __init__(self, *, url: str, model: str, api_key: str = "", default_timeout: float = 120.0) -> None:
        super().__init__()
        self.model = model
        self._url = url
        self._api_key = api_key
        self.default_timeout = default_timeout

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        **opts: Any,
    ) -> LLMResponse:
        from harness_scaffold.core.dependency import require
        requests = require("requests", extra="http", purpose="Direct URL LLM client")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        for k in ("temperature", "max_tokens", "top_p", "stop", "tool_choice"):
            if k in opts:
                payload[k] = opts[k]

        # Default to higher max_tokens for writing tasks if not specified.
        if "max_tokens" not in payload:
            payload["max_tokens"] = 4096

        to = float(timeout if timeout is not None else self.default_timeout)
        try:
            resp = requests.post(self._url, headers=headers, json=payload, timeout=to)
        except Exception as exc:
            from harness_scaffold.core.errors import ProviderError
            raise ProviderError(
                f"Direct URL request failed: {type(exc).__name__}: {exc}",
                stage="llm",
                details={"url": self._url[:100], "exception_type": type(exc).__name__},
                recoverable=True,
            ) from exc

        if resp.status_code >= 400:
            from harness_scaffold.core.errors import ProviderError
            raise ProviderError(
                f"Direct URL HTTP {resp.status_code}",
                stage="llm",
                details={"status_code": resp.status_code, "body_preview": resp.text[:500]},
                recoverable=resp.status_code in (429, 500, 502, 503, 504),
            )

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        text = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        usage = data.get("usage", {}) or {}
        self._account(usage)
        return LLMResponse(
            text=text, tool_calls=tool_calls, usage=usage, raw=data,
            model=data.get("model", self.model),
        )


def _build_llm_from_env() -> Optional[LLMClient]:
    """Build an LLM client from environment variables, or return None."""
    model = os.environ.get("MODEL_NAME")
    if not model:
        return None

    base_url = os.environ.get("BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")

    if not base_url:
        return None

    # Detect if the URL is a direct endpoint (has query params or non-standard path).
    is_direct = ("?" in base_url) or ("/v2/" in base_url)

    if is_direct:
        return DirectURLClient(url=base_url, model=model, api_key=api_key or "")
    else:
        kwargs: dict[str, Any] = {"model": model, "base_url": base_url}
        if api_key:
            kwargs["api_key"] = api_key
        return OpenAILikeClient(**kwargs)


FINAL_ARTIFACT_NAME = "response.md"


def _fallback_llm() -> MockLLMClient:
    """Deterministic mock for offline / no-provider runs."""
    return MockLLMClient(
        scripted=[
            # outline
            "- Introduction setting the scene\n- Main conflict or theme development\n- Climax or turning point\n- Resolution and reflection",
            # draft
            (
                "The morning light filtered through the curtains, casting long shadows across the room. "
                "Sarah stood by the window, her coffee growing cold in her hands as she watched the "
                "neighborhood slowly come to life outside.\n\n"
                "She had been thinking about this moment for weeks. The letter sat on the kitchen table, "
                "its seal still unbroken. She knew what it would say, or at least she thought she did. "
                "But knowing and accepting are two very different things.\n\n"
                "The phone rang, breaking the silence. She let it ring. Whatever news awaited her in "
                "that letter, she needed to face it on her own terms first. Taking a deep breath, she "
                "walked to the table and picked it up.\n\n"
                "Inside, the words were exactly as she had feared, yet somehow softer than she imagined. "
                "The world didn't end. The sky didn't fall. Instead, there was simply a new beginning "
                "waiting for her on the other side of acceptance.\n\n"
                "She smiled, set down the letter, and finally took a sip of her cold coffee. It tasted "
                "like the future."
            ),
            # critique response (JSON)
            '{"score": 0.65, "issues": ["Could use more sensory detail", "Emotional arc could be stronger"], "strengths": ["Clear narrative voice", "Good pacing"], "revision_focus": ["Add more vivid sensory descriptions", "Deepen the emotional conflict", "Strengthen the ending"]}',
            # revision 1
            (
                "The amber morning light spilled through the gauze curtains, painting the worn "
                "floorboards in streaks of gold and shadow. Sarah pressed her forehead against the cool "
                "glass, her coffee cooling between her palms, its bitter scent mixing with the first "
                "rain of autumn. Below, Mrs. Chen was sweeping her front steps; the rhythmic swish of "
                "the broom was the only sound in the stillness.\n\n"
                "She had been rehearsing this moment for weeks, turning it over in her mind like a stone "
                "worn smooth by worry. The letter lay on the kitchen table, its crisp white envelope "
                "still sealed, the handwriting on the front achingly familiar. She knew what it would "
                "say—or she thought she did. But knowing something in your mind and accepting it in "
                "your chest are two entirely different landscapes.\n\n"
                "The phone rang, its shrill call cutting through the quiet like a blade. She let it "
                "ring. She let it ring again. Whatever truth waited inside that envelope, she needed to "
                "meet it standing up, with her own two feet on her own floor, in her own time.\n\n"
                "She crossed the room. Her fingers trembled as she broke the seal, the paper crinkling "
                "like dry leaves. The words were exactly as she had feared, yet somehow lighter than "
                "she had imagined—as if the truth, once set free on paper, had lost some of its weight. "
                "The world didn't end. The sky didn't crack open. Instead, there was simply this: a new "
                "beginning, quiet and unassuming, waiting on the other side of acceptance like a door "
                "left slightly ajar.\n\n"
                "A laugh escaped her—half sob, half relief. She set the letter down and raised the cup "
                "to her lips. The coffee was cold now, and bitter, and somehow it tasted exactly like "
                "the future: uncertain, but hers."
            ),
        ],
        model="mock-writer",
    )


async def _complete(
    ctx: RuntimeContext,
    llm: Any,
    messages: list[dict[str, Any]],
    *,
    label: str = "llm_call",
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Make a single LLM call with logging and error handling."""
    timeout = min(ctx.policy.max_llm_seconds, max(5.0, ctx.time_left()))
    ctx.trajectory.log_llm_call(
        model=getattr(llm, "model", None),
        num_messages=len(messages),
    )
    opts: dict[str, Any] = {}
    if max_tokens is not None:
        opts["max_tokens"] = max_tokens
    if temperature is not None:
        opts["temperature"] = temperature

    resp = await llm.complete(messages, timeout=timeout, **opts)
    preview = resp.text[:300] if resp.text else ""
    ctx.trajectory.log_llm_result(
        model=getattr(llm, "model", None),
        usage=resp.usage,
        text_preview=preview,
    )
    return resp.text


def _build_system_prompt(plan: WritingPlan, phase: str = "draft") -> str:
    """Build a system prompt tailored to the writing plan and phase."""
    parts: list[str] = []

    if phase == "draft":
        parts.append("You are an expert creative writer.")
        if plan.is_eqbench:
            parts.append(
                "You excel at writing with emotional depth, empathy, and psychological realism. "
                "Preserve emotional nuance, theory of mind, role consistency, and genuine human "
                "complexity in your writing."
            )
        if plan.is_roleplay:
            parts.append(
                "You are skilled at maintaining character voice and staying in role throughout. "
                "Write consistently from the perspective of your assigned character."
            )
        parts.append(
            "Write in natural, flowing prose. Do not output JSON, metadata, code, or structured data. "
            "Do not include commentary about the writing process. Just write the requested content."
        )
    elif phase == "critique":
        parts.append(
            "You are a writing critic. Evaluate the draft against the original task constraints. "
            "Output a JSON object with: 'score' (0-1), 'issues' (list), 'strengths' (list), "
            "'revision_focus' (list of specific directions for improvement)."
        )
    elif phase == "revise":
        parts.append("You are an expert editor and reviser.")
        if plan.is_eqbench:
            parts.append("Preserve and deepen the emotional nuance and psychological realism.")
        if plan.is_roleplay:
            parts.append("Maintain strict role consistency throughout.")
        parts.append(
            "Revise the draft to address the critique. Write in natural, flowing prose. "
            "Do not output JSON, metadata, code, or structured data. "
            "Do not include commentary about the revision process."
        )

    if plan.genre and plan.genre != "general":
        parts.append(f"Genre: {plan.genre}")
    if plan.style:
        parts.append(f"Style: {plan.style}")
    if plan.tone:
        parts.append(f"Tone: {plan.tone}")
    if plan.audience:
        parts.append(f"Audience: {plan.audience}")
    if plan.role:
        parts.append(f"You are writing as: {plan.role}")

    return "\n".join(parts)


class GeneratedHarnessProgram:
    name = "writing-harness"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        prompt = ctx.task.prompt or "(no prompt)"

        # Determine if we have a real LLM or need the mock.
        # Try env-based LLM first (handles non-standard endpoints correctly),
        # then fall back to runtime-provided LLM, then mock.
        client = _build_llm_from_env()
        used_mock = False
        if client is None and llm is not None:
            client = llm
        if client is None:
            client = _fallback_llm()
            used_mock = True

        status = "success"
        error_path = None
        final_text = ""

        try:
            # Phase 1: Parse the task prompt.
            ctx.step()
            ctx.check_abort(stage="planning")
            ctx.trajectory.log_step(1, phase="planning", note="parse_prompt")
            plan = plan_from_prompt(prompt)
            ctx.new_artifact_json("plan.json", plan.to_dict())
            ctx.trajectory.log_observation(
                f"Parsed plan: genre={plan.genre}, length={plan.length_target}, "
                f"eqbench={plan.is_eqbench}, roleplay={plan.is_roleplay}",
                source="planner",
            )

            # Phase 2: Build outline (if LLM available).
            ctx.step()
            ctx.check_abort(stage="outline")
            ctx.trajectory.log_step(2, phase="outline", note="build_outline")
            try:
                plan = await build_outline_with_llm(plan, prompt, client, timeout=30.0)
                ctx.new_artifact_text("outline.md", plan.outline)
            except Exception as e:
                ctx.trajectory.log_observation(
                    f"Outline generation failed: {e}. Proceeding without outline.",
                    source="outline",
                )

            # Phase 3: Draft.
            ctx.step()
            ctx.check_abort(stage="draft")
            ctx.trajectory.log_step(3, phase="draft", note="generate_draft")

            system_prompt = _build_system_prompt(plan, phase="draft")
            draft_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            # Add outline context if available.
            if plan.outline:
                draft_messages.append({
                    "role": "assistant",
                    "content": f"I'll follow this outline:\n{plan.outline}",
                })
                draft_messages.append({
                    "role": "user",
                    "content": "Now write the full text following this outline and the original task.",
                })

            draft = await _complete(ctx, client, draft_messages, label="draft", temperature=0.8)
            draft_path = ctx.new_artifact_text("draft.md", draft)
            ctx.trajectory.log_artifact("draft.md", draft_path, kind="text")

            current = draft

            # Phase 4: Critique + revise loop.
            for rev_i in range(1, MAX_REVISIONS + 1):
                ctx.step()
                ctx.check_abort(stage=f"critique-{rev_i}")
                ctx.trajectory.log_step(3 + rev_i * 2 - 1, phase="critique", note=f"critique_{rev_i}")

                # Critique the current draft.
                critique_result = critique_draft(current, prompt=prompt, plan=plan)

                # Try LLM-based critique if available.
                try:
                    critique_result = await critique_with_llm(
                        current, prompt=prompt, plan=plan, llm=client, timeout=30.0,
                    )
                except Exception:
                    pass  # Sync critique is still valid.

                ctx.new_artifact_json(f"critique_{rev_i}.json", critique_result.to_dict())
                ctx.trajectory.log_observation(
                    f"Critique {rev_i}: score={critique_result.score:.2f}, "
                    f"issues={len(critique_result.issues)}, needs_revision={critique_result.needs_revision}",
                    source="critic",
                )

                if not critique_result.needs_revision:
                    ctx.trajectory.log_observation(
                        f"Draft passes critique at revision {rev_i}.", source="critic"
                    )
                    break

                # Phase 5: Revise.
                ctx.step()
                ctx.check_abort(stage=f"revise-{rev_i}")
                ctx.trajectory.log_step(3 + rev_i * 2, phase="revise", note=f"revise_{rev_i}")

                revision_system = _build_system_prompt(plan, phase="revise")
                critique_summary = "\n".join(f"- {i}" for i in critique_result.issues[:5])
                revision_focus = "\n".join(f"- {f}" for f in critique_result.revision_focus[:5])

                revise_messages = [
                    {"role": "system", "content": revision_system},
                    {"role": "user", "content": f"Original task:\n{prompt}"},
                    {"role": "assistant", "content": current},
                    {"role": "user", "content": (
                        f"Here is the critique of your draft:\n{critique_summary}\n\n"
                        f"Focus areas for revision:\n{revision_focus}\n\n"
                        "Please write an improved version that addresses these issues. "
                        "Output only the revised text, no commentary."
                    )},
                ]

                revised = await _complete(
                    ctx, client, revise_messages, label=f"revise_{rev_i}", temperature=0.7,
                )
                rev_path = ctx.new_artifact_text(f"revision_{rev_i}.md", revised)
                ctx.trajectory.log_artifact(f"revision_{rev_i}.md", rev_path, kind="text")
                current = revised

            final_text = current

            # Phase 6: Write final artifact and result.json BEFORE verification.
            answer_path = ctx.new_artifact_text(FINAL_ARTIFACT_NAME, final_text)
            ctx.trajectory.log_artifact(FINAL_ARTIFACT_NAME, answer_path, kind="text")

            # Write result.json early so verification can check it.
            result_data = {
                "status": "success",
                "trajectory": "trajectory.jsonl",
                "artifacts": {
                    "final_text": FINAL_ARTIFACT_NAME,
                },
            }
            ctx.new_artifact_json("result.json", result_data)

            # Run verification.
            verification = verify_artifacts(
                ctx.out_dir,
                final_text_name=FINAL_ARTIFACT_NAME,
                length_target=plan.length_target,
            )
            ctx.new_artifact_json("verification.json", verification)

            if not verification["ok"]:
                issues_str = "; ".join(verification.get("issues", []))
                ctx.trajectory.log_observation(
                    f"Verification issues: {issues_str}", source="verifier"
                )
                # If the text isn't prose or is too short, mark as partial.
                if not verification.get("checks", {}).get("is_prose", True):
                    status = "partial"
                    result_data["status"] = "partial"
                elif not verification.get("checks", {}).get("meets_length", True):
                    status = "partial"
                    result_data["status"] = "partial"

        except Exception as e:
            error_msg = f"Writing harness failed: {type(e).__name__}: {e}"
            ctx.trajectory.log_error({
                "error_code": ErrorCode.LLM_ERROR.value,
                "message": error_msg,
                "stage": self.name,
                "recoverable": True,
            })
            error_path = ctx.new_artifact_json(
                "error.json",
                {
                    "error_code": ErrorCode.LLM_ERROR.value,
                    "message": error_msg,
                    "stage": self.name,
                    "recoverable": True,
                },
            )
            # Write best-effort response.
            if not final_text:
                final_text = (
                    f"# Writing Task Response\n\n"
                    f"The writing harness encountered an error and could not complete the task.\n\n"
                    f"Error: {error_msg}\n"
                )
            answer_path = ctx.new_artifact_text(FINAL_ARTIFACT_NAME, final_text)
            status = "failed"
            result_data = {
                "status": status,
                "trajectory": "trajectory.jsonl",
                "artifacts": {
                    "final_text": FINAL_ARTIFACT_NAME,
                },
            }
            ctx.new_artifact_json("result.json", result_data)

        ctx.trajectory.log_step(ctx.budget.steps_used, phase="done", note=status)

        return make_result(
            ctx,
            status=status,
            answer_path=ctx.out_dir / FINAL_ARTIFACT_NAME,
            error_path=error_path,
            metadata={
                "program": self.name,
                "used_mock_llm": used_mock,
                "model": getattr(client, "model", None),
                "max_revisions": MAX_REVISIONS,
            },
        )


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
