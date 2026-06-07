"""data_program -- python_exec / json_io over an input file -> metrics.

Loads a small JSON dataset from the task's first input file (or
``task.metadata['data']``), computes simple numeric metrics, and writes a
``metrics.json`` artifact plus a ``response.md`` summary.

Prefers the ``json_io`` atomic tool for reading and ``python_exec`` for
computing metrics in a sandboxed subprocess; when those leaf tools are
unavailable it degrades to stdlib ``json`` / ``statistics`` so it runs offline
with no optional deps.

Expected input shapes (any of these works):
- a JSON list of numbers:            ``[1, 2, 3, 4]``
- a JSON list of records:            ``[{"x": 1}, {"x": 2}]`` (numeric fields)
- a JSON object of named numbers:    ``{"a": 1, "b": 2}``

Run offline:
    python -m harness_scaffold.adapters.cli \
        --task-json <task.json> \
        --program harness_scaffold/examples/data_program.py \
        --out-dir /tmp/data
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import make_result, try_tool


def _input_path(ctx: RuntimeContext) -> Optional[Path]:
    meta = ctx.task.metadata or {}
    name = meta.get("data")
    if name:
        p = (ctx.workdir / name).resolve()
        if p.is_file():
            return p
    for p in ctx.task.input_files:
        p = Path(p)
        if not p.is_absolute():
            p = (ctx.workdir / p).resolve()
        if p.is_file():
            return p
    return None


async def _load_json(ctx, tools, path: Path):
    ok, res = await try_tool(ctx, tools, "json_io", {"path": str(path), "op": "read"})
    if ok and res is not None and res.ok and isinstance(res.data, dict):
        if "json" in res.data:
            return res.data["json"]
        if "content" in res.data:
            try:
                return json.loads(res.data["content"])
            except Exception:
                pass
    # stdlib fallback
    text = ctx.check_path_read(path).read_text(encoding="utf-8", errors="replace")
    return json.loads(text)


def _to_series(obj) -> "list[float]":
    """Coerce common dataset shapes into a flat numeric series."""
    out: "list[float]" = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                out.append(float(item))
            elif isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.append(float(v))
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
    return out


def _metrics(series: "list[float]") -> dict:
    if not series:
        return {"count": 0}
    m = {
        "count": len(series),
        "sum": sum(series),
        "min": min(series),
        "max": max(series),
        "mean": statistics.fmean(series),
    }
    if len(series) > 1:
        m["stdev"] = statistics.stdev(series)
        m["median"] = statistics.median(series)
    return m


class DataProgram:
    name: str = "data"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: "Optional[object]",
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)

        path = _input_path(ctx)
        if path is None:
            err = ctx.new_artifact_json(
                "error.json",
                {
                    "error_code": ErrorCode.FILESYSTEM_ERROR.value,
                    "message": "no input data file provided",
                    "stage": self.name,
                    "details": {"input_files": [str(p) for p in ctx.task.input_files]},
                    "recoverable": False,
                    "elapsed_seconds": 0.0,
                },
            )
            ans = ctx.new_artifact_text(
                "response.md",
                f"# {self.name}\n\nNo input data file was provided.\n",
            )
            return make_result(ctx, status="filesystem_error", answer_path=ans,
                               error_path=err, metadata={"program": self.name})

        ctx.step()
        try:
            data = await _load_json(ctx, tools, path)
        except Exception as e:  # noqa
            err = ctx.new_artifact_json(
                "error.json",
                {
                    "error_code": ErrorCode.TOOL_ERROR.value,
                    "message": f"failed to parse input: {type(e).__name__}: {e}",
                    "stage": self.name,
                    "details": {"path": str(path)},
                    "recoverable": False,
                    "elapsed_seconds": 0.0,
                },
            )
            ans = ctx.new_artifact_text(
                "response.md",
                f"# {self.name}\n\nCould not parse `{path.name}` as JSON.\n",
            )
            return make_result(ctx, status="tool_error", answer_path=ans,
                               error_path=err, metadata={"program": self.name})

        series = _to_series(data)

        # Optionally compute via the python_exec tool to demonstrate sandboxed
        # code execution; the stdlib metrics remain the source of truth so the
        # example is deterministic offline.
        metrics = _metrics(series)
        snippet = (
            "import json\n"
            f"s={series!r}\n"
            "print(json.dumps({'tool_count': len(s)}))\n"
        )
        ok, pres = await try_tool(ctx, tools, "python_exec", {"code": snippet})
        if ok and pres is not None and pres.ok:
            ctx.trajectory.log_observation(
                "python_exec confirmed series length", source="python_exec"
            )

        ctx.step()
        metrics_path = ctx.new_artifact_json("metrics.json", metrics)
        ctx.trajectory.log_artifact("metrics.json", metrics_path, kind="json")

        lines = [f"# {self.name}", "", f"Source: `{path.name}`", ""]
        if metrics.get("count"):
            lines.append("| metric | value |")
            lines.append("| --- | --- |")
            for k, v in metrics.items():
                lines.append(f"| {k} | {v} |")
        else:
            lines.append("No numeric values were found in the dataset.")
        body = "\n".join(lines) + "\n"
        answer_path = ctx.new_artifact_text("response.md", body)
        ctx.trajectory.log_step(1, phase="done")

        return make_result(
            ctx,
            status="success",
            answer_path=answer_path,
            metadata={
                "program": self.name,
                "metrics": metrics,
                "used_python_exec": tools.has("python_exec"),
                "used_json_io": tools.has("json_io"),
            },
        )


PROGRAM = DataProgram()


def get_program() -> DataProgram:
    return PROGRAM
