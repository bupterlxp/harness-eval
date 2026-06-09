"""lsp leaf tool (optional): lightweight Python symbol lookup.

A full Language Server Protocol client needs an external server; that is out of
scope for the stdlib core. This provides the most useful, dependency-free subset:
locate top-level Python symbol definitions (functions/classes) by name across a
sandboxed directory using the stdlib ``ast`` module. It is registered as optional
to mirror Claude Code's LSPTool slot.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode
from ..core.schemas import ToolResult
from .base import AtomicTool

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}


class LSPTool(AtomicTool):
    name = "lsp"
    description = (
        "Locate Python symbol definitions (functions, classes, methods) by name "
        "across .py files in the sandbox, using the stdlib ast module. Returns "
        "file path, line number, and kind for each match."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol name to find."},
            "path": {"type": "string", "description": "Base directory (defaults to workdir)."},
            "limit": {"type": "integer"},
        },
        "required": ["symbol"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "definitions": {"type": "array"},
            "count": {"type": "integer"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        symbol = str(args["symbol"])
        base = Path(args["path"]) if args.get("path") else ctx.workdir
        base = ctx.check_path_read(base)
        limit = int(args.get("limit", 200))

        defs = []
        files = [base] if base.is_file() else base.rglob("*.py")
        for p in files:
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.suffix != ".py" or not p.is_file():
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        kind = "class" if isinstance(node, ast.ClassDef) else "function"
                        defs.append(
                            {"path": str(p), "line": node.lineno, "kind": kind, "name": node.name}
                        )
                        if len(defs) >= limit:
                            break
            if len(defs) >= limit:
                break

        preview = "\n".join(f"{d['path']}:{d['line']} {d['kind']} {d['name']}" for d in defs[:50])
        return ToolResult.success(
            data={"definitions": defs, "count": len(defs)},
            stdout_preview=preview,
        )


def get_tools() -> list[AtomicTool]:
    return [LSPTool()]
