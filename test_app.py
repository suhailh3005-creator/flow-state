"""Headless Streamlit smoke and rerun tests."""

import unittest
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest


class DashboardTests(unittest.TestCase):
    @staticmethod
    def choice_response(policy, confidence):
        response = Mock()
        response.raise_for_status.return_value = None
        probabilities = {name: 0.0 for name in (
            "BALANCED", "PROTECT_TELEMETRY", "REDUCE_VIDEO", "DEFER_SENSORS"
        )}
        probabilities[policy] = 1.0
        response.json.return_value = {
            "model": "mock-strands-decider",
            "answers": {
                "policy": {
                    "type": "choice",
                    "choice": policy,
                    "confidence": confidence,
                    "probabilities": probabilities,
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }
        return response

    def test_dashboard_starts_in_baseline_mode(self):
        app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("BALANCED" in item.value for item in app.subheader))
        self.assertTrue(any("Decision source: deterministic baseline" in item.value for item in app.info))

    def test_ai_is_requested_only_on_submit_and_reused_on_other_reruns(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "model": "strands-decider-2B-qwen3.5-v1-2610",
            "answers": {
                "policy": {
                    "type": "choice",
                    "choice": "BALANCED",
                    "confidence": 0.91,
                    "probabilities": {
                        "BALANCED": 0.91,
                        "PROTECT_TELEMETRY": 0.03,
                        "REDUCE_VIDEO": 0.03,
                        "DEFER_SENSORS": 0.03,
                    },
                }
            },
            "usage": {"input_tokens": 20, "output_tokens": 0},
        }
        app = AppTest.from_file("app.py").run()
        with patch("requests.post", return_value=response) as post:
            app.segmented_control(key="flow_state_decision_mode").set_value("Strands Decider AI")
            app.button[1].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(post.call_count, 1)
            self.assertTrue(any("Strands Decider inference" in item.value for item in app.info))
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(post.call_count, 1)
            app.slider(key="flow_state_bandwidth").set_value(6.0)
            app.button[1].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.kwargs["json"]["state"]["bandwidth_mbps"], 6.0)

    def test_failed_ai_request_is_shown_as_fallback_with_diagnostics(self):
        app = AppTest.from_file("app.py").run()
        with patch("requests.post", side_effect=requests.ConnectionError("service offline")):
            app.segmented_control(key="flow_state_decision_mode").set_value("Strands Decider AI")
            app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Could not connect to the AI service" in item.value for item in app.warning))
        self.assertTrue(any("ConnectionError: service offline" in item.value for item in app.code))
        self.assertFalse(any("AI service responded" in item.value for item in app.info))

    def test_model_baseline_disagreement_and_low_confidence_are_visible(self):
        app = AppTest.from_file("app.py").run()
        with patch("requests.post", return_value=self.choice_response("DEFER_SENSORS", 0.12)):
            app.segmented_control(key="flow_state_decision_mode").set_value("Strands Decider AI")
            app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Model recommendation: DEFER_SENSORS" in item.value for item in app.caption))
        self.assertTrue(any("differs from deterministic baseline (BALANCED)" in item.value for item in app.warning))
        self.assertTrue(any(item.value == 12 for item in app.progress))
        self.assertTrue(any("no cutoff is applied" in item.value for item in app.caption))

    def test_emergency_override_is_distinguished_from_model_recommendation(self):
        app = AppTest.from_file("app.py").run()
        with patch("requests.post", return_value=self.choice_response("BALANCED", 0.01)):
            app.segmented_control(key="flow_state_decision_mode").set_value("Strands Decider AI")
            app.checkbox(key="flow_state_emergency").set_value(True)
            app.button[1].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("REDUCE_VIDEO" in item.value for item in app.subheader))
        self.assertTrue(any("Model recommendation: BALANCED" in item.value for item in app.caption))
        self.assertTrue(any("Deterministic emergency override selected REDUCE_VIDEO" in item.value for item in app.warning))


if __name__ == "__main__":
    unittest.main()
