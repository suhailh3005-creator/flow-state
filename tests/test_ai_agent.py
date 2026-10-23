"""Offline tests for the Strands Decider HTTP adapter."""

import math
import os
import unittest
from unittest.mock import Mock, patch

import requests

from ai_agent import (
    ALLOWED_POLICIES,
    DecisionInferenceError,
    choose_ai_policy,
)
from decisions import POLICIES, choose_policy


def response_for(policy="BALANCED", confidence=0.75):
    response = Mock()
    probabilities = {name: 0.1 for name in ALLOWED_POLICIES}
    probabilities[policy] = 0.7
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
        "usage": {"input_tokens": 20, "output_tokens": 0},
    }
    response.raise_for_status.return_value = None
    return response


class AiAgentTests(unittest.TestCase):
    EVALUATION_MATRIX = (
        # The model outputs are fixed mock fixtures. They exercise comparison
        # behavior and deliberately do not encode an expectation of agreement.
        ("Normal", 5.0, 70, 1, False, "BALANCED", "BALANCED", 0.94),
        ("Moderate", 2.0, 180, 5, False, "PROTECT_TELEMETRY", "REDUCE_VIDEO", 0.62),
        ("Severe", 0.5, 350, 15, False, "DEFER_SENSORS", "PROTECT_TELEMETRY", 0.28),
        ("Emergency", 1.5, 220, 6, True, "REDUCE_VIDEO", "BALANCED", 0.99),
    )

    def invoke(self, post, **kwargs):
        return choose_ai_policy(5, 70, 1, http_post=post, **kwargs)

    def test_request_uses_systemone_wire_schema(self):
        post = Mock(return_value=response_for())
        result = self.invoke(post)
        args, request = post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8000/v1/systemone")
        self.assertEqual(request["json"]["questions"]["policy"]["type"], "choice")
        self.assertEqual(set(request["json"]["questions"]["policy"]["criteria"]), ALLOWED_POLICIES)
        self.assertEqual(result["source"], "mock")
        self.assertEqual(result["confidence"], 0.75)
        self.assertEqual(request["timeout"], (5.0, 30.0))

    def test_all_allowed_policies_use_authoritative_actions(self):
        for policy in ALLOWED_POLICIES:
            with self.subTest(policy=policy):
                result = self.invoke(Mock(return_value=response_for(policy)))
                self.assertEqual(result["policy"], policy)
                self.assertEqual(result["actions"], POLICIES[policy])
                self.assertFalse(result["fallback_used"])

    def test_invalid_inputs_rejected_without_request(self):
        bad_cases = [
            ((-1, 10, 0, False), ValueError),
            ((1, -1, 0, False), ValueError),
            ((1, 1, 101, False), ValueError),
            ((math.nan, 1, 0, False), ValueError),
            ((1, math.inf, 0, False), ValueError),
            ((1, 1, -math.inf, False), ValueError),
            ((True, 1, 0, False), TypeError),
            ((1, 1, 0, 1), TypeError),
        ]
        for args, error in bad_cases:
            with self.subTest(args=args):
                with self.assertRaises(error):
                    choose_ai_policy(*args, http_post=Mock())

    def test_invalid_or_secret_bearing_service_urls_are_rejected(self):
        for url in ("", "file:///tmp/service", "https://user:token@example.com", "https://example.com/?token=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                choose_ai_policy(1, 1, 0, service_url=url, http_post=Mock())

    def test_invalid_fallback_environment_is_rejected(self):
        with patch.dict(os.environ, {"FLOW_STATE_AI_FALLBACK": "maybe"}):
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                choose_ai_policy(1, 1, 0, http_post=Mock())

    def test_invalid_model_policy_falls_back(self):
        result = self.invoke(Mock(return_value=response_for("RUN_CODE")))
        self.assertEqual(result["policy"], choose_policy(5, 70, 1)["policy"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["source"], "deterministic_fallback")

    def test_missing_probability_data_falls_back_to_baseline(self):
        response = response_for()
        del response.json.return_value["answers"]["policy"]["probabilities"]
        result = choose_ai_policy(
            0.5, 350, 15, http_post=Mock(return_value=response)
        )
        self.assertEqual(result["policy"], "DEFER_SENSORS")
        self.assertEqual(result["source"], "deterministic_fallback")
        self.assertTrue(result["fallback_used"])
        self.assertIsNone(result["confidence"])

    def test_four_scenario_matrix_compares_ai_and_baseline_without_forcing_agreement(self):
        disagreements = []
        for name, bandwidth, latency, loss, emergency, expected_baseline, model_policy, confidence in self.EVALUATION_MATRIX:
            with self.subTest(scenario=name):
                baseline = choose_policy(bandwidth, latency, loss, emergency)
                self.assertEqual(baseline["policy"], expected_baseline)
                ai_decision = choose_ai_policy(
                    bandwidth,
                    latency,
                    loss,
                    emergency,
                    http_post=Mock(return_value=response_for(model_policy, confidence)),
                )
                self.assertEqual(ai_decision["model_policy"], model_policy)
                self.assertIn(ai_decision["model_policy"], ALLOWED_POLICIES)
                if ai_decision["model_policy"] != baseline["policy"]:
                    disagreements.append(name)
                if emergency:
                    self.assertEqual(ai_decision["policy"], "REDUCE_VIDEO")
                    self.assertTrue(ai_decision["safety_override"])
                else:
                    self.assertEqual(ai_decision["policy"], model_policy)
                self.assertEqual(ai_decision["confidence"], confidence)
                self.assertFalse(ai_decision["fallback_used"])
        self.assertIn("Severe", disagreements)

    def test_emergency_override_wins_for_every_model_policy_and_confidence(self):
        for model_policy in sorted(ALLOWED_POLICIES):
            for confidence in (0.0, 0.01, 0.5, 1.0):
                with self.subTest(policy=model_policy, confidence=confidence):
                    result = choose_ai_policy(
                        1.5,
                        220,
                        6,
                        True,
                        http_post=Mock(
                            return_value=response_for(model_policy, confidence)
                        ),
                    )
                    self.assertEqual(result["model_policy"], model_policy)
                    self.assertEqual(result["confidence"], confidence)
                    self.assertEqual(result["policy"], "REDUCE_VIDEO")
                    self.assertEqual(result["actions"], POLICIES["REDUCE_VIDEO"])
                    self.assertEqual(result["actions"]["telemetry"], "high_priority")
                    self.assertTrue(result["safety_override"])

    def test_malformed_response_falls_back(self):
        invalid_payloads = (
            [],
            {},
            {"answers": {"wrong": {}}},
            {
                "model": "mock",
                "usage": {},
                "answers": {"policy": {"choice": "BALANCED", "confidence": 4}},
            },
            {
                "model": "mock",
                "usage": {},
                "answers": {
                    "policy": {
                        "type": "choice",
                        "choice": "BALANCED",
                        "confidence": 0.8,
                        "probabilities": {"BALANCED": math.nan},
                    }
                },
            },
        )
        for payload in invalid_payloads:
            response = response_for()
            response.json.return_value = payload
            with self.subTest(payload=payload):
                result = self.invoke(Mock(return_value=response))
                self.assertTrue(result["fallback_used"])

    def test_invalid_json_http_error_unavailable_and_timeout_fall_back(self):
        bad_json = response_for()
        bad_json.json.side_effect = ValueError("invalid JSON")
        http_error = response_for()
        http_error.raise_for_status.side_effect = requests.HTTPError("503")
        for side_effect in (
            requests.ConnectionError("offline"),
            requests.Timeout("late"),
        ):
            with self.subTest(error=side_effect):
                result = self.invoke(Mock(side_effect=side_effect))
                self.assertTrue(result["fallback_used"])
        for response in (bad_json, http_error):
            self.assertTrue(self.invoke(Mock(return_value=response))["fallback_used"])

    def test_fallback_can_be_disabled(self):
        with self.assertRaises(DecisionInferenceError):
            self.invoke(Mock(side_effect=requests.ConnectionError("offline")), fallback_enabled=False)

    def test_unexpected_service_exception_uses_visible_fallback(self):
        result = self.invoke(Mock(side_effect=RuntimeError("unexpected transport failure")))
        self.assertTrue(result["fallback_used"])
        self.assertIn("unexpected transport failure", result["diagnostics"])
        self.assertIn("AI service request failed", result["fallback_reason"])

    def test_missing_confidence_falls_back_without_fabricating_one(self):
        result = self.invoke(Mock(return_value=response_for(confidence=None)))
        self.assertIsNone(result["confidence"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["source"], "deterministic_fallback")

    def test_mock_response_is_labeled_as_mock(self):
        result = self.invoke(Mock(return_value=response_for()))
        self.assertEqual(result["source"], "mock")

    def test_emergency_override_also_applies_to_fallback(self):
        result = choose_ai_policy(1.5, 220, 6, True, http_post=Mock(side_effect=requests.Timeout("late")))
        self.assertEqual(result["policy"], "REDUCE_VIDEO")
        self.assertTrue(result["fallback_used"])


if __name__ == "__main__":
    unittest.main()
