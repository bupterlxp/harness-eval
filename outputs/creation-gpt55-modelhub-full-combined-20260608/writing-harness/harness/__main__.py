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
    policy = {}
    if args.max_steps:
        try:
            policy["max_steps"] = int(args.max_steps)
        except ValueError:
            policy["max_steps"] = args.max_steps
    config = {"policy": policy, "include_optional_tools": True}
    model_name = args.model_name or os.environ.get("MODEL_NAME")
    api_key = os.environ.get("OPENAI_API_KEY")
    if model_name and api_key:
        config["llm"] = {
            "provider": "openai_like",
            "model": model_name,
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key_env": "OPENAI_API_KEY",
        }
    config_json.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return run_cli(
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


if __name__ == "__main__":
    raise SystemExit(main())
