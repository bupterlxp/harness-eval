from __future__ import annotations

import time
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


TASK_GRAPH_ARTIFACT = "task_graph.json"
VALID_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}


class TaskGraphTool(AtomicTool):
    name = "task_graph"
    description = "Maintain a durable task graph with status, dependencies, blockers, owner, and metadata."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "update", "complete", "block", "list"]},
            "id": {"type": "string"},
            "content": {"type": "string"},
            "status": {"type": "string", "enum": sorted(VALID_STATUSES)},
            "owner": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "blocks": {"type": "array", "items": {"type": "string"}},
            "metadata": {"type": "object"},
        },
        "required": ["action"],
    }
    output_schema = {"type": "object"}
    is_read_only = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        graph = self._load(ctx)
        if action == "list":
            return ToolResult.success({"tasks": graph, "count": len(graph), "summary": self._summary(graph)})
        if action == "add":
            content = str(args.get("content") or "").strip()
            if not content:
                return ToolResult.fail("task_graph add requires non-empty content", error_code=ErrorCode.TOOL_ERROR, stage="task_graph")
            item = {
                "id": str(args.get("id") or self._next_id(graph)),
                "content": content,
                "status": str(args.get("status") or "pending"),
                "owner": str(args.get("owner") or ""),
                "depends_on": list(args.get("depends_on") or []),
                "blocks": list(args.get("blocks") or []),
                "metadata": dict(args.get("metadata") or {}),
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            if item["status"] not in VALID_STATUSES:
                return ToolResult.fail(f"invalid status: {item['status']}", error_code=ErrorCode.TOOL_ERROR, stage="task_graph")
            graph = [task for task in graph if task.get("id") != item["id"]] + [item]
        elif action in {"update", "complete", "block"}:
            ident = str(args.get("id") or "")
            item = next((task for task in graph if str(task.get("id")) == ident), None)
            if item is None:
                return ToolResult.fail(f"task not found: {ident}", error_code=ErrorCode.TOOL_ERROR, stage="task_graph")
            if action == "complete":
                item["status"] = "completed"
            elif action == "block":
                item["status"] = "blocked"
            else:
                for key in ("content", "owner"):
                    if key in args and args[key] is not None:
                        item[key] = args[key]
                if args.get("status") is not None:
                    if args["status"] not in VALID_STATUSES:
                        return ToolResult.fail(f"invalid status: {args['status']}", error_code=ErrorCode.TOOL_ERROR, stage="task_graph")
                    item["status"] = args["status"]
                for key in ("depends_on", "blocks"):
                    if args.get(key) is not None:
                        item[key] = list(args[key])
                if isinstance(args.get("metadata"), dict):
                    item.setdefault("metadata", {}).update(args["metadata"])
            item["updated_at"] = time.time()
        else:
            return ToolResult.fail(f"unknown task_graph action: {action}", error_code=ErrorCode.TOOL_ERROR, stage="task_graph")

        path = ctx.artifact_store.put_json(TASK_GRAPH_ARTIFACT, {"tasks": graph, "summary": self._summary(graph)}, kind="json")
        return ToolResult.success({"tasks": graph, "count": len(graph), "summary": self._summary(graph)}, artifacts={"task_graph": path})

    def _load(self, ctx: RuntimeContext) -> list[dict[str, Any]]:
        path = ctx.out_dir / TASK_GRAPH_ARTIFACT
        if not path.exists():
            return []
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            tasks = payload.get("tasks", payload)
            return [dict(item) for item in tasks if isinstance(item, dict)] if isinstance(tasks, list) else []
        except Exception:
            return []

    @staticmethod
    def _next_id(tasks: list[dict[str, Any]]) -> str:
        nums = [int(str(task.get("id"))) for task in tasks if str(task.get("id", "")).isdigit()]
        return str(max(nums, default=0) + 1)

    @staticmethod
    def _summary(tasks: list[dict[str, Any]]) -> dict[str, int]:
        summary = {status: 0 for status in VALID_STATUSES}
        for task in tasks:
            status = str(task.get("status") or "pending")
            summary[status] = summary.get(status, 0) + 1
        return summary


def get_tools() -> list[AtomicTool]:
    return [TaskGraphTool()]
