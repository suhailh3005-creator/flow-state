"""Opt-in tests against a separately running real Strands Decider service.

Run with FLOW_STATE_RUN_INTEGRATION=1 and a live service configured by
FLOW_STATE_AI_URL. No model is downloaded or launched by this test module.
"""

import os
import unittest

from ai_agent import choose_ai_policy


@unittest.skipUnless(
    os.getenv("FLOW_STATE_RUN_INTEGRATION") == "1",
    "set FLOW_STATE_RUN_INTEGRATION=1 with a live Strands Decider service",
)
class StrandsServiceIntegrationTests(unittest.TestCase):
    def test_real_service_returns_constrained_policy(self):
        decision = choose_ai_policy(
            5.0,
            70.0,
            1.0,
            fallback_enabled=False,
        )
        self.assertIn(decision["policy"], {"BALANCED", "PROTECT_TELEMETRY", "REDUCE_VIDEO", "DEFER_SENSORS"})
        self.assertEqual(decision["source"], "strands_decider")


if __name__ == "__main__":
    unittest.main()
