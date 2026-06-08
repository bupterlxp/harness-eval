"""minimal_agent_program -- trivial no-LLM program proving the contract.

The smallest possible HarnessProgram. It takes the task prompt, writes a
``response.md`` artifact, logs a couple of trajectory events, and returns a
``HarnessResult``. No tools, no LLM, no network, no optional deps.

Run:
    python -m harness_scaffold.adapters.cli \
        --task-json <task.json> \
        --program harness_scaffold/examples/minimal_agent_program.py \
        --out-dir /tmp/min
"""
from __future__ import annotations

from typing import Optional

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import HarnessResult
from harness_scaffold.tools.registry import ToolRegistry
from harness_scaffold.examples._common import make_result


class MinimalAgentProgram:
    name: str = "minimal_agent"

    async def run(
        self,
        ctx: RuntimeContext,
        tools: ToolRegistry,
        llm: "Optional[object]",
    ) -> HarnessResult:
        ctx.trajectory.log_step(0, phase="start", note=self.name)
        ctx.check_abort(stage="minimal")

        prompt = ctx.task.prompt or "(empty prompt)"
        body = (
            f"# {self.name}\n\n"
            f"Task id: `{ctx.task.task_id}`\n\n"
            "This minimal program does not call any tool or LLM. It simply "
            "echoes the prompt to prove the harness contract end to end.\n\n"
            "## Prompt\n\n"
            f"{prompt}\n"
        )
        answer_path = ctx.new_artifact_text("response.md", body)
        ctx.trajectory.log_step(1, phase="done")

        return make_result(
            ctx,
            status="success",
            answer_path=answer_path,
            metadata={"program": self.name, "used_llm": False, "used_tools": False},
        )


PROGRAM = MinimalAgentProgram()


def get_program() -> MinimalAgentProgram:
    return PROGRAM
