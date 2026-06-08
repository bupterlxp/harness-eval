from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from harness_scaffold.adapters.cli import run_cli


def _load_manifest(root: Path) -> dict:
    for name in ("scaffold_manifest.json", "harness_scaffold_manifest.json"):
        path = root / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {"program": "generated_program.py"}


def _relative_artifact(artifacts: dict, name: str, fallback: str) -> str:
    item = artifacts.get(name) or {}
    path = item.get("path") if isinstance(item, dict) else None
    return Path(path).name if path else fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold-native generated harness wrapper")
    parser.add_argument("positional_prompt", nargs="*", help="Optional prompt words")
    parser.add_argument("-p", "--prompt", default=None)
    parser.add_argument("--workdir", "--work-dir", "--workspace", dest="workdir", default=".")
    parser.add_argument("--output-dir", "--output", dest="output_dir", required=True)
    parser.add_argument("--max-steps", "--max-turns", dest="max_steps", default=None)
    parser.add_argument("--model-name", default=None)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(root)
    program = (root / str(manifest.get("program") or "generated_program.py")).resolve()
    prompt = args.prompt or " ".join(args.positional_prompt).strip()

    task_json = out_dir / "task.json"
    config_json = out_dir / "config.json"
    task_json.write_text(
        json.dumps(
            {
                "task_id": "generated-harness-task",
                "prompt": prompt,
                "workdir": str(Path(args.workdir).resolve()),
                "metadata": {"adapter": "scaffold_native_wrapper"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    policy = {"allow_network": True}
    if args.max_steps:
        try:
            policy["max_steps"] = int(args.max_steps)
        except ValueError:
            policy["max_steps"] = args.max_steps
    config: dict = {"policy": policy, "include_optional_tools": True}
    model_name = args.model_name or os.environ.get("MODEL_NAME")
    if model_name:
        llm_config = {
            "provider": "openai_like",
            "model": model_name,
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        }
        if os.environ.get("OPENAI_API_KEY"):
            llm_config["api_key"] = os.environ["OPENAI_API_KEY"]
        config["llm"] = llm_config
    config_json.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    exit_code = run_cli(
        [
            "--task-json",
            str(task_json),
            "--program",
            str(program),
            "--out-dir",
            str(out_dir),
            "--config",
            str(config_json),
        ]
    )
    metadata_path = out_dir / "metadata.json"
    result_path = out_dir / "result.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        artifacts = metadata.get("manifest", {}).get("artifacts", {})
        result = {
            "status": metadata.get("status", "failed"),
            "trajectory": "trajectory.jsonl",
            "answer_path": _relative_artifact(artifacts, "answer.md", "answer.md"),
            "evidence_path": _relative_artifact(artifacts, "evidence.json", "evidence.json"),
            "sources_path": _relative_artifact(artifacts, "sources.json", "sources.json"),
            "metrics": {
                "steps": metadata.get("steps"),
                "trajectory_events": metadata.get("trajectory_events"),
            },
            "errors": metadata.get("error"),
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
