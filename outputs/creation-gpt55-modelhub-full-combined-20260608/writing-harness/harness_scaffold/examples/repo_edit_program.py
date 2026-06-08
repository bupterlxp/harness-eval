"""repo_edit_program -- file / grep / edit / patch + git diff -> patch.diff.

Demonstrates composing the filesystem / search / patch atomic tools to make a
small code edit in the task workdir and emit the change as a unified diff
artifact (``patch.diff``).

It prefers the registered atomic tools (``grep``/``file_read``/``file_write``/
``git_diff``) when present, but if those leaf modules are not installed it
degrades to a stdlib implementation (``pathlib`` + ``difflib``) so the example
still runs offline with zero optional deps.

Behaviour: find a target file (from ``task.metadata['target']`` or the first
text file under the workdir), apply a literal find/replace
(``task.metadata['find']`` -> ``task.metadata['replace']``, defaults below),
and write the resulting unified diff to ``patch.diff`` plus a ``response.md``.

Run offline:
    python -m harness_scaffold.adapters.cli \
        --task-json <task.json> \
        --program harness_scaffold/examples/repo_edit_program.py \
        --out-dir /tmp/repo
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

from harness_scaffold.adapters.bmk_io import PATCH_DIFF
from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import make_result, try_tool

DEFAULT_FIND = "TODO"
DEFAULT_REPLACE = "DONE"


def _pick_target(ctx: RuntimeContext) -> Optional[Path]:
    meta = ctx.task.metadata or {}
    target = meta.get("target")
    if target:
        p = (ctx.workdir / target).resolve()
        if p.is_file():
            return p
    # fall back to first small text-ish file under the workdir
    for p in sorted(ctx.workdir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}:
            continue
        try:
            if p.stat().st_size > 200_000:
                continue
        except OSError:
            continue
        return p
    return None


async def _read_text(ctx, tools, path: Path) -> Optional[str]:
    ok, res = await try_tool(ctx, tools, "file_read", {"path": str(path)})
    if ok and res is not None and res.ok and isinstance(res.data, dict):
        content = res.data.get("content")
        if isinstance(content, str):
            return content
    # stdlib fallback
    try:
        return ctx.check_path_read(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


async def _write_text(ctx, tools, path: Path, content: str) -> bool:
    ok, res = await try_tool(
        ctx, tools, "file_write", {"path": str(path), "content": content}
    )
    if ok and res is not None and res.ok:
        return True
    # stdlib fallback (respects sandbox via check_path_write)
    try:
        ctx.check_path_write(path).write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


class RepoEditProgram:
    name: str = "repo_edit"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: "Optional[object]",
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        meta = ctx.task.metadata or {}
        find = str(meta.get("find", DEFAULT_FIND))
        replace = str(meta.get("replace", DEFAULT_REPLACE))

        target = _pick_target(ctx)
        if target is None:
            err = ctx.new_artifact_json(
                "error.json",
                {
                    "error_code": ErrorCode.FILESYSTEM_ERROR.value,
                    "message": "no editable file found in workdir",
                    "stage": self.name,
                    "details": {"workdir": str(ctx.workdir)},
                    "recoverable": False,
                    "elapsed_seconds": 0.0,
                },
            )
            ans = ctx.new_artifact_text(
                "response.md",
                f"# {self.name}\n\nNo editable file was found under "
                f"`{ctx.workdir}`.\n",
            )
            return make_result(
                ctx, status="filesystem_error", answer_path=ans, error_path=err,
                metadata={"program": self.name},
            )

        ctx.step()
        before = await _read_text(ctx, tools, target)
        if before is None:
            ans = ctx.new_artifact_text(
                "response.md", f"# {self.name}\n\nCould not read `{target}`.\n"
            )
            return make_result(ctx, status="filesystem_error", answer_path=ans,
                               metadata={"program": self.name})

        # grep-like search to report match count (prefer the grep tool)
        match_count = before.count(find)
        ok, gres = await try_tool(
            ctx, tools, "grep", {"pattern": find, "path": str(target)}
        )
        if ok and gres is not None and gres.ok:
            ctx.trajectory.log_observation(
                f"grep tool searched for {find!r}", source="grep"
            )

        after = before.replace(find, replace)
        changed = after != before

        try:
            rel = target.relative_to(ctx.workdir)
        except ValueError:
            rel = Path(target.name)
        diff_text = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )

        if changed:
            ctx.step()
            wrote = await _write_text(ctx, tools, target, after)
            if not wrote:
                ans = ctx.new_artifact_text(
                    "response.md",
                    f"# {self.name}\n\nFailed to write edit to `{target}`.\n",
                )
                return make_result(ctx, status="filesystem_error", answer_path=ans,
                                   metadata={"program": self.name})

        # Prefer the git_diff atomic tool for an authoritative diff; fall back
        # to our difflib-generated patch when git/the tool is unavailable.
        ok, dres = await try_tool(ctx, tools, "git_diff", {})
        if ok and dres is not None and dres.ok and isinstance(dres.data, dict):
            gd = dres.data.get("diff")
            if isinstance(gd, str) and gd.strip():
                diff_text = gd

        patch_path = ctx.new_artifact_text(PATCH_DIFF, diff_text or "")
        ctx.trajectory.log_artifact(PATCH_DIFF, patch_path, kind="diff")

        body = (
            f"# {self.name}\n\n"
            f"Edited `{rel}`: replaced {match_count} occurrence(s) of "
            f"`{find}` with `{replace}`.\n\n"
            f"Diff written to `{PATCH_DIFF}` "
            f"({'non-empty' if diff_text.strip() else 'empty -- no change'}).\n"
        )
        answer_path = ctx.new_artifact_text("response.md", body)
        ctx.trajectory.log_step(1, phase="done")

        return make_result(
            ctx,
            status="success",
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "target": str(rel),
                "matches": match_count,
                "changed": changed,
                "used_git_tool": tools.has("git_diff"),
            },
        )


PROGRAM = RepoEditProgram()


def get_program() -> RepoEditProgram:
    return PROGRAM
