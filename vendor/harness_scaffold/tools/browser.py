"""BrowserTool: a bounded observe-act browsing loop on top of Playwright.

This is an *atomic* tool that drives a real (headless) browser via Playwright.
Playwright is an **optional dependency**: it is lazy-imported inside the methods
and a :class:`DependencyError` is raised immediately when it is missing.  No
online installs are ever attempted.

The tool exposes two surfaces:

* ``step(action, args)`` — perform a single browser action and return a
  structured observation.  Actions: ``navigate``, ``observe``, ``click``,
  ``type``, ``select``, ``submit``, ``screenshot``.
* ``run_loop(policy_fn, max_steps=...)`` — an observe-act loop driven by a
  caller-supplied policy function.  The loop is **strictly bounded** by
  ``max_steps`` (defaulting to ``ctx.policy.max_steps``) so a policy cannot
  spin forever guessing URLs.

The public :meth:`run` (the ``AtomicTool`` contract) dispatches a single action
described by ``args`` (so the runtime/LLM can call the tool step-by-step), or a
``steps`` list / ``loop`` plan that is executed under the same bound.

Screenshots are written to :class:`ArtifactStore` (never to stdout).  All output
is truncated to ``ctx.policy.max_output_bytes``.  Every error path returns a
structured ``ToolResult.fail`` with :data:`ErrorCode.BROWSER_ERROR` (or the
appropriate code for permission / dependency / timeout failures); the tool
never raises to its caller through :meth:`run` — the ``execute`` wrapper, and
the internal try/except here, convert exceptions to ``ToolResult``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from ..core.context import RuntimeContext
from ..core.errors import (
    BrowserError,
    DependencyError,
    ErrorCode,
    HarnessError,
    PermissionDenied,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from .base import AtomicTool

__all__ = ["BrowserTool", "get_tools"]


# Actions that mutate page state (i.e. not pure read-only observation).
_READ_ACTIONS = frozenset({"observe", "screenshot", "wait"})

# Actions the tool understands.
_KNOWN_ACTIONS = frozenset(
    {
        "navigate",
        "observe",
        "click",
        "type",
        "select",
        "submit",
        "screenshot",
        "wait",
    }
)


class BrowserTool(AtomicTool):
    """Observe-act browser automation tool (Playwright-backed)."""

    name = "browser"
    description = (
        "Drive a headless browser to navigate, observe the DOM, click, type, "
        "select, submit forms, and capture screenshots. Each call performs one "
        "action (or a bounded list of actions) and returns a structured "
        "observation. Requires the 'browser' optional dependency (playwright) "
        "and network permission for http(s) URLs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": sorted(_KNOWN_ACTIONS),
                "description": "The browser action to perform.",
            },
            "url": {
                "type": "string",
                "description": "Target URL for 'navigate' (http(s):// or file://).",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector for click/type/select/submit.",
            },
            "text": {
                "type": "string",
                "description": "Text to type for the 'type' action.",
            },
            "value": {
                "type": "string",
                "description": "Option value for the 'select' action.",
            },
            "name": {
                "type": "string",
                "description": "Artifact name for the 'screenshot' action.",
            },
            "timeout": {
                "type": "number",
                "description": "Per-action timeout in seconds (clamped to budget).",
            },
            "steps": {
                "type": "array",
                "description": "Optional list of {action, ...} dicts run in order.",
                "items": {"type": "object"},
            },
            "max_steps": {
                "type": "integer",
                "description": "Upper bound on actions executed (defaults to policy.max_steps).",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "observations": {"type": "array", "items": {"type": "object"}},
            "final_url": {"type": "string"},
            "steps_used": {"type": "integer"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = True
    requires_optional_dependency = True
    optional_dependency_module = "playwright"
    optional_dependency_extra = "browser"

    # ------------------------------------------------------------------
    # AtomicTool contract
    # ------------------------------------------------------------------
    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        """Execute one action, or a bounded ``steps`` plan, in a browser session.

        Never raises: every failure is returned as ``ToolResult.fail`` with a
        structured error code.
        """
        args = args or {}
        # Resolve the plan of actions. A single-action call is the common case
        # (so the LLM can drive the observe-act loop turn-by-turn), but a
        # bounded ``steps`` list is also supported.
        plan = self._resolve_plan(args)
        if not plan:
            return ToolResult.fail(
                "browser tool requires an 'action' or non-empty 'steps' list",
                error_code=ErrorCode.BROWSER_ERROR,
                stage="browser:plan",
            )

        # Hard bound on the number of actions: prevents infinite URL-guessing.
        max_steps = args.get("max_steps")
        if not isinstance(max_steps, int) or max_steps <= 0:
            max_steps = ctx.policy.max_steps
        max_steps = max(1, int(max_steps))
        if len(plan) > max_steps:
            return ToolResult.fail(
                f"plan has {len(plan)} actions but max_steps={max_steps}",
                error_code=ErrorCode.BROWSER_ERROR,
                stage="browser:plan",
                details={"requested": len(plan), "max_steps": max_steps},
            )

        # Validate actions before launching a browser (fail fast, cheaply).
        for i, item in enumerate(plan):
            action = (item or {}).get("action")
            if action not in _KNOWN_ACTIONS:
                return ToolResult.fail(
                    f"unknown browser action '{action}' at step {i}",
                    error_code=ErrorCode.BROWSER_ERROR,
                    stage="browser:plan",
                    details={"action": action, "known": sorted(_KNOWN_ACTIONS)},
                )

        start = time.time()
        try:
            session = await self._launch(ctx)
        except HarnessError as exc:
            return ToolResult.fail(
                str(exc),
                error_code=exc.error_code,
                stage=getattr(exc, "stage", "browser:launch"),
                details=getattr(exc, "details", None),
                elapsed_seconds=time.time() - start,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                f"failed to launch browser: {exc}",
                error_code=ErrorCode.BROWSER_ERROR,
                stage="browser:launch",
                elapsed_seconds=time.time() - start,
            )

        observations: list[dict] = []
        artifacts: dict[str, Path] = {}
        try:
            for i, item in enumerate(plan):
                # Respect budget / abort between every action.
                ctx.check_abort(stage="browser")
                if ctx.budget is not None and ctx.budget.seconds_left() <= 0:
                    raise TimeoutErrorH(
                        "browser loop exceeded the time budget",
                        stage="browser:budget",
                    )
                obs = await self.step(ctx, item, _session=session)
                observations.append(obs)
                for k, v in (obs.get("artifacts") or {}).items():
                    artifacts[k] = v
                # Stop early if an action reported a hard failure.
                if obs.get("ok") is False and obs.get("fatal"):
                    break
        except HarnessError as exc:
            await self._close(session)
            return ToolResult.fail(
                str(exc),
                error_code=exc.error_code,
                stage=getattr(exc, "stage", "browser"),
                details=getattr(exc, "details", None),
                elapsed_seconds=time.time() - start,
                artifacts=artifacts or None,
                metadata={"observations": observations},
            )
        except Exception as exc:  # noqa: BLE001
            await self._close(session)
            return ToolResult.fail(
                f"browser action failed: {exc}",
                error_code=ErrorCode.BROWSER_ERROR,
                stage="browser",
                elapsed_seconds=time.time() - start,
                artifacts=artifacts or None,
                metadata={"observations": observations},
            )

        final_url = ""
        try:
            final_url = session.page.url or ""
        except Exception:  # noqa: BLE001
            final_url = ""
        await self._close(session)

        # Did every action succeed?
        any_failed = any(o.get("ok") is False for o in observations)
        data = {
            "observations": observations,
            "final_url": final_url,
            "steps_used": len(observations),
        }
        preview = self._observations_preview(observations)
        if any_failed:
            # Surface a structured browser_error if a target was never found.
            last_err = next(
                (o.get("error") for o in reversed(observations) if o.get("error")),
                "one or more browser actions failed",
            )
            return ToolResult.fail(
                str(last_err),
                error_code=ErrorCode.BROWSER_ERROR,
                stage="browser",
                details=data,
                elapsed_seconds=time.time() - start,
                artifacts=artifacts or None,
                stdout_preview=preview,
                metadata={"observations": observations, "final_url": final_url},
            )
        return ToolResult.success(
            data=data,
            artifacts=artifacts or None,
            stdout_preview=preview,
            elapsed_seconds=time.time() - start,
            metadata={"final_url": final_url, "steps_used": len(observations)},
        )

    # ------------------------------------------------------------------
    # Single-action surface
    # ------------------------------------------------------------------
    async def step(
        self, ctx: RuntimeContext, item: dict, *, _session: "_BrowserSession" = None
    ) -> dict:
        """Perform a single browser action and return a structured observation.

        When ``_session`` is None a fresh browser is launched for just this
        action and closed afterwards (convenient for one-shot use). When called
        from :meth:`run`/:meth:`run_loop` an existing session is reused.

        Returns an observation dict; on failure it returns a dict with
        ``ok=False`` and an ``error`` message rather than raising — but
        budget/abort/timeout/permission/dependency conditions DO propagate as
        ``HarnessError`` so the loop can stop cleanly.
        """
        item = item or {}
        action = item.get("action")
        owns_session = _session is None
        session = _session
        if owns_session:
            session = await self._launch(ctx)
        t0 = time.time()
        try:
            obs = await self._dispatch(ctx, session, action, item)
        except (PermissionDenied, DependencyError, TimeoutErrorH):
            # Hard, non-retryable conditions: let the loop handle/stop.
            if owns_session:
                await self._close(session)
            raise
        except HarnessError:
            if owns_session:
                await self._close(session)
            raise
        except Exception as exc:  # noqa: BLE001
            obs = {
                "ok": False,
                "action": action,
                "error": f"{action} failed: {exc}",
            }
        obs.setdefault("action", action)
        obs["elapsed_seconds"] = round(time.time() - t0, 4)
        try:
            ctx.trajectory.log_observation(
                self._truncate_for_log(obs), source="browser"
            )
        except Exception:  # noqa: BLE001
            pass
        if owns_session:
            try:
                obs.setdefault("final_url", session.page.url or "")
            except Exception:  # noqa: BLE001
                pass
            await self._close(session)
        return obs

    # ------------------------------------------------------------------
    # Observe-act loop
    # ------------------------------------------------------------------
    async def run_loop(
        self,
        ctx: RuntimeContext,
        policy_fn: Callable[[dict, list], dict | None],
        *,
        max_steps: int | None = None,
        start_action: dict | None = None,
    ) -> dict:
        """Run a bounded observe-act loop driven by ``policy_fn``.

        ``policy_fn(last_observation, history) -> next_action_dict | None``.
        Returning ``None`` (or an empty dict) ends the loop. The loop is hard
        bounded by ``max_steps`` (default ``ctx.policy.max_steps``) so a policy
        can never spin forever; when the bound is hit before the policy decides
        to stop, a structured ``browser_error`` observation is appended.

        Returns ``{"observations", "final_url", "steps_used", "stopped_reason"}``.
        """
        if max_steps is None or max_steps <= 0:
            max_steps = ctx.policy.max_steps
        max_steps = max(1, int(max_steps))

        session = await self._launch(ctx)
        observations: list[dict] = []
        stopped_reason = "policy_stop"
        try:
            next_action = start_action
            last_obs: dict = {}
            for _ in range(max_steps):
                ctx.check_abort(stage="browser:loop")
                if ctx.budget is not None and ctx.budget.seconds_left() <= 0:
                    stopped_reason = "budget_exhausted"
                    break
                if next_action is None:
                    next_action = policy_fn(last_obs, observations)
                if not next_action:
                    stopped_reason = "policy_stop"
                    break
                last_obs = await self.step(ctx, next_action, _session=session)
                observations.append(last_obs)
                next_action = None
            else:
                # Loop exhausted max_steps without the policy choosing to stop.
                stopped_reason = "max_steps_reached"
                observations.append(
                    {
                        "ok": False,
                        "action": "loop",
                        "error": (
                            f"target not reached after max_steps={max_steps}"
                        ),
                        "fatal": True,
                    }
                )
            final_url = ""
            try:
                final_url = session.page.url or ""
            except Exception:  # noqa: BLE001
                final_url = ""
            return {
                "observations": observations,
                "final_url": final_url,
                "steps_used": len(observations),
                "stopped_reason": stopped_reason,
            }
        finally:
            await self._close(session)

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------
    async def _dispatch(
        self,
        ctx: RuntimeContext,
        session: "_BrowserSession",
        action: str,
        item: dict,
    ) -> dict:
        if action == "navigate":
            return await self._do_navigate(ctx, session, item)
        if action == "observe":
            return await self._do_observe(ctx, session, item)
        if action == "click":
            return await self._do_click(ctx, session, item)
        if action == "type":
            return await self._do_type(ctx, session, item)
        if action == "select":
            return await self._do_select(ctx, session, item)
        if action == "submit":
            return await self._do_submit(ctx, session, item)
        if action == "screenshot":
            return await self._do_screenshot(ctx, session, item)
        if action == "wait":
            return await self._do_wait(ctx, session, item)
        raise BrowserError(
            f"unknown browser action '{action}'",
            stage="browser:dispatch",
        )

    # --- individual actions -------------------------------------------
    async def _do_navigate(self, ctx, session, item) -> dict:
        url = (item.get("url") or "").strip()
        if not url:
            return {"ok": False, "action": "navigate", "error": "missing 'url'"}
        url = self._check_url(ctx, url)
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            resp = await session.page.goto(
                url, timeout=timeout_ms, wait_until="domcontentloaded"
            )
        except Exception as exc:  # noqa: BLE001 (playwright errors are dynamic)
            if self._is_timeout(exc):
                raise TimeoutErrorH(
                    f"navigation to {url} timed out after {timeout_ms/1000:.1f}s",
                    stage="browser:navigate",
                )
            raise BrowserError(
                f"navigation to {url} failed: {exc}",
                stage="browser:navigate",
                details={"url": url},
            )
        status = getattr(resp, "status", None) if resp is not None else None
        return {
            "ok": True,
            "action": "navigate",
            "url": session.page.url,
            "status": status,
        }

    async def _do_observe(self, ctx, session, item) -> dict:
        max_elements = int(item.get("max_elements") or 50)
        max_bytes = ctx.policy.max_output_bytes
        try:
            title = await session.page.title()
        except Exception:  # noqa: BLE001
            title = ""
        # Visible text content of the body.
        try:
            text = await session.page.inner_text("body")
        except Exception:  # noqa: BLE001
            text = ""
        text = self._truncate(text, max_bytes)
        # Interactive elements.
        elements = await self._collect_interactive(session, max_elements)
        return {
            "ok": True,
            "action": "observe",
            "url": session.page.url,
            "title": title,
            "text": text,
            "interactive_elements": elements,
        }

    async def _do_click(self, ctx, session, item) -> dict:
        selector = item.get("selector")
        if not selector:
            return {"ok": False, "action": "click", "error": "missing 'selector'"}
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            await session.page.click(selector, timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return self._not_found_or_error("click", selector, exc, timeout_ms)
        return {"ok": True, "action": "click", "selector": selector, "url": session.page.url}

    async def _do_type(self, ctx, session, item) -> dict:
        selector = item.get("selector")
        text = item.get("text", "")
        if not selector:
            return {"ok": False, "action": "type", "error": "missing 'selector'"}
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            await session.page.fill(selector, str(text), timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return self._not_found_or_error("type", selector, exc, timeout_ms)
        return {
            "ok": True,
            "action": "type",
            "selector": selector,
            "chars": len(str(text)),
        }

    async def _do_select(self, ctx, session, item) -> dict:
        selector = item.get("selector")
        value = item.get("value")
        if not selector:
            return {"ok": False, "action": "select", "error": "missing 'selector'"}
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            await session.page.select_option(
                selector, value=str(value) if value is not None else None,
                timeout=timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001
            return self._not_found_or_error("select", selector, exc, timeout_ms)
        return {"ok": True, "action": "select", "selector": selector, "value": value}

    async def _do_submit(self, ctx, session, item) -> dict:
        selector = item.get("selector")
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            if selector:
                # Submit by pressing Enter inside the field / clicking submit.
                await session.page.press(selector, "Enter", timeout=timeout_ms)
            else:
                await session.page.evaluate(
                    "() => { const f = document.querySelector('form');"
                    " if (f) f.submit(); else throw new Error('no form'); }"
                )
            try:
                await session.page.wait_for_load_state(
                    "domcontentloaded", timeout=timeout_ms
                )
            except Exception:  # noqa: BLE001 (no navigation is fine)
                pass
        except Exception as exc:  # noqa: BLE001
            return self._not_found_or_error("submit", selector or "<form>", exc, timeout_ms)
        return {"ok": True, "action": "submit", "selector": selector, "url": session.page.url}

    async def _do_screenshot(self, ctx, session, item) -> dict:
        name = item.get("name") or "screenshot.png"
        if not name.lower().endswith((".png", ".jpg", ".jpeg")):
            name = name + ".png"
        # Namespace under screenshots/ in the artifact store.
        if "/" not in name:
            name = f"screenshots/{name}"
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            png: bytes = await session.page.screenshot(
                full_page=bool(item.get("full_page", True)), timeout=timeout_ms
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_timeout(exc):
                raise TimeoutErrorH(
                    "screenshot timed out", stage="browser:screenshot"
                )
            raise BrowserError(
                f"screenshot failed: {exc}", stage="browser:screenshot"
            )
        try:
            path = ctx.artifact_store.put_bytes(name, png, kind="image")
        except HarnessError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(
                f"failed to store screenshot artifact: {exc}",
                stage="browser:screenshot",
            )
        try:
            ctx.trajectory.log_artifact(name, path, kind="image", size_bytes=len(png))
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "action": "screenshot",
            "artifact": name,
            "path": str(path),
            "size_bytes": len(png),
            "artifacts": {name: path},
        }

    async def _do_wait(self, ctx, session, item) -> dict:
        selector = item.get("selector")
        timeout_ms = self._timeout_ms(ctx, item)
        try:
            if selector:
                await session.page.wait_for_selector(selector, timeout=timeout_ms)
            else:
                await session.page.wait_for_load_state(
                    "networkidle", timeout=timeout_ms
                )
        except Exception as exc:  # noqa: BLE001
            return self._not_found_or_error("wait", selector or "<load>", exc, timeout_ms)
        return {"ok": True, "action": "wait", "selector": selector}

    # ------------------------------------------------------------------
    # Browser lifecycle (Playwright, lazy-imported)
    # ------------------------------------------------------------------
    async def _launch(self, ctx: RuntimeContext) -> "_BrowserSession":
        # Lazy import; missing -> DependencyError immediately (no install).
        from ..core.dependency import require

        require(
            "playwright",
            extra=self.optional_dependency_extra,
            purpose=f"tool '{self.name}'",
        )
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # noqa: BLE001
            raise DependencyError(
                f"playwright is installed but not importable: {exc}",
                details={"module": "playwright.async_api"},
            )
        try:
            pw_cm = async_playwright()
            pw = await pw_cm.start()
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            # Default per-page timeout from policy (clamped to budget).
            page.set_default_timeout(self._timeout_ms(ctx, {}))
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(
                f"failed to launch chromium (is it installed? "
                f"run 'playwright install chromium'): {exc}",
                stage="browser:launch",
            )
        return _BrowserSession(pw=pw, browser=browser, context=context, page=page)

    async def _close(self, session: "_BrowserSession" | None) -> None:
        if session is None:
            return
        for closer in (
            getattr(session, "context", None),
            getattr(session, "browser", None),
        ):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if session.pw is not None:
                await session.pw.stop()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_plan(self, args: dict) -> list[dict]:
        steps = args.get("steps")
        if isinstance(steps, list) and steps:
            return [s for s in steps if isinstance(s, dict)]
        action = args.get("action")
        if action:
            single = {k: v for k, v in args.items() if k not in ("steps", "max_steps")}
            single["action"] = action
            return [single]
        return []

    def _check_url(self, ctx: RuntimeContext, url: str) -> str:
        """Validate a navigation target: file:// must stay in the sandbox;
        http(s):// requires network permission."""
        lowered = url.lower()
        if lowered.startswith("file://"):
            # Confine local file URLs to the readable sandbox.
            from urllib.parse import unquote, urlparse

            parsed = urlparse(url)
            local = unquote(parsed.path or "")
            checked = ctx.check_path_read(Path(local))
            return checked.as_uri()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            ctx.permissions.check_network(url)
            return url
        if lowered.startswith("about:") or lowered == "about:blank":
            return url
        # Anything else (data:, javascript:, chrome:, etc.) is refused.
        raise BrowserError(
            f"unsupported URL scheme for '{url}' (allowed: http, https, file)",
            stage="browser:navigate",
            details={"url": url},
        )

    def _timeout_ms(self, ctx: RuntimeContext, item: dict) -> int:
        """Resolve a per-action timeout in milliseconds, clamped to budget."""
        seconds = item.get("timeout")
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            seconds = ctx.policy.max_tool_seconds
        if ctx.budget is not None:
            left = ctx.budget.seconds_left()
            if left and left > 0:
                seconds = min(seconds, left)
        seconds = max(0.1, float(seconds))
        return int(seconds * 1000)

    async def _collect_interactive(self, session, max_elements: int) -> list[dict]:
        script = """
        (max) => {
          const out = [];
          const sel = 'a, button, input, select, textarea, [role=button], [onclick]';
          const nodes = document.querySelectorAll(sel);
          for (let i = 0; i < nodes.length && out.length < max; i++) {
            const el = nodes[i];
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0) continue;
            const tag = el.tagName.toLowerCase();
            let label = (el.innerText || el.value || el.getAttribute('aria-label')
                         || el.getAttribute('placeholder') || el.name || '').trim();
            if (label.length > 120) label = label.slice(0, 120);
            out.push({
              tag: tag,
              type: el.getAttribute('type') || null,
              id: el.id || null,
              name: el.getAttribute('name') || null,
              text: label,
              href: el.getAttribute('href') || null,
            });
          }
          return out;
        }
        """
        try:
            return await session.page.evaluate(script, max_elements)
        except Exception:  # noqa: BLE001
            return []

    def _not_found_or_error(self, action, selector, exc, timeout_ms) -> dict:
        if self._is_timeout(exc):
            return {
                "ok": False,
                "action": action,
                "selector": selector,
                "error": (
                    f"element '{selector}' not found / not actionable within "
                    f"{timeout_ms/1000:.1f}s"
                ),
            }
        return {
            "ok": False,
            "action": action,
            "selector": selector,
            "error": f"{action} on '{selector}' failed: {exc}",
        }

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        return "timeout" in name or "timeout" in str(exc).lower()

    @staticmethod
    def _truncate(text: str, max_bytes: int) -> str:
        if not text:
            return text
        from ..core.serialization import truncate

        return truncate(text, max_bytes)

    def _observations_preview(self, observations: list[dict]) -> str:
        parts = []
        for o in observations:
            line = f"[{o.get('action')}] ok={o.get('ok')}"
            if o.get("url"):
                line += f" url={o['url']}"
            if o.get("error"):
                line += f" error={o['error']}"
            parts.append(line)
        return "\n".join(parts)[:1000]

    @staticmethod
    def _truncate_for_log(obs: dict) -> dict:
        out = dict(obs)
        if isinstance(out.get("text"), str) and len(out["text"]) > 2000:
            out["text"] = out["text"][:2000] + "...[truncated]"
        # Don't log raw Path objects through the JSONL redactor unnecessarily.
        if "artifacts" in out:
            out["artifacts"] = {k: str(v) for k, v in (out["artifacts"] or {}).items()}
        return out


class _BrowserSession:
    """Holds the live Playwright objects for one browser session."""

    __slots__ = ("pw", "browser", "context", "page")

    def __init__(self, *, pw, browser, context, page):
        self.pw = pw
        self.browser = browser
        self.context = context
        self.page = page


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return the tool instances exposed by this module."""
    return [BrowserTool()]
