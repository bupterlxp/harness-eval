"""notebook leaf tool (optional): read/edit Jupyter .ipynb cells (stdlib only).

A .ipynb is JSON, so this needs no third-party deps. It supports reading the
notebook's cells and editing a cell's source by index. It is registered as
"optional" only because notebooks are a niche capability, not because it needs
an external dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode
from ..core.schemas import ToolResult
from .base import AtomicTool


def _load_nb(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else str(src)


class NotebookTool(AtomicTool):
    name = "notebook"
    description = (
        "Read or edit a Jupyter .ipynb notebook in the sandbox. action='read' "
        "returns the list of cells (type + source); action='edit' replaces the "
        "source of the cell at 'index' with 'new_source'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "edit"]},
            "path": {"type": "string"},
            "index": {"type": "integer"},
            "new_source": {"type": "string"},
        },
        "required": ["action", "path"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "cells": {"type": "array"},
            "num_cells": {"type": "integer"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        action = str(args["action"])
        if action == "read":
            path = ctx.check_path_read(Path(args["path"]))
        else:
            path = ctx.check_path_write(Path(args["path"]))
        if not path.exists():
            return ToolResult.fail(
                f"notebook not found: {path}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
            )
        try:
            nb = _load_nb(path)
        except (OSError, json.JSONDecodeError) as exc:
            return ToolResult.fail(
                f"failed to parse notebook {path}: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        cells = nb.get("cells", [])

        if action == "read":
            out = [
                {"index": i, "cell_type": c.get("cell_type"), "source": _cell_source(c)}
                for i, c in enumerate(cells)
            ]
            return ToolResult.success(
                data={"cells": out, "num_cells": len(out)},
                stdout_preview="\n".join(f"[{c['index']}] {c['cell_type']}" for c in out)[:1000],
            )

        if action == "edit":
            if not ctx.policy.allow_destructive_fs and path.exists():
                return ToolResult.fail(
                    f"editing existing notebook disabled by policy: {path}",
                    error_code=ErrorCode.PERMISSION_DENIED,
                    stage=f"tool:{self.name}",
                )
            index = args.get("index")
            if index is None or "new_source" not in args:
                return ToolResult.fail(
                    "edit requires 'index' and 'new_source'",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                )
            index = int(index)
            if not (0 <= index < len(cells)):
                return ToolResult.fail(
                    f"cell index {index} out of range (0..{len(cells) - 1})",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                )
            cells[index]["source"] = str(args["new_source"])
            try:
                path.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
            except OSError as exc:
                return ToolResult.fail(
                    f"failed to write notebook {path}: {exc}",
                    error_code=ErrorCode.FILESYSTEM_ERROR,
                    stage=f"tool:{self.name}",
                )
            return ToolResult.success(
                data={"num_cells": len(cells), "edited_index": index},
                stdout_preview=f"edited cell {index} in {path}",
            )

        return ToolResult.fail(
            f"unknown action: {action!r}",
            error_code=ErrorCode.TOOL_ERROR,
            stage=f"tool:{self.name}",
        )


def get_tools() -> list[AtomicTool]:
    return [NotebookTool()]
