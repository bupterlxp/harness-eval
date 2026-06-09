from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from creation_eval.agent_cli import read_harness_response, run_agent_cli


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class AgentCliTests(unittest.TestCase):
    def test_runs_standard_harness_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact"
            output = root / "out"
            write(artifact / "harness" / "__init__.py", "")
            write(
                artifact / "harness" / "__main__.py",
                """
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run")
    run.add_argument("--task-json", required=True)
    run.add_argument("--model-config", required=True)
    run.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.command != "run":
        parser.error("expected run")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    task = json.loads(Path(args.task_json).read_text())
    (out / "response.md").write_text("handled: " + task["prompt"])
    (out / "metadata.json").write_text(json.dumps({"usage": {"input_tokens": 3, "output_tokens": 4}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
            )

            result = run_agent_cli(
                artifact,
                "code",
                "fix this repo",
                output,
                python_bin=sys.executable,
                timeout=30,
            )

            self.assertEqual(result.status, "success")
            self.assertEqual(read_harness_response(result), "handled: fix this repo")
            self.assertEqual(result.harness_run_tokens, 7)

    def test_missing_harness_package_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_agent_cli(
                root / "artifact",
                "code",
                "fix this repo",
                root / "out",
                python_bin=sys.executable,
                timeout=30,
            )

            self.assertEqual(result.status, "harness_failed")
            self.assertIn("missing harness", result.error)


if __name__ == "__main__":
    unittest.main()
