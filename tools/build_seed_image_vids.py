#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any
from urllib import error, request


CREATE_URL = "https://seed.bytedance.net/api/training/image/create"
BUILD_URL = "https://seed.bytedance.net/api/training/image/version/build"
GET_URL = "https://seed.bytedance.net/api/training/image/version/get"
JWT_URL = "https://cloud.bytedance.net/auth/api/v1/jwt"


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


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("ok") and row.get("instance_id"):
            done.add(str(row["instance_id"]))
    return done


def get_xjwt() -> str:
    explicit = os.environ.get("SEED_X_JWT", "").strip()
    if explicit:
        return explicit
    token_path = os.environ.get("SEC_TOKEN_PATH") or "/etc/tce_dynamic/identity.token"
    if not Path(token_path).exists():
        raise SystemExit("Missing Seed auth. Set SEED_X_JWT or run on a machine with SEC_TOKEN_PATH.")
    zti = Path(token_path).read_text(encoding="utf-8").strip()
    req = request.Request(JWT_URL, headers={"X-ZTI-Token": zti})
    with request.urlopen(req, timeout=30) as resp:
        xjwt = resp.headers.get("x-jwt-token")
    if not xjwt:
        raise SystemExit("JWT request succeeded but x-jwt-token header is missing")
    return xjwt


def post_json(url: str, payload: dict[str, Any], xjwt: str, timeout: int = 60) -> tuple[int, dict[str, Any] | None, str]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-jwt-token": xjwt},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw) if raw else None, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return exc.code, None, raw


def find_image_versions(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    root = body.get("result") or body.get("data") or body
    if not isinstance(root, dict):
        return []
    versions = root.get("image_version") or root.get("image_versions") or root.get("versions") or []
    return versions if isinstance(versions, list) else []


def region_status(version: dict[str, Any]) -> tuple[str | None, str | None]:
    infos = version.get("image_region_info") or version.get("region_info") or []
    if isinstance(infos, list) and infos:
        info = infos[0]
        if isinstance(info, dict):
            return str(info.get("status") or ""), str(info.get("status_desc") or "")
    return None, None


def create_seed_image(xjwt: str, image_name: str) -> str:
    status, body, raw = post_json(CREATE_URL, {"image_name": image_name, "is_official": False, "is_public": False}, xjwt)
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"failed to create Seed image {image_name}: HTTP {status} {raw[:500]}")
    image = (body.get("result") or {}).get("image") or body.get("image") or body.get("data") or {}
    sid = image.get("sid") or image.get("image_sid") or image.get("id")
    if not sid:
        raise SystemExit(f"failed to parse sid from create response: {raw[:1000]}")
    return str(sid)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Seed direct image versions from internally mirrored SWE Pro images.")
    parser.add_argument("--input", type=Path, default=Path("logs/platform_jobs/swepro_internal_images.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("logs/platform_jobs/swepro_seed_imagevid_mapping.jsonl"))
    parser.add_argument("--seed-image-name", default="swepro_direct_full")
    parser.add_argument("--sid", default=os.environ.get("SEED_IMAGE_SID", ""))
    parser.add_argument("--region", default="China-North-LF")
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1, help="Number of image versions to build/poll concurrently.")
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--poll-timeout", type=float, default=1800.0)
    args = parser.parse_args()

    rows = [row for row in read_jsonl(args.input) if row.get("ok")]
    indexed_rows = [(i, row) for i, row in enumerate(rows, 1) if i >= args.start_index]
    if args.limit is not None:
        indexed_rows = indexed_rows[: args.limit]
    done = load_done(args.output) if args.resume else set()
    xjwt = get_xjwt()
    sid = args.sid.strip() or create_seed_image(xjwt, args.seed_image_name)
    print(f"seed_image_sid={sid}", flush=True)
    write_lock = Lock()

    def write_result(result: dict[str, Any]) -> None:
        with write_lock:
            append_jsonl(args.output, result)

    def build_one(index: int, row: dict[str, Any], total_rows: int, concurrent: bool = False) -> dict[str, Any]:
        instance_id = str(row.get("instance_id") or f"row-{index}")
        if instance_id in done:
            print(f"[skip] {index}/{len(rows)} {instance_id}", flush=True)
            return {"ok": True, "skipped": True, "instance_id": instance_id}
        source = str(row.get("internal_image_url") or "").strip()
        if not source:
            result = {"ok": False, "instance_id": instance_id, "error": "missing internal_image_url"}
            write_result(result)
            return result
        tag = str(row.get("target_tag") or f"swepro-{index:04d}")
        payload = {
            "sid": sid,
            "image_description": f"SWE Pro direct image for {instance_id}",
            "base_image": {"base_image_url": source, "base_image_type": "icm", "base_image_vid": ""},
            "build_method": "normal",
            "region": [args.region],
            "image_name": tag,
            "archs": [args.arch],
            "is_sync": False,
        }
        print(f"[build] {index}/{total_rows} {instance_id}", flush=True)
        status, body, raw = post_json(BUILD_URL, payload, xjwt)
        result: dict[str, Any] = {
            "ok": False,
            "instance_id": instance_id,
            "internal_image_url": source,
            "seed_image_sid": sid,
            "seed_image_name": args.seed_image_name,
            "target_tag": tag,
            "build_http_status": status,
        }
        if status != 200:
            result["build_raw"] = raw[:4000]
            write_result(result)
            print(f"[build-fail] {instance_id}", flush=True)
            return result

        deadline = time.time() + args.poll_timeout
        last_version: dict[str, Any] | None = None
        while time.time() < deadline:
            time.sleep(args.poll_interval)
            get_payload = {"sid": sid, "limit": 50, "offset": 0, "show_disabled": True, "check_status_async": True}
            status, body, raw = post_json(GET_URL, get_payload, xjwt)
            versions = find_image_versions(body)
            match = None
            for version in versions:
                if str(version.get("image_name") or version.get("name") or version.get("tag") or "") == tag:
                    match = version
                    break
            if match is None and versions and not concurrent:
                # Seed currently returns newest first; use it as fallback for one-at-a-time builds.
                match = versions[0]
            if not match:
                continue
            last_version = match
            vid = match.get("vid") or match.get("imageVid") or match.get("image_vid")
            status_text, status_desc = region_status(match)
            print(f"  poll status={status_text} vid={vid}", flush=True)
            if vid and status_text == "OK":
                result.update(
                    {
                        "ok": True,
                        "imageVid": vid,
                        "imageSid": sid,
                        "region_status": status_text,
                        "status_desc": status_desc,
                    }
                )
                write_result(result)
                print(f"[ok] {instance_id} imageVid={vid}", flush=True)
                return result
            if status_text and status_text.upper() in {"FAIL", "FAILED"}:
                result.update({"region_status": status_text, "status_desc": status_desc, "version": match})
                write_result(result)
                print(f"[seed-fail] {instance_id}", flush=True)
                return result
        else:
            result.update({"error": "poll_timeout", "last_version": last_version})
            write_result(result)
            print(f"[timeout] {instance_id}", flush=True)
            return result

        return result

    concurrency = max(1, args.concurrency)
    if concurrency == 1:
        for index, row in indexed_rows:
            build_one(index, row, len(rows), concurrent=False)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(build_one, index, row, len(rows), True)
                for index, row in indexed_rows
                if str(row.get("instance_id") or f"row-{index}") not in done
            ]
            for future in as_completed(futures):
                future.result()

    return 0


if __name__ == "__main__":
    sys.exit(main())
