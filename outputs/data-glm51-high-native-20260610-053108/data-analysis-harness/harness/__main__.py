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

    parser.add_argument("-p", "--prompt", default=None)
    parser.add_argument("positional_prompt", nargs="*", help="Optional prompt words")
    parser.add_argument("--workdir", "--work-dir", "--workspace", dest="workdir", default=".")
    parser.add_argument("--output-dir", "--output", dest="output_dir", default=None)
    parser.add_argument("--max-steps", "--max-turns", dest="max_steps", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--task-json", default=None)
    parser.add_argument("--model-config", default=None)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if not args.output_dir:
        print("Error: --output-dir is required", file=sys.stderr)
        return 1
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(root)
    program = (root / str(manifest.get("program") or "generated_program.py")).resolve()

    if args.task_json:
        # Direct task-json mode (equivalent to old "run" subcommand)
        task_json = Path(args.task_json).resolve()
        config_json = Path(args.model_config).resolve() if args.model_config else out_dir / "config.json"
        if not config_json.exists():
            config_json.write_text(json.dumps({"policy": {}, "include_optional_tools": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        prompt = args.prompt or " ".join(args.positional_prompt).strip()
        if not prompt:
            print("Error: a task prompt is required (-p or positional)", file=sys.stderr)
            return 1
        task_json = out_dir / "task.json"
        config_json = out_dir / "config.json"
        task_json.write_text(
            json.dumps(
                {
                    "task_id": "generated-harness-task",
                    "prompt": prompt,
                    "workdir": str(Path(args.workdir).resolve()),
                    "metadata": {"wrapper": "scaffold_native_cli"},
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

        # Build LLM config from environment or --model-name
        config: dict = {"policy": policy, "include_optional_tools": True}
        model_name = args.model_name or os.environ.get("MODEL_NAME", "")
        if model_name:
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            api_key = os.environ.get("OPENAI_API_KEY", "")
            config["llm"] = {
                "provider": "openai_like",
                "model": model_name,
                "base_url": base_url,
                "api_key": api_key,
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
