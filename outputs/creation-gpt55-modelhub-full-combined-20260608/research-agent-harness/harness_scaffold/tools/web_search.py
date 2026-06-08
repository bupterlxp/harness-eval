"""WebSearchTool: pluggable web-search backend.

This is an ATOMIC capability, not a hosted product feature. There is NO built-in
search index and NO fabricated results. A search backend must be supplied via one
of these mechanisms (checked in order):

1. ``ctx.metadata["web_search_backend"]`` — a callable
   ``backend(query, *, allowed_domains, blocked_domains, max_results, timeout)``
   returning a list of result dicts (or an object with such a method).
2. ``ctx.metadata["serper_api_key"]`` / env ``SERPER_KEY_ID`` or
   ``SERPER_API_KEY`` — uses Serper over HTTP (requires network).
3. ``ctx.metadata["serpapi_api_key"]`` / env ``SERPAPI_API_KEY`` — uses SerpApi
   over HTTP (requires network + the stdlib/``requests`` fetch path).

If no backend and no key are configured, the tool returns a STRUCTURED
``dependency_error`` with an empty result set — it never invents results.

Always:
- ``requires_network=True`` (the wrapper gates on ``allow_network``; we also
  defensively call ``ctx.permissions.check_network``).
- A hard timeout (``ctx.policy.max_tool_seconds`` clamped to budget) so it can
  never hang.
- Records ``source``/evidence metadata (backend, query, result count) and writes
  the results as a JSON artifact.
- NEVER prints to stdout. NEVER raises to the caller.

NO third-party imports at module top level.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    PermissionDenied,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from .base import AtomicTool


class WebSearchTool(AtomicTool):
    name = "web_search"
    description = (
        "Search the web via a configured, pluggable backend and return structured "
        "result blocks (title, url, snippet). Requires a backend or API key in "
        "ctx.metadata/env; returns a structured dependency_error (no fabricated "
        "results) when none is configured. Read-only; requires network."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to use.",
                "minLength": 2,
            },
            "allowed_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only include results from these domains.",
            },
            "blocked_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Never include results from these domains.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                },
            },
            "count": {"type": "integer"},
            "backend": {"type": "string"},
            "source": {"type": "string"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = True
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        start = time.monotonic()
        query = str(args.get("query", "")).strip()
        if len(query) < 2:
            return ToolResult.fail(
                "web_search requires a 'query' of at least 2 characters",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_search",
            )
        allowed = _as_str_list(args.get("allowed_domains"))
        blocked = _as_str_list(args.get("blocked_domains"))
        max_results = args.get("max_results", 5)
        if not isinstance(max_results, int) or max_results <= 0:
            max_results = 5

        # Defensive network gate (wrapper already gates requires_network=True).
        try:
            ctx.permissions.check_network(query)
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(elapsed_seconds=time.monotonic() - start))

        timeout_s = self._effective_timeout(ctx)

        backend = self._resolve_backend(ctx)
        if backend is None:
            # No backend configured -> structured dependency error, NO fabrication.
            from ..core.errors import DependencyError

            err = DependencyError(
                "web_search has no configured backend; set "
                "ctx.metadata['web_search_backend'] (callable) or a SerpApi key "
                "(ctx.metadata['serpapi_api_key'] / env SERPAPI_API_KEY)",
                stage="tool:web_search",
                details={
                    "query": query,
                    "configured_backend": None,
                    "hint": "no results fabricated",
                },
            ).to_dict(elapsed_seconds=time.monotonic() - start)
            # Return failure with empty results so callers can branch cleanly.
            return ToolResult.fail(
                err,
                elapsed_seconds=time.monotonic() - start,
                metadata={"query": query, "results": [], "count": 0, "backend": None},
            )

        backend_name, backend_call = backend
        try:
            results = backend_call(
                query,
                allowed_domains=allowed,
                blocked_domains=blocked,
                max_results=max_results,
                timeout=timeout_s,
            )
        except TimeoutErrorH as exc:
            return ToolResult.fail(exc.to_dict(elapsed_seconds=time.monotonic() - start))
        except HarnessError as exc:
            return ToolResult.fail(exc.to_dict(elapsed_seconds=time.monotonic() - start))
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                f"web_search backend '{backend_name}' failed: "
                f"{type(exc).__name__}: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_search",
                details={"query": query, "backend": backend_name},
                elapsed_seconds=time.monotonic() - start,
            )

        results = _normalize_results(results, allowed, blocked, max_results)
        source = f"web_search:{backend_name}"

        artifacts: dict[str, Path] = {}
        try:
            art_name = "web_search/results.json"
            art_path = ctx.new_artifact_json(
                art_name,
                {"query": query, "backend": backend_name, "results": results},
                kind="json",
            )
            artifacts[art_name] = art_path
        except Exception:  # noqa: BLE001 - artifact failure must not fail search
            artifacts = {}

        data = {
            "query": query,
            "results": results,
            "count": len(results),
            "backend": backend_name,
            "source": source,
        }
        meta = {
            "query": query,
            "backend": backend_name,
            "source": source,
            "count": len(results),
            "allowed_domains": allowed,
            "blocked_domains": blocked,
        }
        return ToolResult.success(
            data=data,
            artifacts=artifacts,
            stdout_preview=_results_preview(results),
            elapsed_seconds=time.monotonic() - start,
            metadata=meta,
        )

    # --- helpers --------------------------------------------------------- #
    def _effective_timeout(self, ctx: RuntimeContext) -> float:
        timeout_s = ctx.policy.max_tool_seconds or 60.0
        budget_left = ctx.budget.seconds_left()
        if budget_left != float("inf"):
            timeout_s = max(0.1, min(timeout_s, budget_left))
        return timeout_s

    def _resolve_backend(
        self, ctx: RuntimeContext
    ) -> "Optional[tuple[str, Callable[..., Any]]]":
        """Return (name, callable) for the first configured backend, else None."""
        meta = ctx.metadata or {}

        # 1) explicit pluggable callable.
        backend = meta.get("web_search_backend")
        if backend is not None:
            call = _coerce_backend_callable(backend)
            if call is not None:
                return ("custom", call)

        # 2) Serper via metadata or env.
        serper_key = (
            meta.get("serper_api_key")
            or meta.get("serper_key_id")
            or os.environ.get("SERPER_KEY_ID")
            or os.environ.get("SERPER_API_KEY")
        )
        if serper_key:
            return ("serper", lambda *a, **k: _serper_search(serper_key, *a, **k))

        # 3) SerpApi via metadata or env.
        api_key = meta.get("serpapi_api_key") or os.environ.get("SERPAPI_API_KEY")
        if api_key:
            return ("serpapi", lambda *a, **k: _serpapi_search(api_key, *a, **k))

        return None


# --------------------------------------------------------------------------- #
# Built-in search backends (HTTP; requests if present else stdlib urllib).
# --------------------------------------------------------------------------- #


def _serper_search(
    api_key: str,
    query: str,
    *,
    allowed_domains: Optional[list] = None,
    blocked_domains: Optional[list] = None,
    max_results: int = 5,
    timeout: float = 30.0,
) -> list[dict]:
    q = query
    if allowed_domains:
        q += " (" + " OR ".join(f"site:{d}" for d in allowed_domains) + ")"
    if blocked_domains:
        q += "".join(f" -site:{d}" for d in blocked_domains)
    payload = {"q": q, "num": max_results}
    raw = _http_post_json_bytes(
        "https://google.serper.dev/search",
        payload,
        timeout,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise HarnessError(
            f"serper returned invalid JSON: {exc}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
        ) from exc
    if isinstance(data, dict) and data.get("message") and not data.get("organic"):
        raise HarnessError(
            f"serper error: {data['message']}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
            details={"message": data.get("message")},
        )
    organic = data.get("organic", []) if isinstance(data, dict) else []
    results: list[dict] = []
    for item in organic[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("link", "")),
                "snippet": str(item.get("snippet", "")),
            }
        )
    return results


def _serpapi_search(
    api_key: str,
    query: str,
    *,
    allowed_domains: Optional[list] = None,
    blocked_domains: Optional[list] = None,
    max_results: int = 5,
    timeout: float = 30.0,
) -> list[dict]:
    q = query
    # SerpApi supports site: operators; encode include/exclude domains simply.
    if allowed_domains:
        q += " (" + " OR ".join(f"site:{d}" for d in allowed_domains) + ")"
    if blocked_domains:
        q += "".join(f" -site:{d}" for d in blocked_domains)
    params = {"engine": "google", "q": q, "api_key": api_key, "num": max_results}
    url = "https://serpapi.com/search.json?" + urlencode(params)
    raw = _http_get_bytes(url, timeout)
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise HarnessError(
            f"serpapi returned invalid JSON: {exc}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
        ) from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise HarnessError(
            f"serpapi error: {payload['error']}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
            details={"error": payload.get("error")},
        )
    organic = payload.get("organic_results", []) if isinstance(payload, dict) else []
    results: list[dict] = []
    for item in organic[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("link", "")),
                "snippet": str(item.get("snippet", "")),
            }
        )
    return results


def _http_get_bytes(url: str, timeout: float) -> bytes:
    """GET bytes using requests if available, else stdlib urllib. Raises HarnessError."""
    try:
        from ..core.dependency import require

        requests = require("requests", extra="http", purpose="web_search")
    except HarnessError:
        requests = None
    if requests is not None:
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "harness_scaffold/1.0 (+web_search)"},
            )
            return resp.content or b""
        except requests.exceptions.Timeout as exc:  # type: ignore[attr-defined]
            raise TimeoutErrorH(
                f"web_search timed out after {timeout:.1f}s",
                stage="tool:web_search",
                details={"timeout_seconds": timeout},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                f"web_search http request failed: {exc}",
                error_code=ErrorCode.PROVIDER_ERROR,
                stage="tool:web_search",
            ) from exc

    import socket
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "harness_scaffold/1.0 (+web_search)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read() or b""
    except socket.timeout as exc:
        raise TimeoutErrorH(
            f"web_search timed out after {timeout:.1f}s",
            stage="tool:web_search",
            details={"timeout_seconds": timeout},
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise TimeoutErrorH(
                f"web_search timed out after {timeout:.1f}s",
                stage="tool:web_search",
                details={"timeout_seconds": timeout},
            ) from exc
        raise HarnessError(
            f"web_search http request failed: {reason}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
            details={"reason": str(reason)},
        ) from exc


def _http_post_json_bytes(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    headers: Optional[dict[str, str]] = None,
) -> bytes:
    """POST JSON using requests if available, else stdlib urllib."""
    headers = dict(headers or {})
    try:
        from ..core.dependency import require

        requests = require("requests", extra="http", purpose="web_search")
    except HarnessError:
        requests = None
    if requests is not None:
        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=timeout,
                headers={
                    "User-Agent": "harness_scaffold/1.0 (+web_search)",
                    **headers,
                },
            )
            return resp.content or b""
        except requests.exceptions.Timeout as exc:  # type: ignore[attr-defined]
            raise TimeoutErrorH(
                f"web_search timed out after {timeout:.1f}s",
                stage="tool:web_search",
                details={"timeout_seconds": timeout},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HarnessError(
                f"web_search http request failed: {exc}",
                error_code=ErrorCode.PROVIDER_ERROR,
                stage="tool:web_search",
            ) from exc

    import socket
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": "harness_scaffold/1.0 (+web_search)", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read() or b""
    except socket.timeout as exc:
        raise TimeoutErrorH(
            f"web_search timed out after {timeout:.1f}s",
            stage="tool:web_search",
            details={"timeout_seconds": timeout},
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise TimeoutErrorH(
                f"web_search timed out after {timeout:.1f}s",
                stage="tool:web_search",
                details={"timeout_seconds": timeout},
            ) from exc
        raise HarnessError(
            f"web_search http request failed: {reason}",
            error_code=ErrorCode.PROVIDER_ERROR,
            stage="tool:web_search",
            details={"reason": str(reason)},
        ) from exc


# --------------------------------------------------------------------------- #
# Result normalization / backend coercion.
# --------------------------------------------------------------------------- #


def _coerce_backend_callable(backend: Any) -> "Optional[Callable[..., Any]]":
    if callable(backend):
        return backend
    for attr in ("search", "run", "__call__"):
        fn = getattr(backend, attr, None)
        if callable(fn):
            return fn
    return None


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(v) for v in value]
    except TypeError:
        return []


def _domain_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _normalize_results(
    results: Any,
    allowed: list[str],
    blocked: list[str],
    max_results: int,
) -> list[dict]:
    if not isinstance(results, (list, tuple)):
        return []
    out: list[dict] = []
    allowed_l = [d.lower() for d in allowed]
    blocked_l = [d.lower() for d in blocked]
    for item in results:
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("link") or "")
            entry = {
                "title": str(item.get("title", "")),
                "url": url,
                "snippet": str(item.get("snippet") or item.get("description") or ""),
            }
        elif isinstance(item, str):
            entry = {"title": "", "url": item, "snippet": ""}
        else:
            continue
        dom = _domain_of(entry["url"])
        if blocked_l and any(b in dom for b in blocked_l if b):
            continue
        if allowed_l and not any(a in dom for a in allowed_l if a):
            continue
        out.append(entry)
        if len(out) >= max_results:
            break
    return out


def _results_preview(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results[:10], 1):
        lines.append(f"{i}. {r.get('title', '')} — {r.get('url', '')}")
    return "\n".join(lines)


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return this module's tool instances."""
    return [WebSearchTool()]
