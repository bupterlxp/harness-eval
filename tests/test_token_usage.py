from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from creation_eval.token_usage import extract_harness_token_usage


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TokenUsageExtractionTests(unittest.TestCase):
    def test_extracts_scaffold_metadata_usage_from_harness_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            write(root / "harness_result.json", f'{{"artifacts_dir": "{artifacts}"}}')
            write(artifacts / "metadata.json", '{"usage": {"input_tokens": 10, "output_tokens": 5}}')

            usage = extract_harness_token_usage(root / "harness_result.json")

            self.assertEqual(usage["total_tokens"], 15)
            self.assertEqual(usage["input_tokens"], 10)
            self.assertEqual(usage["output_tokens"], 5)
            self.assertIn("metadata.json", usage["source_files"][0])

    def test_sums_trajectory_usage_when_metadata_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "trajectory.jsonl",
                "\n".join(
                    [
                        '{"type": "llm_result", "usage": {"prompt_tokens": 7, "completion_tokens": 3}}',
                        '{"type": "llm_result", "usage": {"input_tokens": 11, "output_tokens": 2}}',
                    ]
                )
                + "\n",
            )

            usage = extract_harness_token_usage(root)

            self.assertEqual(usage["total_tokens"], 23)
            self.assertEqual(usage["input_tokens"], 18)
            self.assertEqual(usage["output_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
