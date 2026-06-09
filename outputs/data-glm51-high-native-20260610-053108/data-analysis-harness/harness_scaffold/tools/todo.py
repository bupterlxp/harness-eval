"""TodoTool: a persisted, structured task list for a HarnessProgram.

The list is durable: it is stored as an artifact (``todo.json``) under the run's
``out_dir`` via :class:`~harness_scaffold.core.artifacts.ArtifactStore`, so the
manifest stays accurate and writes stay confined to the sandbox.

Operations (``action``):
  - ``add``      -> append a new item (status ``pending``)
  - ``update``   -> change an item's ``content``, ``status`` and/or ``priority``
  - ``complete`` -> shorthand for setting an item's status to ``completed``
  - ``list``     -> return the current list (read-only)

Statuses: ``pending``, ``in_progress``, ``completed``, ``cancelled``.

This tool never prints to stdout, never raises to the caller (it returns
``ToolResult.fail(...)`` with a structured error), and performs no network or
subprocess work.
"""
from __future__ import annotations

import time
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ArtifactError, ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool

TODO_ARTIFACT_NAME = "todo.json"

VALID_STATUSES = ("pending", "in_progress", "completed", "cancelled")
VALID_PRIORITIES = ("low", "medium", "high")


def _now() -> float:
    return time.time()


class TodoTool(AtomicTool):
    name = "todo"
    description = (
        "Maintain a persisted, structured task list for the current run. "
        "Supports add / update / complete / list. The list is stored durably "
        "as the 'todo.json' artifact under the run out_dir."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "update", "complete", "list"],
                "description": "Operation to perform.",
            },
            "id": {
                "type": "string",
                "description": "Target item id (required for update/complete).",
            },
            "content": {
                "type": "string",
                "description": "Item text (required for add; optional for update).",
            },
            "status": {
                "type": "string",
                "enum": list(VALID_STATUSES),
                "description": "Item status (optional for add/update).",
            },
            "priority": {
                "type": "string",
                "enum": list(VALID_PRIORITIES),
                "description": "Item priority (optional).",
            },
        },
        "required": ["action"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "object"}},
            "item": {"type": "object"},
            "count": {"type": "integer"},
            "summary": {"type": "object"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    # ----- persistence helpers -----
    def _load(self, ctx: RuntimeContext) -> list[dict]:
        """Load the persisted todo list from the out_dir artifact, if present."""
        path = ctx.out_dir / TODO_ARTIFACT_NAME
        if not path.exists():
            return []
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt or partial state: start fresh rather than crash the run.
            return []
        items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []
        return [dict(x) for x in items if isinstance(x, dict)]

    def _save(self, ctx: RuntimeContext, items: list[dict]) -> None:
        payload = {
            "items": items,
            "count": len(items),
            "updated_at": _now(),
        }
        # put_json registers the artifact and updates the manifest.
        ctx.artifact_store.put_json(TODO_ARTIFACT_NAME, payload, kind="json")

    @staticmethod
    def _summary(items: list[dict]) -> dict:
        summary = {s: 0 for s in VALID_STATUSES}
        for it in items:
            st = it.get("status", "pending")
            summary[st] = summary.get(st, 0) + 1
        return summary

    @staticmethod
    def _next_id(items: list[dict]) -> str:
        max_n = 0
        for it in items:
            ident = str(it.get("id", ""))
            if ident.isdigit():
                max_n = max(max_n, int(ident))
        return str(max_n + 1)

    @staticmethod
    def _find(items: list[dict], ident: str) -> dict | None:
        for it in items:
            if str(it.get("id")) == str(ident):
                return it
        return None

    # ----- main entry point -----
    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        action = (args.get("action") or "").strip().lower()
        if action not in ("add", "update", "complete", "list"):
            return ToolResult.fail(
                f"unknown todo action: {action!r}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="todo",
            )

        items = self._load(ctx)

        if action == "list":
            return ToolResult.success(
                data={
                    "items": items,
                    "count": len(items),
                    "summary": self._summary(items),
                },
                stdout_preview=f"{len(items)} todo item(s)",
            )

        if action == "add":
            content = args.get("content")
            if not isinstance(content, str) or not content.strip():
                return ToolResult.fail(
                    "add requires a non-empty 'content' string",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="todo",
                )
            status = args.get("status") or "pending"
            if status not in VALID_STATUSES:
                return ToolResult.fail(
                    f"invalid status {status!r}; expected one of {VALID_STATUSES}",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="todo",
                )
            priority = args.get("priority") or "medium"
            if priority not in VALID_PRIORITIES:
                return ToolResult.fail(
                    f"invalid priority {priority!r}; expected one of {VALID_PRIORITIES}",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="todo",
                )
            item = {
                "id": self._next_id(items),
                "content": content.strip(),
                "status": status,
                "priority": priority,
                "created_at": _now(),
                "updated_at": _now(),
            }
            items.append(item)

        elif action in ("update", "complete"):
            ident = args.get("id")
            if ident is None or str(ident) == "":
                return ToolResult.fail(
                    f"{action} requires an item 'id'",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="todo",
                )
            item = self._find(items, str(ident))
            if item is None:
                return ToolResult.fail(
                    f"todo item not found: id={ident!r}",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="todo",
                )
            if action == "complete":
                item["status"] = "completed"
            else:
                if "content" in args and isinstance(args["content"], str):
                    item["content"] = args["content"].strip()
                if "status" in args and args["status"] is not None:
                    if args["status"] not in VALID_STATUSES:
                        return ToolResult.fail(
                            f"invalid status {args['status']!r}; expected one of "
                            f"{VALID_STATUSES}",
                            error_code=ErrorCode.TOOL_ERROR,
                            stage="todo",
                        )
                    item["status"] = args["status"]
                if "priority" in args and args["priority"] is not None:
                    if args["priority"] not in VALID_PRIORITIES:
                        return ToolResult.fail(
                            f"invalid priority {args['priority']!r}; expected one of "
                            f"{VALID_PRIORITIES}",
                            error_code=ErrorCode.TOOL_ERROR,
                            stage="todo",
                        )
                    item["priority"] = args["priority"]
            item["updated_at"] = _now()

        # Persist mutated state.
        try:
            self._save(ctx, items)
        except ArtifactError as exc:
            return ToolResult.fail(
                str(exc),
                error_code=ErrorCode.ARTIFACT_ERROR,
                stage="todo",
            )

        artifacts = {}
        stored = ctx.artifact_store.get(TODO_ARTIFACT_NAME)
        if stored is not None:
            artifacts[TODO_ARTIFACT_NAME] = stored

        return ToolResult.success(
            data={
                "item": item,
                "items": items,
                "count": len(items),
                "summary": self._summary(items),
            },
            artifacts=artifacts,
            stdout_preview=f"todo {action}: id={item.get('id')} "
            f"status={item.get('status')}",
        )


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return the tool instances defined in this module."""
    return [TodoTool()]
