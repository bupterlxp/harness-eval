"""WebFetchTool: fetch a URL (http/https) or a local ``file://`` URL/path.

Behavior (mirrors the universal/atomic capability, not the CC product):

- ``http(s)`` URLs require network (``requires_network=True``); the wrapper gates
  on ``ctx.permissions.allow_network`` and we also defensively call
  ``ctx.permissions.check_network``. HTTP is upgraded to HTTPS by default.
- ``file://`` URLs and bare local paths are allowed OFFLINE; they are confined to
  the sandbox via ``ctx.check_path_read``.
- Fetching uses ``requests`` if available (lazy import), else falls back to the
  stdlib ``urllib`` so the tool works with zero optional deps.
- HTML responses are stripped to text: ``bs4`` if available (lazy), else the
  stdlib ``html.parser``-based extractor.
- Enforces a hard timeout (``ctx.policy.max_tool_seconds`` clamped to budget) and
  caps the response to ``ctx.policy.max_output_bytes``.
- Records ``source`` / evidence metadata (final URL, status, content-type, bytes)
  and writes the fetched text as an artifact.
- NEVER prints to stdout. NEVER raises to the caller: returns ``ToolResult.fail``
  with a structured ErrorCode on any error.

NO third-party imports at module top level.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    PermissionDenied,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from ..core.serialization import truncate
from .base import AtomicTool

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class WebFetchTool(AtomicTool):
    name = "web_fetch"
    description = (
        "Fetch content from a URL (http/https) or a local file:// URL and return "
        "it as text. HTML is converted to plain text. http(s) requires network; "
        "file:// works offline within the sandbox. Read-only."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (http://, https://, or file://, "
                "or a local path within the sandbox).",
            },
            "as_text": {
                "type": "boolean",
                "description": "Strip HTML to plain text (default true).",
                "default": True,
            },
            "upgrade_http": {
                "type": "boolean",
                "description": "Upgrade http:// to https:// (default true).",
                "default": True,
            },
            "max_bytes": {
                "type": "integer",
                "description": "Optional override for the max returned bytes.",
            },
        },
        "required": ["url"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "source": {"type": "string"},
            "status": {"type": "integer"},
            "content_type": {"type": "string"},
            "bytes": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
    }
    is_read_only = True
    is_destructive = False
    # http(s) needs network; the wrapper gates on this. file:// is handled below
    # WITHOUT network (we branch before any network check).
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        start = time.monotonic()
        url = str(args.get("url", "")).strip()
        if not url:
            return ToolResult.fail(
                "web_fetch requires a non-empty 'url'",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_fetch",
            )
        as_text = bool(args.get("as_text", True))
        upgrade_http = bool(args.get("upgrade_http", True))
        max_bytes = args.get("max_bytes")
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            max_bytes = ctx.policy.max_output_bytes

        scheme = urlsplit(url).scheme.lower()

        # --- local file branch (offline-safe) ---------------------------- #
        if scheme == "file" or scheme == "" or scheme in ("", None):
            return self._fetch_local(ctx, url, scheme, as_text, max_bytes, start)

        # --- network branch ---------------------------------------------- #
        if scheme == "http" and upgrade_http:
            url = "https://" + url[len("http://"):]
            scheme = "https"
        if scheme not in ("http", "https"):
            return ToolResult.fail(
                f"unsupported URL scheme: {scheme!r}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_fetch",
                details={"url": url, "scheme": scheme},
            )

        # Defensive network gate (wrapper already gates requires_network when set,
        # but this tool keeps requires_network=False to allow the file:// path, so
        # we MUST enforce here for the network branch).
        try:
            ctx.permissions.check_network(url)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.to_dict(),
                elapsed_seconds=time.monotonic() - start,
            )

        timeout_s = self._effective_timeout(ctx)
        try:
            status, ctype, raw = self._http_get(url, timeout_s)
        except TimeoutErrorH as exc:
            return ToolResult.fail(
                exc.to_dict(elapsed_seconds=time.monotonic() - start),
            )
        except HarnessError as exc:
            return ToolResult.fail(
                exc.to_dict(elapsed_seconds=time.monotonic() - start),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(
                f"web_fetch failed: {type(exc).__name__}: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_fetch",
                details={"url": url, "exception_type": type(exc).__name__},
                elapsed_seconds=time.monotonic() - start,
            )

        return self._finalize(
            ctx, url, status, ctype, raw, as_text, max_bytes, start
        )

    # --- local-file handling -------------------------------------------- #
    def _fetch_local(
        self,
        ctx: RuntimeContext,
        url: str,
        scheme: str,
        as_text: bool,
        max_bytes: int,
        start: float,
    ) -> ToolResult:
        if scheme == "file":
            parts = urlsplit(url)
            local_path = parts.path or ""
            if not local_path:
                return ToolResult.fail(
                    "file:// URL has no path",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="tool:web_fetch",
                    details={"url": url},
                )
        else:
            local_path = url
        try:
            path = ctx.check_path_read(Path(local_path))
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(elapsed_seconds=time.monotonic() - start))
        if not path.exists() or not path.is_file():
            return ToolResult.fail(
                f"local file not found: {path}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:web_fetch",
                details={"path": str(path)},
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return ToolResult.fail(
                f"failed to read local file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:web_fetch",
                details={"path": str(path)},
                elapsed_seconds=time.monotonic() - start,
            )
        ctype = "text/html" if path.suffix.lower() in (".html", ".htm") else "text/plain"
        return self._finalize(
            ctx, f"file://{path}", 200, ctype, raw, as_text, max_bytes, start
        )

    # --- network helpers ------------------------------------------------- #
    def _effective_timeout(self, ctx: RuntimeContext) -> float:
        timeout_s = ctx.policy.max_tool_seconds or 60.0
        budget_left = ctx.budget.seconds_left()
        if budget_left != float("inf"):
            timeout_s = max(0.1, min(timeout_s, budget_left))
        return timeout_s

    def _http_get(self, url: str, timeout_s: float):
        """Return (status, content_type, raw_bytes). requests if present, else urllib."""
        # Prefer requests (lazy), but it is OPTIONAL: fall back to stdlib urllib.
        try:
            from ..core.dependency import require

            requests = require("requests", extra="http", purpose="web_fetch")
        except HarnessError:
            requests = None
        if requests is not None:
            try:
                resp = requests.get(
                    url,
                    timeout=timeout_s,
                    headers={"User-Agent": "harness_scaffold/1.0 (+web_fetch)"},
                    allow_redirects=True,
                )
            except requests.exceptions.Timeout as exc:  # type: ignore[attr-defined]
                raise TimeoutErrorH(
                    f"web_fetch timed out after {timeout_s:.1f}s",
                    stage="tool:web_fetch",
                    details={"url": url, "timeout_seconds": timeout_s},
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise HarnessError(
                    f"http request failed: {exc}",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage="tool:web_fetch",
                    details={"url": url, "exception_type": type(exc).__name__},
                ) from exc
            ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
            return resp.status_code, ctype, resp.content or b""

        # stdlib fallback
        import socket
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            url, headers={"User-Agent": "harness_scaffold/1.0 (+web_fetch)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
                status = getattr(resp, "status", None) or resp.getcode() or 200
                ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # Read the error body so callers can inspect it.
            try:
                raw = exc.read()
            except Exception:  # noqa: BLE001
                raw = b""
            ctype = ""
            try:
                ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
            except Exception:  # noqa: BLE001
                ctype = ""
            return int(exc.code), ctype, raw or b""
        except socket.timeout as exc:
            raise TimeoutErrorH(
                f"web_fetch timed out after {timeout_s:.1f}s",
                stage="tool:web_fetch",
                details={"url": url, "timeout_seconds": timeout_s},
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, socket.timeout):
                raise TimeoutErrorH(
                    f"web_fetch timed out after {timeout_s:.1f}s",
                    stage="tool:web_fetch",
                    details={"url": url, "timeout_seconds": timeout_s},
                ) from exc
            raise HarnessError(
                f"http request failed: {reason}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:web_fetch",
                details={"url": url, "reason": str(reason)},
            ) from exc
        return int(status), ctype, raw or b""

    # --- shared finalize ------------------------------------------------- #
    def _finalize(
        self,
        ctx: RuntimeContext,
        source: str,
        status: int,
        ctype: str,
        raw: bytes,
        as_text: bool,
        max_bytes: int,
        start: float,
    ) -> ToolResult:
        raw_bytes = len(raw)
        text = raw.decode("utf-8", errors="replace")
        is_html = "html" in (ctype or "").lower() or _looks_like_html(text)
        if as_text and is_html:
            text = _html_to_text(text)

        truncated = False
        if len(text.encode("utf-8", "ignore")) > max_bytes:
            text = truncate(text, max_bytes)
            truncated = True

        # Persist the fetched content as an artifact for evidence/traceability.
        artifacts: dict[str, Path] = {}
        try:
            art_name = "web_fetch/" + _safe_name(source)
            art_path = ctx.new_artifact_text(art_name, text, kind="text")
            artifacts[art_name] = art_path
        except Exception:  # noqa: BLE001 - artifact failure must not fail the fetch
            artifacts = {}

        data = {
            "content": text,
            "source": source,
            "status": int(status),
            "content_type": ctype or "",
            "bytes": raw_bytes,
            "truncated": truncated,
        }
        meta = {
            "source": source,
            "status": int(status),
            "content_type": ctype or "",
            "bytes": raw_bytes,
            "is_html": is_html,
            "truncated": truncated,
        }
        # A non-2xx status is surfaced as data but not treated as a hard failure;
        # the program can decide. (4xx/5xx still returned ok with status set.)
        return ToolResult.success(
            data=data,
            artifacts=artifacts,
            stdout_preview=text[:1000],
            elapsed_seconds=time.monotonic() - start,
            metadata=meta,
        )


# --------------------------------------------------------------------------- #
# HTML -> text helpers (bs4 if available, else stdlib html.parser).
# --------------------------------------------------------------------------- #


def _html_to_text(html: str) -> str:
    # Prefer bs4 (lazy, optional). Never required.
    try:
        from ..core.dependency import require

        bs4 = require("bs4", extra="html", purpose="web_fetch html->text")
    except HarnessError:
        bs4 = None
    if bs4 is not None:
        try:
            soup = bs4.BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "template"]):
                tag.decompose()
            txt = soup.get_text(separator="\n")
            return _collapse_blank_lines(txt)
        except Exception:  # noqa: BLE001 - fall through to stdlib extractor
            pass
    return _stdlib_html_to_text(html)


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "head"}
    _BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "ul", "ol", "table", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _stdlib_html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - never raise from extraction
        return _collapse_blank_lines(re.sub(r"<[^>]+>", " ", html))
    return _collapse_blank_lines(parser.text())


def _collapse_blank_lines(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _looks_like_html(text: str) -> bool:
    head = text[:2048].lower()
    return "<html" in head or "<!doctype html" in head or "<body" in head


def _safe_name(source: str) -> str:
    base = _SAFE_NAME_RE.sub("_", source).strip("_")
    if not base:
        base = "fetched"
    base = base[:120]
    if not base.endswith(".txt"):
        base += ".txt"
    return base


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return this module's tool instances."""
    return [WebFetchTool()]
