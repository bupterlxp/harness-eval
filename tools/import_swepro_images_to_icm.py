#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_NAMESPACE = "Harness_evolve"
DEFAULT_REGION = "China-North-LF"
DEFAULT_IMAGE_NAME = "swepro_prebuilt"


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


def slug(value: str, max_len: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower()
    return (text or "unknown")[:max_len]


def stable_tag(instance_id: str, index: int, repo_family: str = "") -> str:
    digest = hashlib.sha1(instance_id.encode("utf-8")).hexdigest()[:12]
    family = slug(repo_family or instance_id, 36)
    return f"swepro-{index:04d}-{family}-{digest}"[:80]


def dockerfile_for(source_image: str, row: dict[str, Any]) -> str:
    labels = {
        "benchmark": "swebench_pro",
        "wrapper_source": "external_prebuilt_swepro_image",
        "instance_id": str(row.get("instance_id") or ""),
        "repo": str(row.get("repo") or ""),
        "repo_family": str(row.get("repo_family") or ""),
    }
    label_lines = []
    for key, value in labels.items():
        safe = value.replace("\\", "\\\\").replace('"', '\\"')
        label_lines.append(f'LABEL {key}="{safe}"')
    return "FROM " + source_image + "\n" + "\n".join(label_lines) + "\n"


def build_payload(
    *,
    namespace: str,
    region: str,
    username: str,
    image_name: str,
    specific_tag: str,
    source_image: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    dockerfile = dockerfile_for(source_image, row)
    return {
        "dockerfile": dockerfile,
        "username": username,
        "name": image_name,
        "reuse_version": False,
        "regions": [region],
        "galaxy_node_id": 0,
        "specific_tag": specific_tag,
        "describe": f"SWE Pro prebuilt image wrapper for {row.get('instance_id', specific_tag)}",
        "image_type": "normal",
        "namespace": namespace,
        "build_arg": [],
        "encoded_content": "",
        "parameter_type": "custom",
        "arch_map": {region: ["x86_64"]},
        "configs": {"x86_64": {"dockerfile_content": dockerfile}},
    }


def post_json(api: str, payload: dict[str, Any], header: str, timeout: int) -> dict[str, Any]:
    req = request.Request(
        api,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": header},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = None
            return {"http_status": resp.status, "body": body, "raw": raw}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        return {"http_status": exc.code, "body": None, "raw": raw, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"http_status": None, "body": None, "raw": "", "error": str(exc)}


def result_ok(result: dict[str, Any]) -> bool:
    body = result.get("body")
    return result.get("http_status") == 200 and isinstance(body, dict) and body.get("code") == 0


def icm_ids(result: dict[str, Any]) -> dict[str, Any]:
    body = result.get("body") if isinstance(result.get("body"), dict) else {}
    data = body.get("data") if isinstance(body, dict) else {}
    versions = data.get("version_list") if isinstance(data, dict) else []
    first_version = versions[0] if isinstance(versions, list) and versions else {}
    return {
        "icm_image_id": data.get("image_id") if isinstance(data, dict) else None,
        "icm_version_id": first_version.get("version_id") if isinstance(first_version, dict) else None,
    }


def platform_row(
    *,
    source_row: dict[str, Any],
    image_name: str,
    specific_tag: str,
    result: dict[str, Any] | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    row = dict(source_row)
    row["icmName"] = image_name
    row["icmVersion"] = specific_tag
    row["imageMeta"] = {
        "imageSid": "",
        "imageVid": "",
        "imageSource": "icm",
        "needBuild": False,
        "icmName": image_name,
        "icmVersion": specific_tag,
    }
    if dry_run:
        row["icm_import_status"] = "dry_run"
    elif result is not None:
        row.update(icm_ids(result))
        row["icm_import_status"] = "success" if result_ok(result) else "failed"
    return row


def load_done(results_path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not results_path.exists():
        return done
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        instance_id = row.get("instance_id")
        if instance_id and row.get("ok"):
            done[str(instance_id)] = row
    return done


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create ICM-visible SWE Pro image versions by wrapping external "
            "prebuilt images with the image-manager dockerfile_based_build API."
        )
    )
    parser.add_argument("--input", type=Path, default=Path("configs/swepro_external_images.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("configs/platform_bmk_instances.swepro.jsonl"))
    parser.add_argument("--results", type=Path, default=Path("logs/icm_swepro_import_results.jsonl"))
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--image-name", default=DEFAULT_IMAGE_NAME)
    parser.add_argument("--username", default=os.environ.get("ICM_USERNAME", "zhangjingyuan.seed"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    api = f"https://image-manager.byted.org/api/v2/images/{args.namespace}/dockerfile_based_build/"
    dry_run = args.dry_run or os.environ.get("ICM_DRY_RUN") == "1"
    header = "" if dry_run else auth_header()
    done = load_done(args.results) if args.resume else {}
    args.results.parent.mkdir(parents=True, exist_ok=True)
    platform_rows: list[dict[str, Any]] = []

    print(f"api={api}")
    print(f"namespace={args.namespace} image_name={args.image_name} rows={len(rows)} dry_run={dry_run}")
    ok = failed = skipped = 0
    mode = "a" if args.resume else "w"
    with args.results.open(mode, encoding="utf-8") as results_handle:
        for offset, source_row in enumerate(rows, args.start_index):
            instance_id = str(source_row.get("instance_id") or f"row-{offset}")
            source_image = str(source_row.get("source_image") or "").strip().lower()
            if not source_image:
                raise SystemExit(f"Missing source_image for {instance_id}")
            tag = stable_tag(instance_id, offset, str(source_row.get("repo_family") or ""))
            if instance_id in done:
                skipped += 1
                prior = done[instance_id]
                platform_rows.append(
                    platform_row(
                        source_row=source_row,
                        image_name=args.image_name,
                        specific_tag=str(prior.get("specific_tag") or tag),
                        result=prior.get("response"),
                    )
                )
                continue
            payload = build_payload(
                namespace=args.namespace,
                region=args.region,
                username=args.username,
                image_name=args.image_name,
                specific_tag=tag,
                source_image=source_image,
                row=source_row,
            )
            print(f"[{offset}/{len(rows)}] {instance_id} <- {source_image} as {args.image_name}:{tag}")
            if dry_run:
                result = {"http_status": 0, "body": {"code": 0, "data": {}}, "raw": "", "dry_run": True}
            else:
                result = post_json(api, payload, header, args.timeout)
            ok_flag = result_ok(result) or dry_run
            if ok_flag:
                ok += 1
            else:
                failed += 1
                print(f"  FAIL http={result.get('http_status')} raw={(result.get('raw') or result.get('error') or '')[:500]}")
            record = {
                "instance_id": instance_id,
                "source_image": source_image,
                "image_name": args.image_name,
                "specific_tag": tag,
                "ok": ok_flag,
                "payload": payload,
                "response": result,
            }
            results_handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            results_handle.flush()
            platform_rows.append(
                platform_row(
                    source_row=source_row,
                    image_name=args.image_name,
                    specific_tag=tag,
                    result=result,
                    dry_run=dry_run,
                )
            )
            if not ok_flag and not dry_run:
                print("Stopping at first failed import. Re-run with --resume after fixing the issue.")
                break
            if args.sleep:
                time.sleep(args.sleep)

    write_jsonl(args.output, platform_rows)
    print(f"wrote results: {args.results}")
    print(f"wrote platform manifest: {args.output}")
    print(f"ok={ok} failed={failed} skipped={skipped}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
