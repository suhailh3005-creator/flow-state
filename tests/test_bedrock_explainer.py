import unittest
from types import ModuleType
from unittest.mock import patch
import sys

from bedrock_explainer import (
    BedrockExplanationError,
    explain_decision,
)


class FakeBedrock:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "output": {
                "message": {
                    "content": [
                        {"text": "Video may be reduced to preserve telemetry."}
                    ]
                }
            }
        }
        self.error = error
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class BedrockExplanationTests(unittest.TestCase):
    def test_generates_explanation_without_changing_policy(self):
        fake = FakeBedrock()
        text = explain_decision(
            bandwidth_mbps=0.5,
            latency_ms=350,
            packet_loss_pct=12,
            policy="REDUCE_VIDEO",
            reason="Severe network degradation",
            emergency=False,
            client=fake,
        )
        self.assertIn("telemetry", text)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(
            fake.calls[0]["modelId"], "apac.amazon.nova-lite-v1:0"
        )
        prompt = fake.calls[0]["messages"][0]["content"][0]["text"]
        self.assertIn("Selected policy: REDUCE_VIDEO", prompt)
        self.assertIn("do not recommend replacing it", prompt)

    def test_rejects_invalid_metrics_without_calling_model(self):
        fake = FakeBedrock()
        with self.assertRaises(ValueError):
            explain_decision(
                bandwidth_mbps=-1,
                latency_ms=20,
                packet_loss_pct=0,
                policy="BALANCED",
                reason="test",
                client=fake,
            )
        self.assertEqual(fake.calls, [])

    def test_wraps_bedrock_errors(self):
        fake = FakeBedrock(error=RuntimeError("simulated failure"))
        with self.assertRaises(BedrockExplanationError):
            explain_decision(
                bandwidth_mbps=5,
                latency_ms=80,
                packet_loss_pct=1,
                policy="BALANCED",
                reason="Normal conditions",
                client=fake,
            )

    def test_timeout_and_malformed_response_fail_safely_after_one_call(self):
        for fake in (
            FakeBedrock(error=TimeoutError("simulated timeout")),
            FakeBedrock(response={"output": {"message": {"content": []}}}),
        ):
            with self.subTest(fake=fake), self.assertRaises(BedrockExplanationError):
                explain_decision(
                    bandwidth_mbps=1.5,
                    latency_ms=220,
                    packet_loss_pct=6,
                    policy="REDUCE_VIDEO",
                    reason="Emergency override",
                    emergency=True,
                    client=fake,
                )
            self.assertEqual(len(fake.calls), 1)

    def test_default_client_has_bounded_timeouts_and_no_retries(self):
        fake = FakeBedrock()
        created = {}
        client_module = ModuleType("boto3")
        def make_client(*args, **kwargs):
            created.update(kwargs)
            return fake
        client_module.client = make_client
        config_module = ModuleType("botocore.config")
        config_module.Config = lambda **kwargs: kwargs
        botocore_module = ModuleType("botocore")
        botocore_module.__path__ = []
        with patch.dict(sys.modules, {
            "boto3": client_module,
            "botocore": botocore_module,
            "botocore.config": config_module,
        }):
            explain_decision(
                bandwidth_mbps=5,
                latency_ms=70,
                packet_loss_pct=1,
                policy="BALANCED",
                reason="Normal conditions",
            )

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(created["config"]["connect_timeout"], 3)
        self.assertEqual(created["config"]["read_timeout"], 20)
        self.assertEqual(created["config"]["retries"]["total_max_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
