from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from creation_eval.benchmarks import _classify_mle_grade_report, _sum_interactions
from creation_eval.schema import HarnessRunResult
from creation_eval.token_usage import extract_harness_interactions


class ClassifyMleGradeReportTests(unittest.TestCase):
    def test_numeric_valid_submission_is_success(self) -> None:
        status, score = _classify_mle_grade_report({"score": 0.5, "valid_submission": True})
        self.assertEqual(status, "success")
        self.assertEqual(score, 0.5)

    def test_invalid_submission_is_not_success(self) -> None:
        status, score = _classify_mle_grade_report({"score": None, "valid_submission": False})
        self.assertEqual(status, "failed/invalid_submission")
        self.assertIsNone(score)

    def test_nan_score_is_not_success(self) -> None:
        status, score = _classify_mle_grade_report({"score": math.nan, "valid_submission": True})
        self.assertEqual(status, "failed/non_numeric_score")
        self.assertIsNone(score)

    def test_null_score_with_valid_submission_is_not_success(self) -> None:
        status, score = _classify_mle_grade_report({"score": None, "valid_submission": True})
        self.assertEqual(status, "failed/non_numeric_score")
        self.assertIsNone(score)

    def test_string_score_is_parsed(self) -> None:
        status, score = _classify_mle_grade_report({"score": "0.75", "valid_submission": True})
        self.assertEqual(status, "success")
        self.assertEqual(score, 0.75)


class SumInteractionsTests(unittest.TestCase):
    def test_all_unknown_stays_unknown(self) -> None:
        results = [HarnessRunResult(status="success"), HarnessRunResult(status="failed")]
        self.assertIsNone(_sum_interactions(results))

    def test_known_values_are_summed_and_unknown_skipped(self) -> None:
        results = [
            HarnessRunResult(status="success", interactions=3),
            HarnessRunResult(status="success"),
            HarnessRunResult(status="failed", interactions=2),
        ]
        self.assertEqual(_sum_interactions(results), 5)

    def test_empty_list_is_unknown(self) -> None:
        self.assertIsNone(_sum_interactions([]))


class ExtractHarnessInteractionsTests(unittest.TestCase):
    def test_explicit_counter_in_result_json_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "result.json").write_text(json.dumps({"llm_calls": 7}), encoding="utf-8")
            (root / "trajectory.jsonl").write_text(
                "\n".join(json.dumps({"type": "llm_call"}) for _ in range(3)),
                encoding="utf-8",
            )
            self.assertEqual(extract_harness_interactions(root), 7)

    def test_trajectory_llm_call_events_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"type": "llm_call", "step": 1},
                {"type": "llm_result", "step": 1},
                {"type": "tool_call", "step": 2},
                {"type": "llm_call", "step": 3},
            ]
            (root / "trajectory.jsonl").write_text(
                "\n".join(json.dumps(event) for event in events),
                encoding="utf-8",
            )
            self.assertEqual(extract_harness_interactions(root), 2)

    def test_no_sources_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(extract_harness_interactions(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
