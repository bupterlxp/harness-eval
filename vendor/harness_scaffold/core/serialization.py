"""Safe JSON serialization helpers.

These guarantee that anything written to disk (trajectory, metadata, artifacts
manifest, error.json) can be serialized without exploding on Path objects,
dataclasses, sets, or raw bytes. This is load-bearing for the stdout contract:
``emit_result_line`` must never throw.

NO third-party imports.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


def json_default(obj: Any) -> Any:
    """Fallback encoder for ``json.dumps(default=...)``.

    Handles Path, dataclass instances, sets/tuples/frozensets, bytes (as a
    short preview), and anything with a ``to_dict``. Last resort: ``repr``.
    """
    if isinstance(obj, Path):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, (bytes, bytearray)):
        return _bytes_preview(bytes(obj))
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:  # pragma: no cover - defensive
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return repr(obj)


def _bytes_preview(b: bytes, *, max_len: int = 256) -> dict[str, Any]:
    head = b[:max_len]
    try:
        text = head.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive
        text = repr(head)
    return {
        "__bytes__": True,
        "length": len(b),
        "preview": text,
        "truncated": len(b) > max_len,
    }


def safe_json_dumps(
    obj: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
    ensure_ascii: bool = False,
    compact: bool = False,
) -> str:
    """Serialize ``obj`` to JSON, never raising on un-encodable members.

    ``compact=True`` produces the single-line separators used by the stdout
    contract. Falls back to a repr-based encoding on any TypeError.
    """
    separators = (",", ":") if compact else None
    try:
        return json.dumps(
            obj,
            default=json_default,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii,
            separators=separators,
        )
    except (TypeError, ValueError):
        # Coerce the whole structure through json_default recursively as a
        # last resort by round-tripping via repr-ed leaves.
        coerced = _coerce(obj)
        return json.dumps(
            coerced,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=ensure_ascii,
            separators=separators,
        )


def _coerce(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _coerce(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_coerce(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    try:
        return _coerce(json_default(obj))
    except Exception:  # pragma: no cover - defensive
        return repr(obj)


def truncate(text: str, max_bytes: int, *, suffix: str = "\n...[truncated]") -> str:
    """Truncate ``text`` so its UTF-8 encoding is <= ``max_bytes``.

    Appends ``suffix`` when truncation occurs (suffix counted against budget).
    Never returns more than ``max_bytes`` bytes. Safe for any ``max_bytes>=0``.
    """
    if max_bytes <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    suffix_raw = suffix.encode("utf-8")
    keep = max(0, max_bytes - len(suffix_raw))
    if keep <= 0:
        # suffix itself doesn't fit; just hard-cut the text.
        return raw[:max_bytes].decode("utf-8", errors="ignore")
    head = raw[:keep].decode("utf-8", errors="ignore")
    return head + suffix


def preview(text: str | None, max_bytes: int = 4096) -> str | None:
    """Short preview used for ToolResult.stdout_preview / stderr_preview."""
    if text is None:
        return None
    return truncate(text, max_bytes)


def write_json_file(path: Path, obj: Any, *, indent: int = 2, sort_keys: bool = False) -> Path:
    """Write a pretty JSON file atomically-ish (write then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(safe_json_dumps(obj, indent=indent, sort_keys=sort_keys), encoding="utf-8")
    tmp.replace(path)
    return path
