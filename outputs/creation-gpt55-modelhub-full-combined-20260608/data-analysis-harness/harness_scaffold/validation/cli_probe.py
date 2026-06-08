"""Subprocess-probe the CLI: run --help and a trivial smoke, with timeouts.

Asserts the CLI's real stdout is a single JSON line. Used by tests/self-check.

NO third-party imports.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

CLI_MODULE = "harness_scaffold.adapters.cli"


def probe_help(*, timeout: float = 30.0) -> dict[str, Any]:
    """Run ``python -m harness_scaffold.adapters.cli --help``; expect exit 0."""
    proc = _run([sys.executable, "-m", CLI_MODULE, "--help"], timeout=timeout)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_preview": proc.stdout[:500],
    }


def probe_smoke(
    *,
    timeout: float = 60.0,
    workdir: Optional[Path] = None,
) -> dict[str, Any]:
    """Run the CLI end-to-end against a trivial generated program.

    Writes a temp task.json + program.py, runs the CLI, and asserts real stdout
    is exactly one valid JSON line with a status.
    """
    tmp = tempfile.TemporaryDirectory(prefix="harness_cli_probe_")
    root = Path(tmp.name)
    wd = Path(workdir) if workdir else root / "work"
    wd.mkdir(parents=True, exist_ok=True)
    out_dir = root / "out"

    task = {
        "task_id": "cli-probe",
        "prompt": "Probe the CLI contract.",
        "workdir": str(wd),
    }
    (root / "task.json").write_text(json.dumps(task), encoding="utf-8")

    program_src = (
        "from harness_scaffold.core.schemas import HarnessResult\n"
        "class Program:\n"
        "    name = 'cli_probe_program'\n"
        "    async def run(self, ctx, tools, llm):\n"
        "        print('this should NOT pollute stdout')\n"
        "        ctx.new_artifact_text('response.md', '# probe ok')\n"
        "        return HarnessResult(status='success', answer_path=ctx.out_dir/'response.md',\n"
        "            artifacts={}, trajectory_path=ctx.out_dir/'trajectory.jsonl',\n"
        "            metadata_path=ctx.out_dir/'metadata.json', error_path=None, metadata={})\n"
        "PROGRAM = Program()\n"
    )
    (root / "program.py").write_text(program_src, encoding="utf-8")

    proc = _run(
        [
            sys.executable,
            "-m",
            CLI_MODULE,
            "--task-json",
            str(root / "task.json"),
            "--program",
            str(root / "program.py"),
            "--out-dir",
            str(out_dir),
        ],
        timeout=timeout,
    )

    issues: list[str] = []
    parsed: Optional[dict[str, Any]] = None
    raw = proc.stdout.rstrip("\n")
    if "\n" in raw:
        issues.append("stdout has more than one line")
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        issues.append(f"stdout not valid JSON: {exc}")

    tmp.cleanup()
    return {
        "ok": proc.returncode in (0, 1) and not issues,
        "returncode": proc.returncode,
        "stdout_line": raw[:500],
        "parsed": parsed,
        "issues": issues,
    }


def _run(cmd: list[str], *, timeout: float) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "")
