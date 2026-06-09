from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


INPUT_KEYS = ("input_tokens", "prompt_tokens", "agent_input_tokens")
OUTPUT_KEYS = ("output_tokens", "completion_tokens", "agent_output_tokens")
REASONING_KEYS = ("reasoning_tokens", "agent_reasoning_tokens")
TOTAL_KEYS = ("total_tokens", "agent_total_tokens", "harness_run_tokens", "tokens")
USAGE_KEYS = ("usage", "token_usage", "llm_usage")
JSON_FILENAMES = {
    "metadata.json",
    "result.json",
    "harness_result.json",
    "metrics.json",
    "artifacts.json",
}
JSONL_FILENAMES = {"trajectory.jsonl", "events.jsonl"}
TEXT_FILENAMES = {"stdout.log", "stderr.log", "harness_stdout.log", "harness_stderr.log"}


def _safe_read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > 5_000_000:
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            return None
    return None


def _add_field(target: dict[str, int | float], key: str, value: Any) -> None:
    number = _as_number(value)
    if number is None:
        return
    target[key] = target.get(key, 0) + number


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize provider-specific token usage into a stable summary.

    Anthropic-style responses usually expose ``input_tokens`` and
    ``output_tokens``. OpenAI-compatible responses usually expose
    ``prompt_tokens`` and ``completion_tokens``. We preserve the original
    numeric fields and also compute canonical ``total_tokens`` when possible.
    """
    if not isinstance(usage, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in usage.items():
        number = _as_number(value)
        if number is not None:
            normalized[key] = number

    input_total = _as_number(usage.get("input_tokens"))
    if input_total is None:
        input_total = _as_number(usage.get("prompt_tokens"))
    if input_total is None:
        input_total = _as_number(usage.get("agent_input_tokens"))
    input_total = input_total or 0

    output_total = _as_number(usage.get("output_tokens"))
    if output_total is None:
        output_total = _as_number(usage.get("completion_tokens"))
    if output_total is None:
        output_total = _as_number(usage.get("agent_output_tokens"))
    output_total = output_total or 0

    reasoning_total = sum(_as_number(usage.get(key)) or 0 for key in REASONING_KEYS)
    explicit_total = next((_as_number(usage.get(key)) for key in TOTAL_KEYS if _as_number(usage.get(key)) is not None), None)
    if explicit_total is None and (input_total or output_total):
        explicit_total = input_total + output_total
    if explicit_total is not None:
        normalized["total_tokens"] = explicit_total
    if input_total:
        normalized["input_tokens"] = input_total
    if output_total:
        normalized["output_tokens"] = output_total
    if reasoning_total:
        normalized["reasoning_tokens"] = reasoning_total
    return normalized


def merge_token_usages(usages: Iterable[dict[str, Any] | None]) -> dict[str, Any]:
    merged: dict[str, int | float] = {}
    sources: list[str] = []
    for usage in usages:
        if not usage:
            continue
        for key, value in usage.items():
            if key == "source_files":
                if isinstance(value, list):
                    sources.extend(str(item) for item in value)
                continue
            if key == "source":
                continue
            _add_field(merged, key, value)
    result: dict[str, Any] = normalize_usage(merged)
    if sources:
        result["source_files"] = sorted(set(sources))
    return result


def _extract_direct_usage(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    for key in USAGE_KEYS:
        usage = normalize_usage(obj.get(key))
        if usage.get("total_tokens") is not None:
            return usage
    return normalize_usage(obj)


def _iter_named_files(root: Path, names: set[str], *, limit: int = 200) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.name in names else []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.name in names:
            files.append(path)
            if len(files) >= limit:
                break
    return files


def _artifact_dirs_from_json(path: Path) -> list[Path]:
    data = _safe_read_json(path)
    if not isinstance(data, dict):
        return []
    dirs = []
    for key in ("artifacts_dir", "output_dir", "run_output_dir"):
        value = data.get(key)
        if value:
            candidate = Path(str(value))
            if candidate.exists() and candidate.is_dir():
                dirs.append(candidate)
    return dirs


def _candidate_roots(paths: Iterable[str | Path | None]) -> list[Path]:
    roots: list[Path] = []
    for item in paths:
        if not item:
            continue
        path = Path(str(item))
        if not path.exists():
            continue
        roots.append(path)
        if path.is_file():
            roots.append(path.parent)
            roots.extend(_artifact_dirs_from_json(path))
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key not in seen:
            deduped.append(root)
            seen.add(key)
    return deduped


def _usage_from_json_files(roots: list[Path]) -> dict[str, Any]:
    # Prefer scaffold/runtime metadata because it already aggregates LLM calls.
    for name in ("metadata.json", "metrics.json", "result.json", "harness_result.json"):
        for root in roots:
            for path in _iter_named_files(root, {name}):
                data = _safe_read_json(path)
                usage = _extract_direct_usage(data)
                if usage.get("total_tokens") is not None:
                    usage["source_files"] = [str(path)]
                    return usage
    return {}


def _usage_from_trajectory_files(roots: list[Path]) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    sources: list[str] = []
    for root in roots:
        for path in _iter_named_files(root, JSONL_FILENAMES):
            try:
                if path.stat().st_size > 20_000_000:
                    continue
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        continue
                    usage = normalize_usage(event.get("usage"))
                    if usage.get("total_tokens") is not None:
                        usages.append(usage)
                if usages:
                    sources.append(str(path))
            except Exception:
                continue
    merged = merge_token_usages(usages)
    if merged:
        merged["source_files"] = sources
    return merged


_USAGE_MARKER_RE = re.compile(r"(?:USAGE|TOKEN_USAGE|KIMI_WRITER_USAGE_JSON)\s*[:=]\s*(\{.*?\})(?:\n|$)")


def _usage_from_text_files(roots: list[Path]) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    sources: list[str] = []
    for root in roots:
        for path in _iter_named_files(root, TEXT_FILENAMES):
            try:
                if path.stat().st_size > 10_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for match in _USAGE_MARKER_RE.finditer(text):
                    usage = normalize_usage(json.loads(match.group(1)))
                    if usage.get("total_tokens") is not None:
                        usages.append(usage)
                        sources.append(str(path))
            except Exception:
                continue
    merged = merge_token_usages(usages)
    if merged:
        merged["source_files"] = sorted(set(sources))
    return merged


def extract_harness_token_usage(*paths: str | Path | None) -> dict[str, Any]:
    """Extract eval-time generated harness token usage from harness CLI artifacts.

    This intentionally targets the generated/evolved harness execution logs,
    not downstream judge calls. Callers should record judge-token usage in
    ``score_breakdown`` instead of ``harness_run_tokens``.
    """
    roots = _candidate_roots(paths)
    if not roots:
        return {}
    for extractor in (_usage_from_json_files, _usage_from_trajectory_files, _usage_from_text_files):
        usage = extractor(roots)
        if usage.get("total_tokens") is not None:
            usage["source"] = extractor.__name__.replace("_usage_from_", "")
            return usage
    return {}


def extract_harness_token_usage_from_result(result: Any) -> dict[str, Any]:
    return extract_harness_token_usage(
        getattr(result, "raw_result_path", ""),
        getattr(result, "stdout_path", ""),
        getattr(result, "stderr_path", ""),
    )
