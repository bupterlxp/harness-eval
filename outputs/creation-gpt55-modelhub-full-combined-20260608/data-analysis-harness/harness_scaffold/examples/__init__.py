"""Example HarnessProgram modules.

Each module is a SMALL, self-contained demo of *composing* the generic
harness scaffold -- not a fixed domain base class. Every module exposes a
module-level ``PROGRAM`` (and ``get_program()``) so the CLI can load it:

    python -m harness_scaffold.adapters.cli \
        --task-json task.json \
        --program harness_scaffold/examples/minimal_agent_program.py \
        --out-dir /tmp/out

The programs are written to run WITHOUT network and WITHOUT optional
dependencies wherever possible. When a required atomic tool or optional
dependency is unavailable they degrade to a *structured* result (an error
artifact / refusal) rather than crashing -- exercising the same failure
taxonomy the runtime uses.

Available example programs:

- ``minimal_agent_program``  trivial no-LLM program proving the contract.
- ``repo_edit_program``      file / grep / edit / patch + git diff -> patch.diff.
- ``data_program``           python_exec / json_io over an input file -> metrics.
- ``writing_program``        LLM (or mock) draft+revise -> response + revisions.
- ``research_program``       web_fetch / web_search / evidence, refuses fabrication.
- ``browser_program``        BrowserTool observe-act loop over local HTML.
"""
from __future__ import annotations

__all__ = [
    "minimal_agent_program",
    "repo_edit_program",
    "data_program",
    "writing_program",
    "research_program",
    "browser_program",
]
