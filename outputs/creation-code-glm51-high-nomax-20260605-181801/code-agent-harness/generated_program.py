"""Scaffold-native generated harness program: a ReAct-style code agent.

This program accepts a software engineering task (bug fix, feature, refactor,
test repair, etc.), inspects the repository, plans edits using an LLM,
applies changes via scaffold tools, verifies the result, and iterates until
the task is complete or the budget is exhausted.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.examples._common import make_result, try_tool
from harness_scaffold.tools.registry import ToolRegistry

from planner import TaskPlan, build_plan, extract_paths_from_prompt
from context_manager import (
    ContextWindow,
    build_system_prompt,
    build_initial_user_message,
    format_tool_result,
)
from verifier import run_verification, verify_artifacts, VerificationResult
from recovery import (
    FailureDiagnosis,
    EditTracker,
    diagnose_failure,
    build_retry_prompt,
    create_checkpoint,
    rollback_to_checkpoint,
)


def _normalize_string(s: str) -> str:
    """Normalize a string from LLM output, handling escaped newlines and quotes."""
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    s = s.replace('\\"', '"').replace("\\'", "'")
    return s


def _safe_relative(path_str: str, workdir: Path) -> str:
    """Get a relative path from workdir, or the original if not possible."""
    try:
        return str(Path(path_str).relative_to(workdir))
    except (ValueError, OSError):
        return path_str


class GeneratedHarnessProgram:
    name = "generated"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        ctx.check_abort(stage="start")

        prompt = ctx.task.prompt or "(no task prompt)"
        workdir = ctx.workdir
        out_dir = ctx.out_dir

        changed_files: list[str] = []
        commands_run: list[str] = []
        test_results: dict[str, Any] = {}
        error_path: Optional[Path] = None
        status: str = "failed"
        edit_tracker = EditTracker()

        try:
            result = await self._run_loop(
                ctx, tools, llm, prompt, workdir, out_dir,
                changed_files, commands_run, test_results, edit_tracker,
            )
            return result
        except Exception as exc:
            error_obj = {
                "error_code": ErrorCode.UNKNOWN_ERROR.value,
                "message": f"harness crashed: {type(exc).__name__}: {exc}",
                "stage": "main_loop",
                "recoverable": False,
            }
            error_path = ctx.new_artifact_json("error.json", error_obj)
            self._ensure_result_json(ctx, "failed", changed_files, commands_run, test_results)
            return make_result(
                ctx, status="unknown_error", error_path=error_path,
                metadata={
                    "program": self.name,
                    "changed_files": changed_files,
                    "commands_run": commands_run,
                    "tests": test_results,
                    "error": str(exc)[:500],
                },
            )

    async def _run_loop(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Optional[object],
        prompt: str,
        workdir: Path,
        out_dir: Path,
        changed_files: list[str],
        commands_run: list[str],
        test_results: dict[str, Any],
        edit_tracker: EditTracker,
    ) -> HarnessResult:
        """Main ReAct-style loop: plan -> act -> observe -> repeat."""
        error_path: Optional[Path] = None

        # --- Phase 1: Plan ---
        ctx.trajectory.log_step(1, phase="plan", note="build_task_plan")
        plan = await build_plan(ctx, tools)
        ctx.step()

        # --- Phase 2: Build context window ---
        context = ContextWindow()
        context.add_system(build_system_prompt(plan))
        context.add_user(build_initial_user_message(plan))

        # --- Phase 3: Execute ReAct loop ---
        max_steps = ctx.policy.max_steps if ctx.policy else 50
        step = 0
        finished = False
        finish_status = "failed"
        finish_message = ""
        last_action_type = ""
        consecutive_noops = 0

        while step < max_steps and not finished:
            step += 1
            ctx.check_abort(stage=f"react_step_{step}")

            if ctx.budget.steps_used >= max_steps - 1:
                finish_status = "partial"
                finish_message = "Budget exhausted before completion"
                break

            # Compress context if needed
            if context.needs_compression():
                context.compress()
                ctx.trajectory.log_info("context_compressed", step=step)

            # Get LLM decision
            action = await self._get_llm_action(ctx, tools, llm, context, step)
            if action is None:
                consecutive_noops += 1
                if consecutive_noops >= 3:
                    finish_status = "partial"
                    finish_message = "LLM returned no actionable response after multiple attempts"
                    break
                continue

            consecutive_noops = 0
            action_type = action.get("action", "")

            ctx.trajectory.log_info(
                "action",
                step=step,
                action=action_type,
                details={k: str(v)[:200] for k, v in action.items() if k != "content"},
            )

            # Execute the action
            tool_result: Optional[ToolResult] = None
            result_text = ""

            if action_type == "finish":
                finished = True
                finish_status = action.get("status", "partial")
                finish_message = action.get("message", "")
                if finish_status not in ("success", "partial", "failed"):
                    finish_status = "partial"
                break

            elif action_type == "read_file":
                path = action.get("path", "")
                ok, tool_result = await try_tool(ctx, tools, "file_read", {
                    "path": str(workdir / path) if not Path(path).is_absolute() else path,
                    "line_numbers": True,
                })
                if ok and tool_result:
                    result_text = format_tool_result("file_read", tool_result)
                else:
                    result_text = f"[ERROR] Could not read file: {path}"

            elif action_type == "search":
                pattern = action.get("pattern", "")
                search_path = action.get("path", str(workdir))
                glob_filter = action.get("glob", "")
                ok, tool_result = await try_tool(ctx, tools, "grep", {
                    "pattern": pattern,
                    "path": search_path,
                    "glob": glob_filter or None,
                    "limit": 100,
                })
                if ok and tool_result:
                    result_text = format_tool_result("grep", tool_result)
                else:
                    result_text = f"[ERROR] Search failed for pattern: {pattern}"

            elif action_type == "list_files":
                list_path = action.get("path", str(workdir))
                depth = action.get("depth", 3)
                ok, tool_result = await try_tool(ctx, tools, "tree", {
                    "path": list_path,
                    "depth": depth,
                    "max_entries": 200,
                })
                if ok and tool_result:
                    result_text = format_tool_result("tree", tool_result)
                else:
                    result_text = f"[ERROR] Could not list files at: {list_path}"

            elif action_type == "edit_file":
                path = action.get("path", "")
                old_string = _normalize_string(action.get("old_string", ""))
                new_string = _normalize_string(action.get("new_string", ""))
                abs_path = str(workdir / path) if not Path(path).is_absolute() else path

                # Read before for tracking
                before_ok, before_res = await try_tool(ctx, tools, "file_read", {"path": abs_path})

                ok, tool_result = await try_tool(ctx, tools, "file_edit", {
                    "path": abs_path,
                    "old_string": old_string,
                    "new_string": new_string,
                })
                if ok and tool_result and tool_result.ok:
                    rel = _safe_relative(abs_path, workdir)
                    if rel not in changed_files:
                        changed_files.append(rel)
                    edit_tracker.record(path, old_string, new_string, True)
                    result_text = format_tool_result("file_edit", tool_result)
                else:
                    err_msg = ""
                    if tool_result and tool_result.error:
                        err_msg = str(tool_result.error.get("message", ""))[:500]
                    edit_tracker.record(path, old_string, new_string, False)
                    result_text = f"[ERROR] Edit failed: {err_msg or 'old_string not found or ambiguous'}"

            elif action_type == "write_file":
                path = action.get("path", "")
                content = _normalize_string(action.get("content", ""))
                abs_path = str(workdir / path) if not Path(path).is_absolute() else path

                ok, tool_result = await try_tool(ctx, tools, "file_write", {
                    "path": abs_path,
                    "content": content,
                })
                if ok and tool_result and tool_result.ok:
                    rel = _safe_relative(abs_path, workdir)
                    if rel not in changed_files:
                        changed_files.append(rel)
                    edit_tracker.record(path, "", content, True)
                    result_text = format_tool_result("file_write", tool_result)
                else:
                    err_msg = ""
                    if tool_result and tool_result.error:
                        err_msg = str(tool_result.error.get("message", ""))[:500]
                    edit_tracker.record(path, "", content, False)
                    result_text = f"[ERROR] Write failed: {err_msg or 'unknown error'}"

            elif action_type == "run_command":
                command = action.get("command", "")
                commands_run.append(command)
                timeout = action.get("timeout", 120.0)
                ok, tool_result = await try_tool(ctx, tools, "bash", {
                    "command": command,
                    "timeout": timeout,
                })
                if ok and tool_result:
                    result_text = format_tool_result("bash", tool_result)
                else:
                    result_text = "[ERROR] Command execution failed"

            else:
                result_text = f"[ERROR] Unknown action: {action_type}. Use: read_file, search, list_files, edit_file, write_file, run_command, or finish."

            # Add results to context
            context.add_user(f"Step {step} action: {action_type}\nResult:\n{result_text}")

            # Check for stuck patterns
            if edit_tracker.is_stuck():
                context.add_user(
                    "WARNING: You appear to be making repeated failing edits. "
                    "Try a completely different approach, or use write_file to rewrite the entire file."
                )

            ctx.step()

        # --- Phase 4: Verification ---
        ctx.trajectory.log_step(step, phase="verify", note="run_verification")
        verification: Optional[VerificationResult] = None

        if changed_files:
            verification = await run_verification(
                ctx, tools, plan.test_commands, changed_files, plan.iteration,
            )
            test_results["verification"] = {
                "passed": verification.passed,
                "syntax_ok": verification.syntax_ok,
                "artifacts_exist": verification.artifacts_exist,
                "command": verification.command,
                "exit_code": verification.exit_code,
                "details": verification.details,
            }

            # If verification failed and we have budget, try one more recovery iteration
            if not verification.passed and ctx.budget.steps_left() > 5 and not finished:
                ctx.trajectory.log_info("recovery_attempt", step=step)
                # Let LLM try to fix the issue
                recovery_prompt = (
                    "## Verification Failed\n"
                    f"Test command: {verification.command}\n"
                    f"Exit code: {verification.exit_code}\n"
                )
                if verification.stderr:
                    recovery_prompt += f"Error output:\n```\n{verification.stderr[:3000]}\n```\n"
                recovery_prompt += (
                    "\nPlease fix the issue. Use edit_file or write_file to correct the code, "
                    "then use run_command to re-run the tests."
                )
                context.add_user(recovery_prompt)

                # Run a few more recovery steps
                for recovery_step in range(min(5, max_steps - step)):
                    step += 1
                    ctx.step()
                    ctx.check_abort(stage=f"recovery_{step}")

                    action = await self._get_llm_action(ctx, tools, llm, context, step)
                    if action is None:
                        break
                    if action.get("action") == "finish":
                        finish_status = action.get("status", "partial")
                        finish_message = action.get("message", "")
                        finished = True
                        break

                    # Execute recovery action (same dispatch as main loop)
                    result_text = await self._execute_action(
                        ctx, tools, action, workdir, changed_files, commands_run, edit_tracker,
                    )
                    context.add_user(f"Recovery step {recovery_step}: {action.get('action', '')}\nResult:\n{result_text}")

                # Re-verify
                if changed_files and not finished:
                    verification = await run_verification(
                        ctx, tools, plan.test_commands, changed_files, plan.iteration + 1,
                    )
                    test_results["recovery_verification"] = {
                        "passed": verification.passed,
                        "syntax_ok": verification.syntax_ok,
                        "exit_code": verification.exit_code,
                    }

        # --- Phase 5: Generate patch/diff artifact ---
        ctx.trajectory.log_step(step, phase="finalize", note="generate_diff")
        patch_path: Optional[Path] = None

        # Try to get git diff
        ok, diff_res = await try_tool(ctx, tools, "git_diff", {})
        if ok and diff_res and diff_res.ok and isinstance(diff_res.data, dict):
            artifact_path = diff_res.data.get("artifact")
            if artifact_path:
                patch_path = Path(artifact_path)

        # If no git diff or no changes captured, build a manual diff
        if patch_path is None and changed_files:
            diff_parts: list[str] = []
            for rel in changed_files:
                abs_path = workdir / rel
                if abs_path.exists():
                    ok, fr = await try_tool(ctx, tools, "file_read", {"path": str(abs_path)})
                    if ok and fr and fr.ok and isinstance(fr.data, dict):
                        content = fr.data.get("content", "")
                        diff_parts.append(f"--- a/{rel}\n+++ b/{rel}\n{content}")
            if diff_parts:
                diff_text = "\n".join(diff_parts)
                patch_path = ctx.new_artifact_text("patch.diff", diff_text, kind="diff")

        # --- Phase 6: Determine final status ---
        if finished and finish_status == "success":
            status = "success"
        elif finished and finish_status == "partial":
            status = "partial"
        elif verification and verification.passed:
            status = "success"
        elif changed_files:
            status = "partial"
        else:
            status = "failed"

        # Validate against domain artifact requirements
        artifact_check = await verify_artifacts(ctx, plan.target_files, require_patch=True)
        if status == "success" and not artifact_check.get("targets_exist", True) and plan.target_files:
            status = "partial"

        # Write the response
        body = self._build_response_body(
            status, prompt, changed_files, commands_run, test_results,
            finish_message, verification,
        )
        answer_path = ctx.new_artifact_text("response.md", body)

        # Write result.json
        self._ensure_result_json(ctx, status, changed_files, commands_run, test_results)

        ctx.trajectory.log_step(step + 1, phase="done", note=f"status={status}")

        return make_result(
            ctx,
            status=status,
            answer_path=answer_path,
            error_path=error_path,
            metadata={
                "program": self.name,
                "changed_files": changed_files,
                "commands_run": commands_run,
                "tests": test_results,
                "target_files": plan.target_files,
                "steps_used": ctx.budget.steps_used,
                "finish_message": finish_message,
            },
        )

    async def _get_llm_action(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: Any,
        context: ContextWindow,
        step: int,
    ) -> Optional[dict[str, Any]]:
        """Get the next action from the LLM. Returns parsed JSON or None."""
        if llm is None:
            return self._fallback_action(ctx, tools, step)

        messages = context.build_messages()
        try:
            response = await llm.complete(
                messages,
                temperature=0.2,
                max_tokens=1024,
            )
            text = response.text.strip()
            ctx.trajectory.log_llm_call(
                model=getattr(llm, "model", "unknown"),
                num_messages=len(messages),
                step=step,
            )
            ctx.trajectory.log_llm_result(
                model=getattr(llm, "model", "unknown"),
                usage=response.usage,
                step=step,
            )
        except Exception as exc:
            ctx.trajectory.log_error(
                {
                    "error_code": "llm_error",
                    "message": f"LLM call failed: {type(exc).__name__}: {exc}",
                    "step": step,
                },
                step=step,
            )
            return self._fallback_action(ctx, tools, step)

        # Parse the JSON action from the LLM response
        return self._parse_action(text)

    def _parse_action(self, text: str) -> Optional[dict[str, Any]]:
        """Parse a JSON action from the LLM response text."""
        # Try to extract JSON from the response
        # Sometimes LLMs wrap JSON in markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        # Try direct JSON parse
        try:
            action = json.loads(text)
            if isinstance(action, dict) and "action" in action:
                return action
        except json.JSONDecodeError:
            pass

        # Try to find JSON-like structure in the text
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                action = json.loads(text[brace_start:brace_end + 1])
                if isinstance(action, dict) and "action" in action:
                    return action
            except json.JSONDecodeError:
                pass

        # Try to extract action from natural language
        action = self._extract_action_from_text(text)
        if action:
            return action

        return None

    def _extract_action_from_text(self, text: str) -> Optional[dict[str, Any]]:
        """Try to extract an action from natural language when JSON parse fails."""
        lower = text.lower()

        # Check for finish intent
        if any(kw in lower for kw in ("task is complete", "i'm done", "finished", "all changes made")):
            if "fail" in lower:
                return {"action": "finish", "status": "failed", "message": text[:500]}
            return {"action": "finish", "status": "success", "message": text[:500]}

        # Check for read intent
        m = re.search(r'read(?:ing)?\s+(?:file\s+)?[`"\']?([^\s`"\']+\.\w+)[`"\']?', lower)
        if m:
            return {"action": "read_file", "path": m.group(1)}

        # Check for search intent
        m = re.search(r'search(?:ing)?\s+for\s+["\']([^"\']+)["\']', lower)
        if m:
            return {"action": "search", "pattern": m.group(1)}

        return None

    def _fallback_action(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        step: int,
    ) -> Optional[dict[str, Any]]:
        """Generate a fallback action when no LLM is available.

        Implements a simple heuristic-based agent for common code tasks.
        """
        prompt = ctx.task.prompt or ""
        target_files = extract_paths_from_prompt(prompt)

        # Step 1: Read target files if they exist
        if step == 1 and target_files:
            return {"action": "read_file", "path": target_files[0]}

        # Step 2: List files if no targets found
        if step <= 2 and not target_files:
            return {"action": "list_files", "path": str(ctx.workdir), "depth": 2}

        # Step 3: Search for relevant patterns
        if step == 3:
            # Extract key terms from the prompt
            words = re.findall(r'\b\w{4,}\b', prompt)
            if words:
                return {"action": "search", "pattern": words[0], "path": str(ctx.workdir)}

        # Without an LLM, we can't make intelligent edits, so finish early
        return {"action": "finish", "status": "partial", "message": "No LLM available for intelligent code editing"}

    async def _execute_action(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        action: dict[str, Any],
        workdir: Path,
        changed_files: list[str],
        commands_run: list[str],
        edit_tracker: EditTracker,
    ) -> str:
        """Execute a single action and return the result text."""
        action_type = action.get("action", "")

        if action_type == "read_file":
            path = action.get("path", "")
            abs_path = str(workdir / path) if not Path(path).is_absolute() else path
            ok, res = await try_tool(ctx, tools, "file_read", {
                "path": abs_path, "line_numbers": True,
            })
            return format_tool_result("file_read", res) if ok and res else f"[ERROR] Could not read: {path}"

        elif action_type == "search":
            pattern = action.get("pattern", "")
            ok, res = await try_tool(ctx, tools, "grep", {
                "pattern": pattern,
                "path": action.get("path", str(workdir)),
                "glob": action.get("glob") or None,
                "limit": 100,
            })
            return format_tool_result("grep", res) if ok and res else f"[ERROR] Search failed: {pattern}"

        elif action_type == "list_files":
            ok, res = await try_tool(ctx, tools, "tree", {
                "path": action.get("path", str(workdir)),
                "depth": action.get("depth", 3),
                "max_entries": 200,
            })
            return format_tool_result("tree", res) if ok and res else "[ERROR] Could not list files"

        elif action_type == "edit_file":
            path = action.get("path", "")
            abs_path = str(workdir / path) if not Path(path).is_absolute() else path
            ok, res = await try_tool(ctx, tools, "file_edit", {
                "path": abs_path,
                "old_string": _normalize_string(action.get("old_string", "")),
                "new_string": _normalize_string(action.get("new_string", "")),
            })
            if ok and res and res.ok:
                rel = _safe_relative(abs_path, workdir)
                if rel not in changed_files:
                    changed_files.append(rel)
                edit_tracker.record(path, action.get("old_string", ""), action.get("new_string", ""), True)
                return format_tool_result("file_edit", res)
            else:
                err = ""
                if res and res.error:
                    err = str(res.error.get("message", ""))[:500]
                edit_tracker.record(path, action.get("old_string", ""), action.get("new_string", ""), False)
                return f"[ERROR] Edit failed: {err or 'old_string not found'}"

        elif action_type == "write_file":
            path = action.get("path", "")
            abs_path = str(workdir / path) if not Path(path).is_absolute() else path
            ok, res = await try_tool(ctx, tools, "file_write", {
                "path": abs_path,
                "content": _normalize_string(action.get("content", "")),
            })
            if ok and res and res.ok:
                rel = _safe_relative(abs_path, workdir)
                if rel not in changed_files:
                    changed_files.append(rel)
                return format_tool_result("file_write", res)
            else:
                return "[ERROR] Write failed"

        elif action_type == "run_command":
            command = action.get("command", "")
            commands_run.append(command)
            ok, res = await try_tool(ctx, tools, "bash", {
                "command": command,
                "timeout": action.get("timeout", 120.0),
            })
            return format_tool_result("bash", res) if ok and res else "[ERROR] Command failed"

        return f"[ERROR] Unknown action: {action_type}"

    def _build_response_body(
        self,
        status: str,
        prompt: str,
        changed_files: list[str],
        commands_run: list[str],
        test_results: dict[str, Any],
        finish_message: str,
        verification: Optional[VerificationResult],
    ) -> str:
        """Build the response.md content."""
        parts = [
            f"# Code Agent Result\n",
            f"**Status:** {status}\n",
            f"## Task\n\n{prompt[:2000]}\n",
        ]
        if changed_files:
            parts.append("## Changed Files\n\n" + "\n".join(f"- `{f}`" for f in changed_files) + "\n")
        if commands_run:
            parts.append("## Commands Run\n\n" + "\n".join(f"- `{c}`" for c in commands_run[:20]) + "\n")
        if test_results:
            parts.append("## Test Results\n\n```json\n" + json.dumps(test_results, indent=2, default=str)[:3000] + "\n```\n")
        if verification:
            parts.append(
                f"## Verification\n\n"
                f"- Passed: {verification.passed}\n"
                f"- Syntax OK: {verification.syntax_ok}\n"
                f"- Artifacts exist: {verification.artifacts_exist}\n"
                f"- Test command: `{verification.command}`\n"
                f"- Exit code: {verification.exit_code}\n"
            )
        if finish_message:
            parts.append(f"## Notes\n\n{finish_message}\n")
        return "\n".join(parts)

    def _ensure_result_json(
        self,
        ctx: RuntimeContext,
        status: str,
        changed_files: list[str],
        commands_run: list[str],
        test_results: dict[str, Any],
    ) -> None:
        """Write result.json to the output directory."""
        result = {
            "status": status,
            "trajectory": "trajectory.jsonl",
            "artifacts": {},
            "changed_files": changed_files,
            "commands_run": commands_run,
            "tests": test_results,
        }
        ctx.new_artifact_json("result.json", result)


PROGRAM = GeneratedHarnessProgram()


def get_program() -> GeneratedHarnessProgram:
    return PROGRAM
