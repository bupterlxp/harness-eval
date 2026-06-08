"""
Git tools for the harness scaffold: ``GitStatusTool`` and ``GitDiffTool``.

Both tools are READ-ONLY: they never mutate the repository. They shell out to
the system ``git`` binary via the sanctioned ``_run_subprocess`` helper (which
provides process-group cleanup, hard timeout, and output truncation) and
translate results into structured :class:`ToolResult` values.

  - ``GitStatusTool``  : ``git status --porcelain`` -> parsed list of changed files.
  - ``GitDiffTool``    : ``git diff`` (optionally ``--staged`` and/or path-scoped)
                          -> writes the diff to an artifact (``patch.diff``) via the
                          ArtifactStore and returns a summary + artifact path
                          (the full diff is NOT placed on stdout).

Conforms to ``_INTERFACE_SPEC.md`` section 4. Neither tool ever raises to the
caller; failures are returned as ``ToolResult.fail(...)`` with an appropriate
:class:`ErrorCode`.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, HarnessError, ShellError, TimeoutErrorH
from ..core.schemas import ToolResult
from .base import AtomicTool, SubprocessResult, _run_subprocess

__all__ = ["GitStatusTool", "GitDiffTool", "get_tools"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _resolve_repo_dir(ctx: RuntimeContext, args: dict) -> Path:
    """Resolve and permission-check the repository working directory.

    A caller may pass an explicit ``repo``/``cwd``/``path`` argument; otherwise
    the runtime workdir is used. The path must be readable within the sandbox.
    """
    raw = args.get("repo") or args.get("cwd") or args.get("path")
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (ctx.workdir / candidate).resolve()
        return ctx.check_path_read(candidate)
    return ctx.check_path_read(ctx.workdir)


def _git_available() -> bool:
    return shutil.which("git") is not None


def _max_output_bytes(ctx: RuntimeContext) -> int:
    pol = getattr(ctx, "policy", None)
    val = getattr(pol, "max_output_bytes", None)
    return int(val) if val else 200_000


def _parse_porcelain(text: str) -> list[dict]:
    """Parse ``git status --porcelain`` (v1) output into structured records.

    Each non-empty line has the shape ``XY <path>`` where ``X`` is the staged
    (index) status and ``Y`` is the worktree status. Renames/copies appear as
    ``XY <orig> -> <new>``.
    """
    entries: list[dict] = []
    for line in text.splitlines():
        if not line:
            continue
        index_status = line[0] if len(line) > 0 else " "
        worktree_status = line[1] if len(line) > 1 else " "
        rest = line[3:] if len(line) > 3 else line[2:].lstrip()
        orig_path: Optional[str] = None
        path = rest
        if " -> " in rest:
            orig_path, path = rest.split(" -> ", 1)
        entries.append(
            {
                "index": index_status,
                "worktree": worktree_status,
                "status": (index_status + worktree_status).strip() or "?",
                "path": path.strip(),
                "orig_path": orig_path.strip() if orig_path else None,
            }
        )
    return entries


# --------------------------------------------------------------------------- #
# GitStatusTool
# --------------------------------------------------------------------------- #
class GitStatusTool(AtomicTool):
    name = "git_status"
    description = (
        "Show the working-tree status of a git repository "
        "(`git status --porcelain`) and return the list of changed files "
        "with their staged/worktree status codes. Read-only."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository directory (defaults to the workdir).",
            },
            "untracked": {
                "type": "boolean",
                "description": "Include untracked files (default true).",
            },
        },
        "required": [],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "clean": {"type": "boolean"},
            "branch": {"type": ["string", "null"]},
            "changed": {"type": "array"},
            "count": {"type": "integer"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        if not _git_available():
            return ToolResult.fail(
                "The `git` executable was not found on PATH.",
                error_code=ErrorCode.DEPENDENCY_ERROR,
                stage="git_status",
                recoverable=False,
            )
        try:
            repo = _resolve_repo_dir(ctx, args)
        except HarnessError as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.PERMISSION_DENIED),
                stage="git_status",
            )

        include_untracked = args.get("untracked", True)
        cmd = [
            "git",
            "status",
            "--porcelain",
            "--branch",
            ("--untracked-files=all" if include_untracked else "--untracked-files=no"),
        ]
        try:
            res: SubprocessResult = _run_subprocess(
                cmd,
                ctx=ctx,
                cwd=repo,
                max_output_bytes=_max_output_bytes(ctx),
            )
        except TimeoutErrorH as exc:
            return ToolResult.fail(
                exc.to_dict(elapsed_seconds=getattr(exc, "elapsed_seconds", 0.0)),
                error_code=ErrorCode.TIMEOUT,
                stage="git_status",
                recoverable=True,
            )
        except (ShellError, HarnessError) as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.SHELL_ERROR),
                stage="git_status",
            )

        if res.returncode != 0:
            return ToolResult.fail(
                res.stderr.strip() or "git status failed.",
                error_code=ErrorCode.SHELL_ERROR,
                stage="git_status",
                details={"returncode": res.returncode, "stderr": res.stderr[:2000]},
                stderr_preview=res.stderr[:1000],
                elapsed_seconds=res.elapsed_seconds,
            )

        branch: Optional[str] = None
        body_lines: list[str] = []
        for line in res.stdout.splitlines():
            if line.startswith("## "):
                # e.g. "## main...origin/main [ahead 1]"
                branch = line[3:].split("...", 1)[0].split(" ", 1)[0].strip() or None
            else:
                body_lines.append(line)
        changed = _parse_porcelain("\n".join(body_lines))

        data = {
            "clean": len(changed) == 0,
            "branch": branch,
            "changed": changed,
            "count": len(changed),
            "truncated": res.truncated,
        }
        preview_lines = [f"branch: {branch or '(unknown)'}"]
        if changed:
            preview_lines += [f"{e['status']:<2} {e['path']}" for e in changed[:50]]
            if len(changed) > 50:
                preview_lines.append(f"... ({len(changed) - 50} more)")
        else:
            preview_lines.append("(working tree clean)")
        return ToolResult.success(
            data=data,
            stdout_preview="\n".join(preview_lines),
            elapsed_seconds=res.elapsed_seconds,
            metadata={"returncode": res.returncode},
        )


# --------------------------------------------------------------------------- #
# GitDiffTool
# --------------------------------------------------------------------------- #
class GitDiffTool(AtomicTool):
    name = "git_diff"
    description = (
        "Produce a unified diff of a git repository (`git diff`, optionally "
        "`--staged` and/or scoped to paths). The full diff is written to an "
        "artifact (`patch.diff`) via the ArtifactStore; the result returns a "
        "summary and the artifact path rather than dumping the diff to stdout. "
        "Read-only."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "Repository directory (defaults to the workdir).",
            },
            "staged": {
                "type": "boolean",
                "description": "Diff the index against HEAD (`git diff --staged`).",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional pathspecs to limit the diff.",
            },
            "artifact_name": {
                "type": "string",
                "description": "Artifact name for the diff (default 'patch.diff').",
            },
        },
        "required": [],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "empty": {"type": "boolean"},
            "files_changed": {"type": "integer"},
            "insertions": {"type": "integer"},
            "deletions": {"type": "integer"},
            "artifact": {"type": ["string", "null"]},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        if not _git_available():
            return ToolResult.fail(
                "The `git` executable was not found on PATH.",
                error_code=ErrorCode.DEPENDENCY_ERROR,
                stage="git_diff",
                recoverable=False,
            )
        try:
            repo = _resolve_repo_dir(ctx, args)
        except HarnessError as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.PERMISSION_DENIED),
                stage="git_diff",
            )

        cmd = ["git", "diff"]
        if args.get("staged") or args.get("cached"):
            cmd.append("--staged")
        paths = args.get("paths") or []
        if paths:
            if not isinstance(paths, (list, tuple)):
                paths = [paths]
            cmd.append("--")
            cmd.extend(str(p) for p in paths)

        max_out = _max_output_bytes(ctx)
        # Allow the diff itself to be larger than the stdout cap, bounded by the
        # artifact byte budget so we can persist the full patch as an artifact.
        art_cap = int(getattr(ctx.policy, "max_artifact_bytes", 10_000_000) or 10_000_000)
        try:
            res: SubprocessResult = _run_subprocess(
                cmd,
                ctx=ctx,
                cwd=repo,
                max_output_bytes=max(max_out, art_cap),
            )
        except TimeoutErrorH as exc:
            return ToolResult.fail(
                exc.to_dict(elapsed_seconds=getattr(exc, "elapsed_seconds", 0.0)),
                error_code=ErrorCode.TIMEOUT,
                stage="git_diff",
                recoverable=True,
            )
        except (ShellError, HarnessError) as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.SHELL_ERROR),
                stage="git_diff",
            )

        if res.returncode not in (0, 1):
            # `git diff` normally exits 0; non-0/1 indicates a real error.
            return ToolResult.fail(
                res.stderr.strip() or "git diff failed.",
                error_code=ErrorCode.SHELL_ERROR,
                stage="git_diff",
                details={"returncode": res.returncode, "stderr": res.stderr[:2000]},
                stderr_preview=res.stderr[:1000],
                elapsed_seconds=res.elapsed_seconds,
            )

        diff_text = res.stdout
        empty = not diff_text.strip()
        lines = diff_text.splitlines()
        files_changed = sum(1 for ln in lines if ln.startswith("diff --git "))
        insertions = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
        deletions = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))

        artifact_path: Optional[Path] = None
        artifacts: dict[str, Path] = {}
        art_name = args.get("artifact_name") or "patch.diff"
        if not empty:
            try:
                artifact_path = ctx.new_artifact_text(art_name, diff_text, kind="diff")
                artifacts[art_name] = artifact_path
            except HarnessError as exc:
                return ToolResult.fail(
                    exc.to_dict(),
                    error_code=getattr(exc, "error_code", ErrorCode.ARTIFACT_ERROR),
                    stage="git_diff",
                )

        data = {
            "empty": empty,
            "files_changed": files_changed,
            "insertions": insertions,
            "deletions": deletions,
            "artifact": str(artifact_path) if artifact_path else None,
            "artifact_name": art_name if artifact_path else None,
            "truncated": res.truncated,
        }
        preview = (
            "(no changes)"
            if empty
            else (
                f"{files_changed} file(s) changed, "
                f"+{insertions}/-{deletions} -> artifact {art_name}"
            )
        )
        return ToolResult.success(
            data=data,
            artifacts=artifacts,
            stdout_preview=preview,
            elapsed_seconds=res.elapsed_seconds,
            metadata={"returncode": res.returncode},
        )


# --------------------------------------------------------------------------- #
# Discovery hook
# --------------------------------------------------------------------------- #
def get_tools() -> list[AtomicTool]:
    return [GitStatusTool(), GitDiffTool()]
