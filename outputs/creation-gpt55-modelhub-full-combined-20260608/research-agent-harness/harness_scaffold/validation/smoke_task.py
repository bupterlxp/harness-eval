"""End-to-end smoke: a trivial task + no-op program, run with no network.

Used by tests and by the CLI's self-check. Asserts the out-dir contract files
exist after a run. No third-party imports; no network.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Optional

from ..core.runtime import HarnessRuntime
from ..core.schemas import HarnessResult, HarnessTask, RuntimePolicy


class _SmokeProgram:
    name = "smoke_program"

    async def run(self, ctx: Any, tools: Any, llm: Any) -> HarnessResult:
        ctx.step()
        ctx.new_artifact_text("response.md", "# Smoke OK\n\nThe scaffold runtime works.\n")
        ctx.new_artifact_json("smoke.json", {"ok": True, "tools": tools.names()})
        ctx.trajectory.log_info("smoke_done")
        return HarnessResult(
            status="success",
            answer_path=ctx.out_dir / "response.md",
            artifacts={},
            trajectory_path=ctx.out_dir / "trajectory.jsonl",
            metadata_path=ctx.out_dir / "metadata.json",
            error_path=None,
            metadata={},
        )


def run_smoke(out_dir: Optional[Path] = None, *, workdir: Optional[Path] = None) -> dict[str, Any]:
    """Run the smoke task end-to-end and return a structured report."""
    tmp_root: Optional[tempfile.TemporaryDirectory[str]] = None
    if out_dir is None:
        tmp_root = tempfile.TemporaryDirectory(prefix="harness_smoke_")
        out_dir = Path(tmp_root.name) / "out"
    wd = Path(workdir) if workdir else Path(out_dir).parent
    wd.mkdir(parents=True, exist_ok=True)

    from ..tools.registry import default_registry

    task = HarnessTask(task_id="smoke", prompt="smoke", workdir=wd)
    policy = RuntimePolicy(allow_network=False)
    runtime = HarnessRuntime(tools=default_registry(), llm=None, policy=policy)
    result = runtime.run_sync(task, _SmokeProgram(), Path(out_dir))

    expected = ["response.md", "trajectory.jsonl", "metadata.json", "artifacts.json"]
    present = {name: (Path(out_dir) / name).exists() for name in expected}
    report = {
        "ok": result.status == "success" and all(present.values()),
        "status": result.status,
        "out_dir": str(out_dir),
        "files_present": present,
    }
    # Keep tmp dir alive until the caller reads files if they passed no out_dir.
    if tmp_root is not None:
        report["_tmp"] = tmp_root  # caller may keep reference
    return report
