"""Tests for the deterministic, no-service evaluation report."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evaluate_offline import build_report


class OfflineEvaluationTests(unittest.TestCase):
    def test_report_is_repeatable_and_covers_all_four_scenarios(self):
        report = build_report()
        self.assertEqual(report, build_report())
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(
            [row["scenario"] for row in report["scenarios"]],
            ["Normal", "Moderate", "Severe", "Emergency"],
        )
        self.assertEqual(
            [row["policy"] for row in report["scenarios"]],
            ["BALANCED", "PROTECT_TELEMETRY", "DEFER_SENSORS", "REDUCE_VIDEO"],
        )
        self.assertTrue(all("simulated_metrics" in row for row in report["scenarios"]))

    def test_cli_writes_json_to_requested_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reports" / "evaluation.json"
            subprocess.run(
                [sys.executable, "scripts/evaluate_offline.py", "--output", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), build_report())


if __name__ == "__main__":
    unittest.main()
