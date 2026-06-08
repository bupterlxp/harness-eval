from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


class CheckpointTool(AtomicTool):
    name = "checkpoint"
    description = "Create/list/rollback workspace checkpoints under the run output directory."
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "rollback"]},
            "name": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["action"],
    }
    output_schema = {"type": "object"}
    is_read_only = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        root = ctx.out_dir / "checkpoints"
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "manifest.json"
        manifest = self._load_manifest(manifest_path)
        if action == "list":
            return ToolResult.success({"checkpoints": manifest})
        name = str(args.get("name") or f"cp_{int(time.time())}").strip()
        if not name or "/" in name or ".." in name:
            return ToolResult.fail("checkpoint name must be a simple relative name", error_code=ErrorCode.TOOL_ERROR, stage="checkpoint")
        target = root / name
        if action == "create":
            if target.exists():
                shutil.rmtree(target)
            ignore = shutil.ignore_patterns(".git", "__pycache__", ".venv", "venv", "node_modules")
            shutil.copytree(ctx.workdir, target, ignore=ignore)
            entry = {"name": name, "path": str(target), "created_at": time.time(), "note": str(args.get("note") or "")}
            manifest = [item for item in manifest if item.get("name") != name] + [entry]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            return ToolResult.success(entry, artifacts={"checkpoint_manifest": manifest_path})
        if action == "rollback":
            if not target.exists():
                return ToolResult.fail(f"checkpoint not found: {name}", error_code=ErrorCode.TOOL_ERROR, stage="checkpoint")
            for item in ctx.workdir.iterdir():
                if item.name in {".git", "__pycache__"}:
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            for item in target.iterdir():
                dest = ctx.workdir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            return ToolResult.success({"rolled_back_to": name})
        return ToolResult.fail(f"unknown checkpoint action: {action}", error_code=ErrorCode.TOOL_ERROR, stage="checkpoint")

    @staticmethod
    def _load_manifest(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [dict(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
        except Exception:
            return []


def get_tools() -> list[AtomicTool]:
    return [CheckpointTool()]
