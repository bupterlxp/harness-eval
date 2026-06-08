#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_NAMESPACE = "Harness_evolve"
DEFAULT_VERSION_ENDPOINTS = [
    "https://image-manager.byted.org/api/v1/images/{image_id}/versions/{version_id}/",
    "https://image-manager.byted.org/api/v2/images/{namespace}/versions/{version_id}/",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSONL: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def auth_header() -> str:
    header = os.environ.get("ICM_BASIC_AUTH", "").strip()
    if header:
        return header if header.lower().startswith("basic ") else f"Basic {header}"
    user = os.environ.get("ICM_USERNAME", "").strip()
    password = os.environ.get("ICM_PASSWORD", "")
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {token}"
    raise SystemExit("Missing ICM auth. Set ICM_BASIC_AUTH or ICM_USERNAME/ICM_PASSWORD.")


def load_mapping(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    rows = read_jsonl(path)
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        image_vid = str(row.get("imageVid") or row.get("image_vid") or row.get("vid") or "").strip()
        if not image_vid:
            continue
        image_sid = str(row.get("imageSid") or row.get("image_sid") or row.get("sid") or "").strip()
        payload = {"imageVid": image_vid, "imageSid": image_sid}
        for key_name in ("instance_id", "icm_version_id", "version_id", "icmVersion", "icm_version", "source_image"):
            value = row.get(key_name)
            if value is not None and str(value).strip():
                mapping[str(value).strip()] = payload
        image_id = row.get("icm_image_id") or row.get("image_id")
        version_id = row.get("icm_version_id") or row.get("version_id")
        if image_id is not None and version_id is not None:
            mapping[f"{image_id}:{version_id}"] = payload
    return mapping


def lookup_mapping(row: dict[str, Any], mapping: dict[str, dict[str, str]]) -> tuple[str | None, str | None, str | None]:
    keys = [
        row.get("instance_id"),
        row.get("icm_version_id"),
        row.get("version_id"),
        row.get("icmVersion"),
        row.get("icm_version"),
        row.get("source_image"),
    ]
    image_id = row.get("icm_image_id") or row.get("image_id")
    version_id = row.get("icm_version_id") or row.get("version_id")
    if image_id is not None and version_id is not None:
        keys.insert(0, f"{image_id}:{version_id}")
    for key in keys:
        if key is None:
            continue
        value = mapping.get(str(key).strip())
        if value:
            return value.get("imageVid"), value.get("imageSid"), f"mapping:{key}"
    return None, None, None


def extract_image_vid(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key in ("imageVid", "image_vid", "imageVID"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        # Platform API often uses plain "vid"; keep this behind explicit image-ish context.
        for key in ("vid", "image_version_vid", "version_vid"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            found = extract_image_vid(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = extract_image_vid(value)
            if found:
                return found
    return None


def get_json(url: str, header: str, timeout: int) -> dict[str, Any]:
    req = request.Request(url, headers={"Authorization": header, "Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            body = json.loads(raw) if raw else None
            return {"ok": True, "http_status": resp.status, "body": body, "raw": raw[:2000]}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return {"ok": False, "http_status": exc.code, "body": None, "raw": raw[:2000], "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "http_status": None, "body": None, "raw": "", "error": str(exc)}


def resolve_from_api(
    row: dict[str, Any],
    *,
    namespace: str,
    endpoints: list[str],
    header: str,
    timeout: int,
) -> tuple[str | None, dict[str, Any]]:
    image_id = row.get("icm_image_id") or row.get("image_id")
    version_id = row.get("icm_version_id") or row.get("version_id")
    if image_id is None or version_id is None:
        return None, {"error": "missing icm_image_id/icm_version_id"}
    attempts = []
    for endpoint in endpoints:
        url = endpoint.format(image_id=image_id, version_id=version_id, namespace=namespace)
        result = get_json(url, header, timeout)
        body = result.get("body")
        image_vid = extract_image_vid(body)
        attempts.append(
            {
                "url": url,
                "http_status": result.get("http_status"),
                "ok": result.get("ok"),
                "found_image_vid": bool(image_vid),
                "error": result.get("error"),
                "raw": result.get("raw"),
            }
        )
        if image_vid:
            return image_vid, {"method": "api", "url": url, "attempts": attempts}
    return None, {"error": "imageVid not found in API responses", "attempts": attempts}


def direct_row(row: dict[str, Any], image_vid: str, source: str, image_sid: str = "") -> dict[str, Any]:
    out = dict(row)
    out["imageVid"] = image_vid
    if image_sid:
        out["imageSid"] = image_sid
    out["imageSource"] = "vid"
    out["needBuild"] = False
    out["icmName"] = ""
    out["icmVersion"] = ""
    out["imageMeta"] = {
        "imageSid": image_sid,
        "imageVid": image_vid,
        "imageSource": "vid",
        "needBuild": False,
        "icmName": "",
        "icmVersion": "",
    }
    out["platform_image_resolution"] = {"status": "resolved", "source": source}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve ICM-imported SWE Pro images to direct Seed runnable imageVid rows. "
            "The output manifest is safe for platform-native jobs only when all rows resolve."
        )
    )
    parser.add_argument("--input", type=Path, default=Path("configs/platform_bmk_instances.swepro.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("configs/platform_bmk_instances.swepro.vid.jsonl"))
    parser.add_argument("--failures", type=Path, default=Path("logs/platform_jobs/swepro_image_vid_resolution_failures.jsonl"))
    parser.add_argument("--mapping", type=Path, default=None, help="Optional JSONL with imageVid mappings keyed by instance_id/version_id.")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--endpoint", action="append", default=None, help="Extra endpoint template with {image_id}, {version_id}, {namespace}.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--allow-partial", action="store_true", help="Write resolved subset even if some rows fail.")
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    mapping = load_mapping(args.mapping)
    endpoints = (args.endpoint or []) + DEFAULT_VERSION_ENDPOINTS
    header: str | None = None
    resolved: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for index, row in enumerate(rows, 1):
        instance_id = row.get("instance_id") or f"row-{index}"
        image_vid, image_sid, source = lookup_mapping(row, mapping)
        detail: dict[str, Any] = {}
        if not image_vid:
            if header is None:
                header = auth_header()
            image_vid, detail = resolve_from_api(row, namespace=args.namespace, endpoints=endpoints, header=header, timeout=args.timeout)
            image_sid = ""
            source = detail.get("method") or "api"
        if image_vid:
            resolved.append(direct_row(row, image_vid, str(source), image_sid or ""))
            print(f"[resolved] {index}/{len(rows)} {instance_id} imageVid={image_vid}")
        else:
            failure = {
                "row_index": index,
                "instance_id": instance_id,
                "icm_image_id": row.get("icm_image_id") or row.get("image_id"),
                "icm_version_id": row.get("icm_version_id") or row.get("version_id"),
                "icmName": row.get("icmName") or row.get("icm_name"),
                "icmVersion": row.get("icmVersion") or row.get("icm_version"),
                "detail": detail,
            }
            failures.append(failure)
            print(f"[unresolved] {index}/{len(rows)} {instance_id}", file=sys.stderr)

    if failures:
        write_jsonl(args.failures, failures)
        print(f"Wrote {len(failures)} failures to {args.failures}", file=sys.stderr)
        if not args.allow_partial:
            print(
                f"Resolved {len(resolved)}/{len(rows)} rows. Refusing to write full direct-image manifest "
                "because unresolved rows remain. Use --allow-partial only for debugging/probe subsets.",
                file=sys.stderr,
            )
            return 2

    write_jsonl(args.output, resolved)
    print(f"Wrote {len(resolved)} direct-image rows to {args.output}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
