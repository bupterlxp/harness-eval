from __future__ import annotations

from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


class ContextCompactorTool(AtomicTool):
    name = "context_compactor"
    description = "Deterministically compact long text or trajectory logs within a character budget."
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "path": {"type": "string"},
            "max_chars": {"type": "integer"},
            "keep_head_chars": {"type": "integer"},
            "keep_tail_chars": {"type": "integer"},
            "artifact_name": {"type": "string"},
        },
    }
    output_schema = {"type": "object"}
    is_read_only = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        text = args.get("text")
        source = ""
        if text is None and args.get("path"):
            path = ctx.check_path_read(Path(str(args["path"])))
            source = str(path)
            text = path.read_text(encoding="utf-8", errors="replace")
        if text is None:
            return ToolResult.fail("context_compactor requires text or path", error_code=ErrorCode.TOOL_ERROR, stage="context_compactor")
        text = str(text)
        max_chars = max(100, int(args.get("max_chars") or 8000))
        head = max(0, int(args.get("keep_head_chars") or max_chars // 3))
        tail = max(0, int(args.get("keep_tail_chars") or max_chars - head - 200))
        compacted = self._compact(text, max_chars=max_chars, head=head, tail=tail)
        artifact_name = str(args.get("artifact_name") or "compacted_context.md")
        artifact = ctx.artifact_store.put_text(artifact_name, compacted, kind="context")
        return ToolResult.success(
            {"source": source, "original_chars": len(text), "compacted_chars": len(compacted), "artifact": str(artifact)},
            artifacts={"compacted_context": artifact},
            stdout_preview=compacted[:1000],
        )

    @staticmethod
    def _compact(text: str, *, max_chars: int, head: int, tail: int) -> str:
        if len(text) <= max_chars:
            return text
        omitted = len(text) - head - tail
        return text[:head] + f"\n\n...[compacted {omitted} chars]...\n\n" + text[-tail:]


def get_tools() -> list[AtomicTool]:
    return [ContextCompactorTool()]
