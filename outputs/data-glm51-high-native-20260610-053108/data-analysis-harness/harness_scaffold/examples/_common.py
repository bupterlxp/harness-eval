"""Small helpers shared by the example programs.

These are deliberately tiny so each example stays readable. They only use
public scaffold symbols documented in the frozen interface spec.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult, HarnessStatus
from harness_scaffold.tools.registry import ToolRegistry


def make_result(
    ctx: RuntimeContext,
    *,
    status: HarnessStatus = "success",
    answer_path: Optional[Path] = None,
    error_path: Optional[Path] = None,
    metadata: Optional[dict] = None,
) -> HarnessResult:
    """Build a HarnessResult from the live context + artifact store.

    The runtime also synthesizes a result from the out-dir, but returning an
    explicit HarnessResult lets each example declare its own status/metadata.
    """
    return HarnessResult(
        status=status,
        answer_path=answer_path,
        artifacts=dict(ctx.artifact_store.paths()),
        trajectory_path=ctx.out_dir / "trajectory.jsonl",
        metadata_path=ctx.out_dir / "metadata.json",
        error_path=error_path,
        metadata=metadata or {},
    )


async def try_tool(
    ctx: RuntimeContext,
    tools: ToolRegistry,
    name: str,
    args: dict,
) -> "tuple[bool, Any]":
    """Run an atomic tool if it is registered.

    Returns ``(available, ToolResult|None)``. When the tool is not present in
    the registry (e.g. leaf modules not installed) we return ``(False, None)``
    and log an observation -- the caller decides how to degrade. We always go
    through ``tool.execute`` (never ``run``) so gating/timeout/logging apply.
    """
    if not tools.has(name):
        ctx.trajectory.log_observation(
            f"tool {name!r} unavailable; degrading", source="example"
        )
        return False, None
    tool = tools.get(name)
    result = await tool.execute(ctx, args)
    return True, result
