"""ArtifactTool: a tool wrapper around the run's ArtifactStore.

Lets a HarnessProgram (or a model driving it) persist durable outputs -- the
final ``response.md``, reports, metrics, or arbitrary text/json/binary blobs --
into the run's ``out_dir`` and keep the manifest (``artifacts.json``) accurate.

All writes go through :class:`~harness_scaffold.core.artifacts.ArtifactStore`,
which confines names to ``out_dir`` and enforces ``max_artifact_bytes``.

Operations (``action``):
  - ``response`` -> write the final answer markdown to ``response.md``
  - ``put_text`` -> write a text artifact (``name`` + ``content``)
  - ``put_json`` -> write a json artifact (``name`` + ``obj``)
  - ``put_bytes``-> write a binary artifact (``name`` + base64 ``content_b64``)
  - ``copy``     -> copy an existing in-sandbox file into the store (``name`` + ``src``)
  - ``manifest`` -> write/return the manifest (read-mostly)
  - ``list``     -> return current artifact names/paths (read-only)

The tool never prints to stdout, never raises to the caller, and runs no
subprocess or network operation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import (
    ArtifactError,
    ErrorCode,
    FilesystemError,
    PermissionDenied,
)
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool

RESPONSE_NAME = "response.md"


class ArtifactTool(AtomicTool):
    name = "artifact"
    description = (
        "Persist durable outputs (response.md, reports, metrics, arbitrary "
        "text/json/binary blobs) into the run out_dir and keep artifacts.json "
        "up to date. Writes are confined to the sandbox and size-bounded."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "response",
                    "put_text",
                    "put_json",
                    "put_bytes",
                    "copy",
                    "manifest",
                    "list",
                ],
                "description": "Operation to perform.",
            },
            "name": {
                "type": "string",
                "description": "Artifact name (may include subdirs). Required for "
                "put_*/copy.",
            },
            "content": {
                "type": "string",
                "description": "Text content (put_text) or base64 content (put_bytes).",
            },
            "obj": {
                "description": "JSON-serialisable object (put_json).",
            },
            "src": {
                "type": "string",
                "description": "Source file path to copy from (copy).",
            },
            "kind": {
                "type": "string",
                "description": "Optional artifact kind label.",
            },
        },
        "required": ["action"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "path": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "manifest": {"type": "object"},
            "artifacts": {"type": "object"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    def _registered(self, ctx: RuntimeContext, name: str, path: Path) -> dict:
        """Build a small success payload and refresh the manifest on disk."""
        rec = ctx.artifact_store.manifest().get("artifacts", {}).get(name, {})
        try:
            ctx.artifact_store.write_manifest()
        except Exception:
            # Manifest write failure should not nullify a successful artifact write;
            # it will be re-written at run teardown by the runtime.
            pass
        return {
            "name": name,
            "path": str(path),
            "size_bytes": rec.get("size_bytes"),
            "kind": rec.get("kind"),
        }

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        action = (args.get("action") or "").strip().lower()

        try:
            if action == "list":
                paths = {n: str(p) for n, p in ctx.artifact_store.paths().items()}
                return ToolResult.success(
                    data={"artifacts": paths, "count": len(paths)},
                    stdout_preview=f"{len(paths)} artifact(s)",
                )

            if action == "manifest":
                manifest = ctx.artifact_store.manifest()
                path = ctx.artifact_store.write_manifest()
                return ToolResult.success(
                    data={"manifest": manifest},
                    artifacts={"artifacts.json": path},
                    stdout_preview=f"manifest: {manifest.get('count', 0)} artifact(s)",
                )

            if action == "response":
                content = args.get("content")
                if not isinstance(content, str):
                    return ToolResult.fail(
                        "response requires 'content' (markdown string)",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                path = ctx.artifact_store.put_text(
                    RESPONSE_NAME, content, kind=args.get("kind") or "markdown"
                )
                payload = self._registered(ctx, RESPONSE_NAME, path)
                return ToolResult.success(
                    data=payload,
                    artifacts={RESPONSE_NAME: path},
                    stdout_preview=f"wrote {RESPONSE_NAME} ({payload.get('size_bytes')} bytes)",
                )

            if action == "put_text":
                name = args.get("name")
                content = args.get("content")
                if not name or not isinstance(content, str):
                    return ToolResult.fail(
                        "put_text requires 'name' and string 'content'",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                path = ctx.artifact_store.put_text(
                    name, content, kind=args.get("kind") or "text"
                )
                payload = self._registered(ctx, name, path)
                return ToolResult.success(
                    data=payload,
                    artifacts={name: path},
                    stdout_preview=f"wrote {name} ({payload.get('size_bytes')} bytes)",
                )

            if action == "put_json":
                name = args.get("name")
                if not name or "obj" not in args:
                    return ToolResult.fail(
                        "put_json requires 'name' and 'obj'",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                path = ctx.artifact_store.put_json(
                    name, args["obj"], kind=args.get("kind") or "json"
                )
                payload = self._registered(ctx, name, path)
                return ToolResult.success(
                    data=payload,
                    artifacts={name: path},
                    stdout_preview=f"wrote {name} ({payload.get('size_bytes')} bytes)",
                )

            if action == "put_bytes":
                name = args.get("name")
                b64 = args.get("content")
                if not name or not isinstance(b64, str):
                    return ToolResult.fail(
                        "put_bytes requires 'name' and base64 'content'",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                import base64

                try:
                    raw = base64.b64decode(b64, validate=True)
                except Exception as exc:
                    return ToolResult.fail(
                        f"put_bytes: invalid base64 content: {exc}",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                path = ctx.artifact_store.put_bytes(
                    name, raw, kind=args.get("kind") or "binary"
                )
                payload = self._registered(ctx, name, path)
                return ToolResult.success(
                    data=payload,
                    artifacts={name: path},
                    stdout_preview=f"wrote {name} ({payload.get('size_bytes')} bytes)",
                )

            if action == "copy":
                name = args.get("name")
                src = args.get("src")
                if not name or not src:
                    return ToolResult.fail(
                        "copy requires 'name' and 'src'",
                        error_code=ErrorCode.TOOL_ERROR,
                        stage="artifact",
                    )
                # Confine the source read to the sandbox.
                src_path = ctx.check_path_read(Path(src))
                path = ctx.artifact_store.put_file(
                    name, src_path, kind=args.get("kind") or "file"
                )
                payload = self._registered(ctx, name, path)
                return ToolResult.success(
                    data=payload,
                    artifacts={name: path},
                    stdout_preview=f"copied {src} -> {name}",
                )

            return ToolResult.fail(
                f"unknown artifact action: {action!r}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="artifact",
            )

        except PermissionDenied as exc:
            return ToolResult.fail(
                str(exc), error_code=ErrorCode.PERMISSION_DENIED, stage="artifact"
            )
        except ArtifactError as exc:
            return ToolResult.fail(
                str(exc), error_code=ErrorCode.ARTIFACT_ERROR, stage="artifact"
            )
        except FilesystemError as exc:
            return ToolResult.fail(
                str(exc), error_code=ErrorCode.FILESYSTEM_ERROR, stage="artifact"
            )
        except OSError as exc:
            return ToolResult.fail(
                f"artifact io error: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="artifact",
            )


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return the tool instances defined in this module."""
    return [ArtifactTool()]
