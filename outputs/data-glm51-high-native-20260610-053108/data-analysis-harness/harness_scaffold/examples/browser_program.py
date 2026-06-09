"""browser_program -- BrowserTool observe-act loop over local HTML.

Demonstrates a bounded observe -> act loop driving a browser tool against a
LOCAL HTML file (no network). Each iteration: observe the current page, decide
on an action (follow the next local link), act, and capture a screenshot
artifact under ``screenshots/``. The loop is bounded by
``min(ctx.policy.max_steps, max_steps)``.

If the ``browser`` atomic tool is unavailable (it requires an optional
headless-browser dependency), the program degrades to a stdlib ``html.parser``
"text observation" of the page and writes a placeholder text "screenshot" -- so
the example still runs offline with zero optional deps, exercising the same
loop structure and producing the same artifact shapes.

Seed page: ``task.metadata['start']`` (a path) or the first ``*.html`` file
under the workdir.

Run offline:
    python -m harness_scaffold.adapters.cli \
        --task-json <task.json> \
        --program harness_scaffold/examples/browser_program.py \
        --out-dir /tmp/browser
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from harness_scaffold.adapters.bmk_io import SCREENSHOTS_DIR
from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import make_result, try_tool

DEFAULT_MAX_STEPS = 3


class _TextLinkParser(HTMLParser):
    """Minimal stdlib observation: collect visible text + local hrefs."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: "list[str]" = []
        self.links: "list[str]" = []
        self.title: Optional[str] = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        s = data.strip()
        if not s:
            return
        if self._in_title and not self.title:
            self.title = s
        else:
            self.text_parts.append(s)

    def text(self) -> str:
        return " ".join(self.text_parts)


def _seed_page(ctx: RuntimeContext) -> Optional[Path]:
    meta = ctx.task.metadata or {}
    start = meta.get("start")
    if start:
        p = Path(start)
        if not p.is_absolute():
            p = (ctx.workdir / start).resolve()
        if p.is_file():
            return p
    for p in sorted(ctx.workdir.rglob("*.html")):
        if p.is_file():
            return p
    return None


async def _browser_observe(ctx, tools, target: str) -> "tuple[Optional[dict], bool]":
    """Try the real browser tool; return (observation, used_tool)."""
    ok, res = await try_tool(
        ctx, tools, "browser", {"action": "observe", "url": target}
    )
    if ok and res is not None and res.ok and isinstance(res.data, dict):
        return res.data, True
    return None, False


class BrowserProgram:
    name: str = "browser"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: "Optional[object]",
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        meta = ctx.task.metadata or {}
        max_steps = int(meta.get("max_steps", DEFAULT_MAX_STEPS))
        max_steps = max(1, min(max_steps, ctx.policy.max_steps))

        page = _seed_page(ctx)
        if page is None:
            ans = ctx.new_artifact_text(
                "response.md",
                f"# {self.name}\n\nNo local HTML page found under "
                f"`{ctx.workdir}`.\n",
            )
            return make_result(ctx, status="success", answer_path=ans,
                               metadata={"program": self.name, "pages_visited": 0})

        shots_dir = ctx.out_dir / SCREENSHOTS_DIR
        observations: "list[dict]" = []
        visited: "set[str]" = set()
        current = page
        used_browser_tool = False

        for step_i in range(max_steps):
            if ctx.budget.steps_left() <= 0:
                break
            ctx.step()
            ctx.check_abort(stage=f"observe-{step_i}")

            key = str(current)
            if key in visited:
                break
            visited.add(key)

            # --- observe ---
            obs, used = await _browser_observe(ctx, tools, str(current))
            if used and obs is not None:
                used_browser_tool = True
                text = obs.get("text", "")
                title = obs.get("title", current.name)
                links = obs.get("links", []) or []
                shot_b64 = obs.get("screenshot")  # tool may return base64 PNG
                if isinstance(shot_b64, str) and shot_b64:
                    import base64

                    try:
                        ctx.new_artifact_bytes(
                            f"{SCREENSHOTS_DIR}/page_{step_i}.png",
                            base64.b64decode(shot_b64),
                        )
                    except Exception:
                        pass
            else:
                # stdlib fallback observation over local HTML
                html = ""
                try:
                    html = ctx.check_path_read(current).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception:
                    pass
                parser = _TextLinkParser()
                parser.feed(html)
                text = parser.text()
                title = parser.title or current.name
                links = parser.links
                # "screenshot" placeholder: a text rendering of the page
                ctx.new_artifact_text(
                    f"{SCREENSHOTS_DIR}/page_{step_i}.txt",
                    f"[text-render fallback] {title}\n\n{text[:2000]}\n",
                )

            ctx.trajectory.log_observation(
                f"observed {title!r} ({len(links)} links)", source="browser"
            )
            observations.append(
                {"step": step_i, "url": str(current), "title": title,
                 "chars": len(text), "links": len(links)}
            )

            # --- act: follow the first unvisited *local* link ---
            next_page = None
            for href in links:
                if href.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                cand = (current.parent / href).resolve()
                if cand.is_file() and str(cand) not in visited:
                    next_page = cand
                    break
            if next_page is None:
                break
            current = next_page

        body_lines = [
            f"# {self.name}",
            "",
            f"Visited {len(observations)} page(s) "
            f"({'browser tool' if used_browser_tool else 'stdlib fallback'}).",
            "",
        ]
        for o in observations:
            body_lines.append(
                f"- step {o['step']}: **{o['title']}** "
                f"({o['chars']} chars, {o['links']} links)"
            )
        body = "\n".join(body_lines) + "\n"
        answer_path = ctx.new_artifact_text("response.md", body)
        ctx.trajectory.log_step(1, phase="done")

        return make_result(
            ctx,
            status="success",
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "pages_visited": len(observations),
                "max_steps": max_steps,
                "used_browser_tool": used_browser_tool,
                "screenshots_dir": str(shots_dir),
            },
        )


PROGRAM = BrowserProgram()


def get_program() -> BrowserProgram:
    return PROGRAM
