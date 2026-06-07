"""THE unified CLI entrypoint and stdout contract enforcer.

Usage::

    python -m harness_scaffold.adapters.cli \
        --task-json /path/to/task.json \
        --program  /path/to/generated_program.py \
        --out-dir  /path/to/out \
        [--config  /path/to/config.json]

GUARANTEE: real stdout receives EXACTLY ONE compact JSON line, e.g.::

    {"status":"success","out_dir":"/tmp/out","metadata_path":"/tmp/out/metadata.json"}

Everything else (response, trajectory, logs, tool output, tracebacks) goes to
files under ``--out-dir``. On ANY failure (bad args, import error, adapter
error, runtime error) the CLI STILL prints one JSON line with the correct status
and writes ``error.json``.

``--help`` prints usage to stdout and exits 0.

NO third-party imports.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from ..core.errors import (
    AdapterError,
    ContractError,
    ErrorCode,
    HarnessError,
    InvalidHarnessError,
    build_error_json,
    error_from_exception,
)
from ..core.runtime import HarnessRuntime, build_failed_result
from ..core.schemas import HarnessResult, RuntimePolicy
from ..core.stdout_contract import emit_result_line
from .generated_harness_adapter import load_program
from .task_json import load_task

PROG = "harness_scaffold.adapters.cli"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Universal harness runtime CLI. Runs a generated HarnessProgram "
            "against a task and writes a deterministic out-dir. STDOUT is "
            "exactly one JSON line; all content goes to files."
        ),
    )
    p.add_argument("--task-json", required=True, help="Path to task.json")
    p.add_argument(
        "--program",
        required=True,
        help="Path to the generated program .py (must expose PROGRAM or get_program())",
    )
    p.add_argument("--out-dir", required=True, help="Output directory for all artifacts")
    p.add_argument(
        "--config",
        default=None,
        help="Optional JSON config: policy overrides + optional llm settings",
    )
    return p


def _load_config(path: Optional[str]) -> dict[str, Any]:
    if not path:
        return {}
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ContractError(
            f"config file not found: {cfg_path}",
            stage="cli",
            details={"path": str(cfg_path)},
        )
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            f"config is not valid JSON: {exc}",
            stage="cli",
            details={"path": str(cfg_path)},
        ) from exc


def _build_policy(config: dict[str, Any]) -> RuntimePolicy:
    return RuntimePolicy.from_dict(config.get("policy") or {})


def _build_llm(config: dict[str, Any]) -> Optional[Any]:
    """Construct an LLM client from config, or None.

    Config shape::

        {"llm": {"provider": "openai_like"|"anthropic_like"|"mock",
                 "model": "...", "base_url": "...", ...}}

    Provider clients lazy-import their deps; failures here surface as a
    structured error and the run continues with no LLM only if not required.
    """
    llm_cfg = config.get("llm")
    if not llm_cfg:
        return None
    provider = (llm_cfg.get("provider") or "").lower()
    kwargs = {k: v for k, v in llm_cfg.items() if k != "provider"}
    if provider in ("", "none", "null"):
        return None
    if provider == "mock":
        from ..llm.mock import MockLLMClient

        return MockLLMClient(kwargs.get("scripted"), model=kwargs.get("model", "mock-model"))
    if provider in ("openai", "openai_like", "openai-like"):
        from ..llm.openai_like import OpenAILikeClient

        return OpenAILikeClient(**kwargs)
    if provider in ("anthropic", "anthropic_like", "anthropic-like"):
        from ..llm.anthropic_like import AnthropicLikeClient

        return AnthropicLikeClient(**kwargs)
    raise ContractError(
        f"unknown llm provider: {provider!r}",
        stage="cli",
        details={"provider": provider},
    )


def run_cli(argv: list[str]) -> int:
    """Parse args, run, and emit exactly one JSON line. Returns process exit code.

    This function NEVER lets an exception escape to stdout: all failures become a
    single JSON line + error.json. Returns 0 on success status, 1 otherwise.
    """
    start = time.monotonic()

    # --- argument parsing (failures must still yield one JSON line) ----- #
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as se:
        # argparse exits: code 0 for --help, 2 for usage error.
        if se.code in (0, None):
            return 0
        # Usage error: we cannot know out-dir; emit a contract_error line.
        err = build_error_json(
            error_code=ErrorCode.CONTRACT_ERROR,
            message="invalid command-line arguments",
            stage="cli",
            details={"argv": argv},
            elapsed_seconds=time.monotonic() - start,
        )
        emit_result_line(
            {"status": ErrorCode.CONTRACT_ERROR.value, "out_dir": None, "error": err}
        )
        return 1

    out_dir = Path(args.out_dir)

    # From here on we have an out-dir, so every failure writes files too.
    try:
        config = _load_config(args.config)
        policy = _build_policy(config)
        task = load_task(Path(args.task_json))
        program = load_program(Path(args.program))
        llm = _build_llm(config)
    except HarnessError as exc:
        return _emit_failure(out_dir, exc, start)
    except Exception as exc:  # noqa: BLE001
        return _emit_failure(
            out_dir,
            AdapterError(
                f"adapter setup failed: {type(exc).__name__}: {exc}",
                stage="cli",
                details={"exception_type": type(exc).__name__},
            ),
            start,
        )

    # --- run the harness ------------------------------------------------- #
    try:
        runtime = HarnessRuntime(tools=_build_tools(config), llm=llm, policy=policy)
        result: HarnessResult = runtime.run_sync(task, program, out_dir)
    except HarnessError as exc:
        return _emit_failure(out_dir, exc, start)
    except Exception as exc:  # noqa: BLE001
        return _emit_failure(
            out_dir,
            HarnessError(
                f"runtime crashed: {type(exc).__name__}: {exc}",
                error_code=ErrorCode.UNKNOWN_ERROR,
                stage="runtime",
                details={"exception_type": type(exc).__name__},
            ),
            start,
        )

    # Success path: emit the single JSON line from the result.
    line = result.stdout_line(out_dir)
    emit_result_line(line)
    return 0 if result.status == ErrorCode.SUCCESS.value else 1


def _build_tools(config: dict[str, Any]) -> Any:
    from ..tools.registry import default_registry

    include_optional = bool(config.get("include_optional_tools", True))
    return default_registry(include_optional=include_optional)


def _emit_failure(out_dir: Path, exc: HarnessError, start: float) -> int:
    elapsed = time.monotonic() - start
    error_obj = exc.to_dict(elapsed_seconds=elapsed)
    status = exc.error_code.value
    try:
        result = build_failed_result(out_dir, status=status, error_obj=error_obj)
        line = result.stdout_line(out_dir)
    except Exception:  # noqa: BLE001 - even finalize failed; still emit a line
        line = {
            "status": status,
            "out_dir": str(out_dir),
            "error_path": str(Path(out_dir) / "error.json"),
        }
    emit_result_line(line)
    return 1


def main(argv: Optional[list[str]] = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
