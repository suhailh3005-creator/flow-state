"""Small offline coverage for the live evaluation report format."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from evaluate_live import SCENARIOS, run_evaluation


def mock_response(policy: str, confidence: float):
    response = Mock()
    response.raise_for_status.return_value = None
    choices = ("BALANCED", "PROTECT_TELEMETRY", "REDUCE_VIDEO", "DEFER_SENSORS")
    response.json.return_value = {
        "model": "mock-strands-decider",
        "answers": {
            "policy": {
                "type": "choice",
                "choice": policy,
                "confidence": confidence,
                "probabilities": {choice: float(choice == policy) for choice in choices},
            }
        },
        "usage": {"input_tokens": 10, "output_tokens": 0},
    }
    return response


class LiveEvaluationReportTests(unittest.TestCase):
    def test_serializes_fixed_matrix_and_keeps_emergency_recommendation_separate(self):
        policies = ("BALANCED", "PROTECT_TELEMETRY", "DEFER_SENSORS", "BALANCED")
        post = Mock(side_effect=[mock_response(policy, 0.8) for policy in policies])
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "evaluation.json"
            report, report_path, complete = run_evaluation(
                output,
                http_post=post,
                require_real_service=False,
            )
            saved = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertTrue(complete)
        self.assertEqual(report_path, output)
        self.assertEqual(saved, report)
        self.assertEqual([row["scenario"] for row in saved["scenarios"]], [s["name"] for s in SCENARIOS])
        self.assertEqual(post.call_count, len(SCENARIOS))
        for row in saved["scenarios"]:
            self.assertIn("inputs", row)
            self.assertIn("baseline_recommendation", row)
            self.assertIn("simulated_metrics", row)
            self.assertIn("request_latency_ms", row)
            self.assertIn("error", row)
        emergency = saved["scenarios"][-1]
        self.assertEqual(emergency["model_recommendation"], "BALANCED")
        self.assertEqual(emergency["final_policy"], "REDUCE_VIDEO")
        self.assertTrue(emergency["safety_override"])

    def test_service_failure_records_baseline_and_stops_extra_requests(self):
        post = Mock(side_effect=requests.ConnectionError("service offline"))
        with tempfile.TemporaryDirectory() as temp_dir:
            report, _, complete = run_evaluation(
                Path(temp_dir) / "failed.json",
                http_post=post,
            )
        self.assertFalse(complete)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(report["scenarios"][0]["fallback_used"])
        self.assertIn("service offline", report["scenarios"][0]["error"])
        self.assertTrue(all(row["status"] == "not_attempted" for row in report["scenarios"][1:]))


if __name__ == "__main__":
    unittest.main()
