from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from creation_eval.pre_bmk_validation.artifact_contracts import validate_domain_artifacts
from creation_eval.pre_bmk_validation.validator import (
    _check_data,
    find_cached_pre_bmk_report,
)
from creation_eval.schema import HarnessArtifact


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PublicContractValidatorTests(unittest.TestCase):
    def test_mle_bool_submission_passes_and_probability_submission_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(work / "sample_submission.csv", "PassengerId,Transported\n1,True\n2,False\n")
            write(out / "REPORT.md", "Mean value 1.2 and count 2.")
            write(out / "submission.csv", "PassengerId,Transported\n1,0.7\n2,0.1\n")

            failed = validate_domain_artifacts("data_analysis", work, out)
            self.assertFalse(failed.passed)
            self.assertIn("True/False", "\n".join(failed.failures))

            write(out / "submission.csv", "PassengerId,Transported\n1,True\n2,False\n")
            passed = validate_domain_artifacts("data_analysis", work, out)
            self.assertTrue(passed.passed)

    def test_writing_rejects_log_only_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "response.md", "status metadata trajectory stdout stderr tool_call cli_status " * 12)
            result = validate_domain_artifacts("writing", work, out)
            self.assertFalse(result.passed)

    def test_data_rejects_template_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "REPORT.md", "This is a template report. TODO fill computed results later.")
            result = validate_domain_artifacts("data_analysis", work, out)
            self.assertFalse(result.passed)

    def test_data_toy_gate_does_not_require_chart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "REPORT.md", "Average salary 88666.7 and average performance 4.3.")
            write(out / "submission.csv", "PassengerId,Transported\n1,True\n2,False\n")
            result = _check_data(work, out)
            self.assertTrue(result["passed"])
            self.assertFalse(result["chart_required"])
            self.assertFalse(result["chart_exists"])

    def test_find_cached_pre_bmk_report_prefers_artifact_root_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_root = root / "data-analysis-harness"
            report = artifact_root / "_pre_bmk_validation" / "pre_bmk_validation.json"
            write(artifact_root / "meta.json", '{"task_id":"data-analysis-harness"}')
            write(report, '{"gate":{"passed":true}}')
            artifact = HarnessArtifact(
                path=artifact_root,
                task_id="data-analysis-harness",
                domain="data_analysis",
                generation_model="test",
            )
            self.assertEqual(find_cached_pre_bmk_report(artifact), report.resolve())

    def test_code_requires_diff_and_verifier_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "result.json", '{"status":"success"}')
            result = validate_domain_artifacts("code", work, out)
            self.assertFalse(result.passed)
            self.assertGreaterEqual(len(result.failures), 2)

    def test_research_requires_evidence_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "answer.md", "A plausible answer without evidence.")
            result = validate_domain_artifacts("research", work, out)
            self.assertFalse(result.passed)

    def test_browser_requires_action_and_final_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            out = root / "out"
            work.mkdir()
            out.mkdir()
            write(out / "result.json", '{"status":"success"}')
            result = validate_domain_artifacts("browser", work, out)
            self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
