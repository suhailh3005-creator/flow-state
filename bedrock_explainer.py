"""Optional Amazon Bedrock explanation for a FLOW STATE decision.

Bedrock explains an already-selected policy. It never selects or applies
scheduler policies and never overrides emergency handling.
"""

from __future__ import annotations

import os
from typing import Any


DEFAULT_MODEL_ID = "apac.amazon.nova-lite-v1:0"


class BedrockExplanationError(RuntimeError):
    """Bedrock could not generate a valid explanation."""


def explain_decision(
    *,
    bandwidth_mbps: float,
    latency_ms: float,
    packet_loss_pct: float,
    policy: str,
    reason: str,
    emergency: bool = False,
    client: Any = None,
) -> str:
    """Generate a short explanation for a policy already selected by FLOW STATE."""
    values = (bandwidth_mbps, latency_ms, packet_loss_pct)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
        raise ValueError("Network metrics must be numeric.")
    if bandwidth_mbps < 0 or latency_ms < 0 or not 0 <= packet_loss_pct <= 100:
        raise ValueError("Network metrics are outside their permitted ranges.")
    if not isinstance(policy, str) or not policy.strip():
        raise ValueError("policy must be a non-empty string.")
    if not isinstance(reason, str):
        raise ValueError("reason must be a string.")
    if not isinstance(emergency, bool):
        raise ValueError("emergency must be a bool.")

    if client is None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise BedrockExplanationError(
                "Install the AWS SDK with: python -m pip install boto3"
            ) from exc

        region = (
            os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
        )
        try:
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(
                    connect_timeout=3,
                    read_timeout=20,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                ),
            )
        except Exception as exc:
            raise BedrockExplanationError(
                f"Could not initialize the Bedrock client: {exc}"
            ) from exc

    model_id = os.getenv(
        "FLOW_STATE_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID
    )

    prompt = (
        "Explain this simulated UAV network bandwidth-management decision "
        "to a human operator in 2-4 concise sentences. Use only the supplied "
        "facts. Do not invent measurements or claim real-world control. "
        "The policy has already been selected by a separate decision system: "
        "do not recommend replacing it or changing it.\n\n"
        f"Bandwidth: {bandwidth_mbps} Mbps\n"
        f"Latency: {latency_ms} ms\n"
        f"Packet loss: {packet_loss_pct}%\n"
        f"Selected policy: {policy}\n"
        f"Decision reason: {reason}\n"
        f"Emergency condition: {emergency}\n\n"
        "Explain the likely trade-off and remind the operator that metrics "
        "and effects in this simulator are simulated."
    )

    try:
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": 180,
                "temperature": 0.2,
            },
        )
        content = response["output"]["message"]["content"]
        explanation = next(
            (
                item["text"].strip()
                for item in content
                if isinstance(item, dict)
                and isinstance(item.get("text"), str)
                and item["text"].strip()
            ),
            None,
        )
        if not explanation:
            raise ValueError("Response did not contain text.")
        return explanation
    except Exception as exc:
        raise BedrockExplanationError(
            f"Bedrock explanation request failed: {exc}"
        ) from exc
