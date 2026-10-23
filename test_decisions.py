"""Automated tests for the deterministic FLOW STATE policy baseline."""

import unittest

from decisions import POLICIES, choose_policy
from simulator import run_simulation


class BaselineDecisionTests(unittest.TestCase):
    CASES = (
        ("Normal", 5.0, 70, 1, False, "BALANCED"),
        ("Moderate", 2.0, 180, 5, False, "PROTECT_TELEMETRY"),
        ("Severe", 0.5, 350, 15, False, "DEFER_SENSORS"),
        ("Emergency", 1.5, 220, 6, True, "REDUCE_VIDEO"),
    )

    def test_evaluation_scenario_baseline_outputs(self):
        for name, bandwidth, latency, loss, emergency, expected in self.CASES:
            with self.subTest(scenario=name):
                result = choose_policy(bandwidth, latency, loss, emergency)
                self.assertEqual(result["policy"], expected)
                self.assertEqual(result["actions"], POLICIES[expected])

    def test_emergency_policy_preserves_telemetry(self):
        result = choose_policy(0, 0, 100, True)
        self.assertEqual(result["policy"], "REDUCE_VIDEO")
        self.assertEqual(result["actions"]["telemetry"], "high_priority")

    def test_seeded_simulation_is_repeatable(self):
        self.assertEqual(run_simulation(steps=12, seed=42), run_simulation(steps=12, seed=42))


if __name__ == "__main__":
    unittest.main()
