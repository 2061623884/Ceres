"""Check acceptance consistency against the retained completed batch, offline."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import eval_v4 as evaluation
import eval_v4_record as recorder
import eval_v4_judge as judge


class AcceptanceTests(unittest.TestCase):
    def test_incomplete_batch_reaches_acceptance_without_model_calls(self):
        suite = evaluation.read(Path(__file__).parents[1] / "evals/v4/cases.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, tree, index = root / "source", root / "tree", root / "index"
            tree.mkdir()
            index.mkdir()
            entries = [{"execution_id": f"{case['case_id']}-r{repeat}", "case_id": case["case_id"],
                        "core": case["core"], "repeat": repeat, "group": case["group"],
                        "expected_outcome": case.get("expected_outcome", "normal_completion")}
                       for case, repeat in evaluation.schedule(suite["cases"])]
            evaluation.write(source / "manifest.json", {"product_head": evaluation.HEAD, "schedule": entries,
                             "tree": str(tree), "seed": "isolated-seed", "index": str(index), "index_identity": {},
                             "config_identity": {}, "environment_identity": evaluation.environment_identity()})
            for entry, status in zip(entries, ("preparation_failed", "running")):
                result = {**entry, "status": status, "checks": [], "steps": [], "critical_violations": []}
                if status == "preparation_failed":
                    result["performance_passed"] = False
                evaluation.write(source / entry["execution_id"] / "result.json", result)
            summary = evaluation.report(source)
            summary["manifest"] = "obsolete-manifest.json"
            evaluation.write(source / "summary.json", summary)
            diagnostics = root / "diagnostics"
            with patch.object(sys, "argv", ["eval_v4_judge.py", "--source", str(source), "--output", str(diagnostics)]), \
                    patch.object(judge.httpx, "Client") as network, patch.object(evaluation, "load") as product_loader:
                self.assertEqual(judge.main(), 1)  # Unknown diagnostics are recorded, not a model success.
                network.assert_not_called()
                product_loader.assert_not_called()
            self.assertEqual(evaluation.read(diagnostics / "summary.json")["verdicts"]["unknown"], 100)
            (diagnostics / "R03-r1.json").unlink()  # A diagnostic that was never completed must remain unknown.
            ui_path = root / "ui.json"
            evaluation.write(ui_path, {"product_head": evaluation.HEAD, "runtime_identity": {"product_head": evaluation.HEAD},
                             "journeys": [], "automatic_browser_acceptance": "not_passed"})
            output = root / "acceptance"
            with patch.object(sys, "argv", ["eval_v4_record.py", "--source", str(source), "--ui", str(ui_path),
                                            "--diagnostics", str(diagnostics), "--output", str(output)]):
                self.assertEqual(recorder.main(), 0)
            record = evaluation.read(output / "acceptance.json")
            self.assertEqual(record["api"]["counts"]["preparation_failed"], 1)
            self.assertEqual(record["api"]["counts"]["runner_failed"], 1)
            self.assertEqual(record["api"]["counts"]["not_executed"], 98)
            self.assertEqual(record["api"]["actual_executions"], 2)
            self.assertEqual(record["diagnostic_verdicts"]["unknown"], 100)
            self.assertEqual(record["usage"]["diagnostic_judge"]["calls"], 0)
            self.assertEqual(record["automatic_acceptance"], "not_passed")
            self.assertEqual(record["api"]["manifest"], str(source / "manifest.json"))
            self.assertIsNone(record["execution_sha256"]["R03-r1"]["api"])
            self.assertIsNone(record["execution_sha256"]["R03-r1"]["diagnostic"])
            markdown = (output / "acceptance.md").read_text(encoding="utf-8")
            for unsupported_claim in ("下列两条浏览器旅程", "专题成功清单", "本次探针", "原始裁判记录保留",
                                      "UI运行条件与身份见原始UI回执", "诊断保留原始捕获提示"):
                with self.subTest(unsupported_claim=unsupported_claim):
                    self.assertNotIn(unsupported_claim, markdown)

    def test_stale_api_or_ui_summary_cannot_be_archived(self):
        artifacts = Path(__file__).parents[1] / "work/ceres-v4-evaluation"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            shutil.copytree(artifacts / "run-04", source)
            for number, mismatch in enumerate(("api_gate", "api_count", "ui_gate")):
                with self.subTest(mismatch=mismatch):
                    summary = evaluation.read(artifacts / "run-04/summary.json")
                    ui = evaluation.read(artifacts / "ui/run-02/result.json")
                    if mismatch == "api_gate":
                        summary["automatic_acceptance"] = "passed"
                    elif mismatch == "api_count":
                        summary["counts"]["passed"] = 100
                    else:
                        ui["automatic_browser_acceptance"] = "passed"
                    evaluation.write(source / "summary.json", summary)
                    ui_path = root / "ui.json"
                    evaluation.write(ui_path, ui)
                    output = root / f"acceptance-{number}"
                    argv = ["eval_v4_record.py", "--source", str(source), "--ui", str(ui_path),
                            "--diagnostics", str(artifacts / "diagnostics-run03-v3"),
                            "--probe", str(artifacts / "diagnostics-run03"),
                            "--probe", str(artifacts / "diagnostics-run03-v2"), "--output", str(output)]
                    message = "UI summary" if mismatch == "ui_gate" else "API summary"
                    with patch.object(sys, "argv", argv), self.assertRaisesRegex(ValueError, message):
                        recorder.main()
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
