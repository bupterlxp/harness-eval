"""
Patch application tool for the harness scaffold: ``ApplyPatchTool``.

Applies a unified diff to the sandboxed working tree. The strategy is:

  1. ``git apply --check`` (dry run) to validate the patch cleanly applies.
  2. If the check passes, ``git apply`` to actually apply it.
  3. If ``git apply`` is unavailable / refuses (e.g. not a git repo or the
     diff is not git-formatted), fall back to ``patch -p1``.

The tool reports structured success / conflict information, records the list of
changed files, and writes the applied diff to an artifact (``patch.diff``) via
the ArtifactStore. It is DESTRUCTIVE (mutates the working tree); the write
permission check is delegated to ``ctx.permissions`` (``check_path_write``),
which enforces ``allow_destructive_fs`` confinement.

Conforms to ``_INTERFACE_SPEC.md`` section 4. Never raises to the caller;
failures are returned as ``ToolResult.fail(...)`` with an appropriate
:class:`ErrorCode`.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional, Union

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    PermissionDenied,
    ShellError,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from .base import AtomicTool, SubprocessResult, _run_subprocess

__all__ = ["ApplyPatchTool", "get_tools"]


# Match the new-file path of each hunk header in a unified diff.
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$", re.MULTILINE)
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$", re.MULTILINE)


def _max_output_bytes(ctx: RuntimeContext) -> int:
    pol = getattr(ctx, "policy", None)
    val = getattr(pol, "max_output_bytes", None)
    return int(val) if val else 200_000


def _changed_files_from_diff(diff_text: str) -> list[str]:
    """Best-effort extraction of changed file paths from a unified diff."""
    files: list[str] = []
    for _a, b in _DIFF_GIT_RE.findall(diff_text):
        if b and b not in files:
            files.append(b)
    if not files:
        for path in _PLUS_FILE_RE.findall(diff_text):
            path = path.strip()
            if path and path != "/dev/null" and path not in files:
                files.append(path)
    return files


class ApplyPatchTool(AtomicTool):
    name = "apply_patch"
    description = (
        "Apply a unified diff to the sandboxed working tree. Validates with "
        "`git apply --check`, applies with `git apply`, and falls back to "
        "`patch -p1` when git is unavailable or refuses. Returns structured "
        "success/conflict info, the list of changed files, and writes the "
        "applied diff to an artifact (`patch.diff`). Destructive: requires "
        "allow_destructive_fs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "diff": {
                "type": "string",
                "description": "Unified diff text to apply.",
            },
            "patch_file": {
                "type": "string",
                "description": "Path to a file containing the diff (alternative to 'diff').",
            },
            "repo": {
                "type": "string",
                "description": "Target directory for the patch (defaults to the workdir).",
            },
            "strip": {
                "type": "integer",
                "description": "Path strip level for the `patch` fallback (-pN, default 1).",
            },
            "reverse": {
                "type": "boolean",
                "description": "Apply the patch in reverse (revert).",
            },
            "check_only": {
                "type": "boolean",
                "description": "Only validate that the patch applies; do not modify files.",
            },
            "artifact_name": {
                "type": "string",
                "description": "Artifact name for the applied diff (default 'patch.diff').",
            },
        },
        "required": [],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "applied": {"type": "boolean"},
            "method": {"type": ["string", "null"]},
            "changed_files": {"type": "array"},
            "check_only": {"type": "boolean"},
            "artifact": {"type": ["string", "null"]},
        },
    }
    is_read_only = False
    is_destructive = True
    requires_network = False
    requires_optional_dependency = False

    # ------------------------------------------------------------------ #
    def _resolve_repo(self, ctx: RuntimeContext, args: dict) -> Path:
        raw = args.get("repo") or args.get("cwd") or args.get("path")
        if raw:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (ctx.workdir / candidate).resolve()
        else:
            candidate = ctx.workdir
        # A patch mutates files inside the repo dir: require write permission.
        return ctx.check_path_write(candidate)

    def _load_diff(self, ctx: RuntimeContext, args: dict) -> Optional[str]:
        diff = args.get("diff")
        if diff:
            return diff
        pf = args.get("patch_file")
        if pf:
            p = Path(pf)
            if not p.is_absolute():
                p = (ctx.workdir / p).resolve()
            p = ctx.check_path_read(p)
            return p.read_text(encoding="utf-8", errors="replace")
        return None

    # ------------------------------------------------------------------ #
    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        try:
            diff_text = self._load_diff(ctx, args)
        except HarnessError as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.FILESYSTEM_ERROR),
                stage="apply_patch",
            )
        if not diff_text or not diff_text.strip():
            return ToolResult.fail(
                "No diff supplied (provide 'diff' text or 'patch_file').",
                error_code=ErrorCode.TOOL_ERROR,
                stage="apply_patch",
                recoverable=False,
            )

        check_only = bool(args.get("check_only"))
        reverse = bool(args.get("reverse"))
        try:
            strip = int(args.get("strip", 1))
        except (TypeError, ValueError):
            strip = 1

        try:
            repo = self._resolve_repo(ctx, args)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=ErrorCode.PERMISSION_DENIED,
                stage="apply_patch",
                recoverable=False,
            )
        except HarnessError as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.FILESYSTEM_ERROR),
                stage="apply_patch",
            )

        changed_files = _changed_files_from_diff(diff_text)
        max_out = _max_output_bytes(ctx)

        git_ok = shutil.which("git") is not None
        patch_ok = shutil.which("patch") is not None
        if not git_ok and not patch_ok:
            return ToolResult.fail(
                "Neither `git` nor `patch` is available on PATH.",
                error_code=ErrorCode.DEPENDENCY_ERROR,
                stage="apply_patch",
                recoverable=False,
            )

        # --- Strategy 1: git apply (preferred) ------------------------- #
        git_check_stderr = ""
        if git_ok:
            check_cmd = ["git", "apply", "--check", "--verbose"]
            if reverse:
                check_cmd.append("--reverse")
            res = self._spawn(ctx, check_cmd, repo, max_out, input_text=diff_text)
            if isinstance(res, ToolResult):
                return res  # timeout / shell error already structured
            git_check_stderr = res.stderr
            if res.returncode == 0:
                if check_only:
                    return self._success(
                        ctx, args, diff_text, changed_files,
                        method="git", applied=False, check_only=True,
                        elapsed=res.elapsed_seconds,
                    )
                apply_cmd = ["git", "apply", "--verbose"]
                if reverse:
                    apply_cmd.append("--reverse")
                ares = self._spawn(ctx, apply_cmd, repo, max_out, input_text=diff_text)
                if isinstance(ares, ToolResult):
                    return ares
                if ares.returncode == 0:
                    return self._success(
                        ctx, args, diff_text, changed_files,
                        method="git", applied=True, check_only=False,
                        elapsed=ares.elapsed_seconds,
                    )
                # git apply reported a conflict at apply time.
                return self._conflict(
                    ctx, args, diff_text, changed_files,
                    method="git", stderr=ares.stderr,
                    returncode=ares.returncode, elapsed=ares.elapsed_seconds,
                )
            # git --check failed: fall through to patch fallback if available.

        # --- Strategy 2: patch -pN fallback ---------------------------- #
        if patch_ok:
            base_cmd = ["patch", f"-p{strip}", "--batch", "--forward"]
            if reverse:
                base_cmd.append("--reverse")
            if check_only:
                dry = base_cmd + ["--dry-run"]
                pres = self._spawn(ctx, dry, repo, max_out, input_text=diff_text)
                if isinstance(pres, ToolResult):
                    return pres
                if pres.returncode == 0:
                    return self._success(
                        ctx, args, diff_text, changed_files,
                        method="patch", applied=False, check_only=True,
                        elapsed=pres.elapsed_seconds,
                    )
                return self._conflict(
                    ctx, args, diff_text, changed_files,
                    method="patch", stderr=(pres.stderr or pres.stdout),
                    returncode=pres.returncode, elapsed=pres.elapsed_seconds,
                    git_stderr=git_check_stderr,
                )
            pres = self._spawn(ctx, base_cmd, repo, max_out, input_text=diff_text)
            if isinstance(pres, ToolResult):
                return pres
            if pres.returncode == 0:
                return self._success(
                    ctx, args, diff_text, changed_files,
                    method="patch", applied=True, check_only=False,
                    elapsed=pres.elapsed_seconds,
                )
            return self._conflict(
                ctx, args, diff_text, changed_files,
                method="patch", stderr=(pres.stderr or pres.stdout),
                returncode=pres.returncode, elapsed=pres.elapsed_seconds,
                git_stderr=git_check_stderr,
            )

        # git was present but --check failed, and no patch fallback exists.
        return self._conflict(
            ctx, args, diff_text, changed_files,
            method="git", stderr=git_check_stderr,
            returncode=1, elapsed=0.0,
        )

    # ------------------------------------------------------------------ #
    def _spawn(
        self, ctx, cmd, repo, max_out, *, input_text
    ) -> Union[SubprocessResult, ToolResult]:
        """Run a subprocess, returning SubprocessResult or a failure ToolResult."""
        try:
            return _run_subprocess(
                cmd,
                ctx=ctx,
                cwd=repo,
                max_output_bytes=max_out,
                input_text=input_text,
            )
        except TimeoutErrorH as exc:
            return ToolResult.fail(
                exc.to_dict(elapsed_seconds=getattr(exc, "elapsed_seconds", 0.0)),
                error_code=ErrorCode.TIMEOUT,
                stage="apply_patch",
                recoverable=True,
            )
        except (ShellError, HarnessError) as exc:
            return ToolResult.fail(
                exc.to_dict(),
                error_code=getattr(exc, "error_code", ErrorCode.SHELL_ERROR),
                stage="apply_patch",
            )

    def _write_artifact(self, ctx, args, diff_text):
        art_name = args.get("artifact_name") or "patch.diff"
        try:
            path = ctx.new_artifact_text(art_name, diff_text, kind="diff")
            return art_name, path
        except HarnessError:
            return art_name, None

    def _success(self, ctx, args, diff_text, changed_files, *, method, applied,
                 check_only, elapsed):
        art_name, art_path = self._write_artifact(ctx, args, diff_text)
        artifacts = {art_name: art_path} if art_path else {}
        data = {
            "applied": applied,
            "method": method,
            "check_only": check_only,
            "changed_files": changed_files,
            "files_changed": len(changed_files),
            "artifact": str(art_path) if art_path else None,
            "artifact_name": art_name if art_path else None,
        }
        if check_only:
            preview = f"patch validated cleanly via {method} ({len(changed_files)} file(s))"
        else:
            preview = f"patch applied via {method}: {len(changed_files)} file(s) changed"
        return ToolResult.success(
            data=data,
            artifacts=artifacts,
            stdout_preview=preview,
            elapsed_seconds=elapsed,
            metadata={"method": method},
        )

    def _conflict(self, ctx, args, diff_text, changed_files, *, method, stderr,
                  returncode, elapsed, git_stderr=""):
        # Still persist the diff that failed so it can be inspected as evidence.
        art_name, art_path = self._write_artifact(ctx, args, diff_text)
        artifacts = {art_name: art_path} if art_path else {}
        details = {
            "method": method,
            "returncode": returncode,
            "stderr": (stderr or "")[:4000],
            "changed_files": changed_files,
        }
        if git_stderr:
            details["git_check_stderr"] = git_stderr[:2000]
        return ToolResult.fail(
            f"Patch did not apply cleanly (via {method}).",
            error_code=ErrorCode.TOOL_ERROR,
            stage="apply_patch",
            details=details,
            recoverable=False,
            artifacts=artifacts,
            stderr_preview=(stderr or "")[:1000],
            elapsed_seconds=elapsed,
            metadata={"conflict": True, "method": method},
        )


# --------------------------------------------------------------------------- #
# Discovery hook
# --------------------------------------------------------------------------- #
def get_tools() -> list[AtomicTool]:
    return [ApplyPatchTool()]
