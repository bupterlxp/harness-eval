"""Helpers for loading + safely wrapping an LLM-generated HarnessProgram.

A generated program module must expose ONE of:
  * a module-level ``PROGRAM`` instance (preferred), or
  * a ``get_program() -> HarnessProgram`` factory, or
  * a single ``HarnessProgram`` subclass (instantiated with no args).

This module distinguishes ``invalid_harness`` (the program file is structurally
wrong / un-importable) from ``adapter_failed`` (the wrapping/loading machinery
itself failed) and from runtime errors (handled by HarnessRuntime).

NO third-party imports.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

from ..core.errors import AdapterError, ErrorCode, HarnessError, InvalidHarnessError

PROGRAM_ATTR = "PROGRAM"
FACTORY_ATTR = "get_program"


def load_program(program_path: Path) -> Any:
    """Import a program module from a file path and return a HarnessProgram.

    Raises :class:`InvalidHarnessError` for structural problems with the program,
    :class:`AdapterError` if the loader machinery itself fails.
    """
    program_path = Path(program_path)
    if not program_path.exists():
        raise InvalidHarnessError(
            f"program file not found: {program_path}",
            stage="adapter",
            details={"path": str(program_path)},
        )

    mod_name = f"_generated_harness_{abs(hash(str(program_path.resolve())))}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(program_path))
        if spec is None or spec.loader is None:
            raise AdapterError(
                "could not create import spec for program",
                stage="adapter",
                details={"path": str(program_path)},
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)  # may raise anything
    except HarnessError:
        raise
    except SyntaxError as exc:
        raise InvalidHarnessError(
            f"program has a syntax error: {exc}",
            stage="adapter",
            details={"path": str(program_path), "error": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - import-time failure
        raise InvalidHarnessError(
            f"program failed to import: {type(exc).__name__}: {exc}",
            stage="adapter",
            details={"path": str(program_path), "exception_type": type(exc).__name__},
        ) from exc

    return extract_program(module, source=str(program_path))


def extract_program(module: Any, *, source: str = "<module>") -> Any:
    """Find the HarnessProgram in an already-imported module."""
    program = getattr(module, PROGRAM_ATTR, None)
    if program is not None:
        _check_runnable(program, source)
        return program

    factory = getattr(module, FACTORY_ATTR, None)
    if callable(factory):
        try:
            program = factory()
        except Exception as exc:  # noqa: BLE001
            raise InvalidHarnessError(
                f"{FACTORY_ATTR}() raised: {type(exc).__name__}: {exc}",
                stage="adapter",
                details={"source": source},
            ) from exc
        _check_runnable(program, source)
        return program

    # Fall back to a single HarnessProgram-like class.
    candidates = [
        v
        for v in vars(module).values()
        if isinstance(v, type) and _looks_like_program_class(v)
    ]
    if len(candidates) == 1:
        try:
            program = candidates[0]()
        except Exception as exc:  # noqa: BLE001
            raise InvalidHarnessError(
                f"program class could not be instantiated: {exc}",
                stage="adapter",
                details={"source": source, "class": candidates[0].__name__},
            ) from exc
        _check_runnable(program, source)
        return program

    raise InvalidHarnessError(
        "program module exposes no PROGRAM, get_program(), or single program class",
        stage="adapter",
        details={
            "source": source,
            "expected_one_of": [PROGRAM_ATTR, f"{FACTORY_ATTR}()", "single HarnessProgram subclass"],
        },
    )


def _looks_like_program_class(cls: type) -> bool:
    # Duck-typing: defines an instance-level async/sync ``run``.
    return hasattr(cls, "run") and cls.__name__ not in ("HarnessProgram", "object")


def _check_runnable(program: Any, source: str) -> None:
    if not hasattr(program, "run") or not callable(getattr(program, "run")):
        raise InvalidHarnessError(
            "program has no callable run(ctx, tools, llm)",
            stage="adapter",
            details={"source": source, "program": type(program).__name__},
        )


class FunctionProgram:
    """Wrap a plain ``async def run(ctx, tools, llm)`` function as a program.

    Convenience for examples/tests that don't want to define a class.
    """

    def __init__(self, fn: Any, *, name: str = "function_program") -> None:
        self._fn = fn
        self.name = name

    async def run(self, ctx: Any, tools: Any, llm: Any) -> Any:
        result = self._fn(ctx, tools, llm)
        import asyncio

        if asyncio.iscoroutine(result):
            result = await result
        return result


def preflight_program(program: Any) -> dict[str, Any]:
    """Cheap structural validation of a program object; returns a report."""
    ok = hasattr(program, "run") and callable(getattr(program, "run"))
    return {
        "ok": ok,
        "name": getattr(program, "name", type(program).__name__),
        "has_run": ok,
        "classification": ErrorCode.SUCCESS.value if ok else ErrorCode.INVALID_HARNESS.value,
    }
