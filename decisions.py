
"""
FLOW STATE — Local Decision Engine
Runs entirely on your computer; no AWS calls.
"""

POLICIES = {
    "BALANCED": {
        "video": "normal",
        "telemetry": "normal",
        "sensors": "normal",
    },
    "PROTECT_TELEMETRY": {
        "video": "reduced",
        "telemetry": "high_priority",
        "sensors": "normal",
    },
    "REDUCE_VIDEO": {
        "video": "minimum",
        "telemetry": "high_priority",
        "sensors": "normal",
    },
    "DEFER_SENSORS": {
        "video": "reduced",
        "telemetry": "high_priority",
        "sensors": "deferred",
    },
}


def choose_policy(
    bandwidth_mbps,
    latency_ms,
    packet_loss_pct,
    emergency=False,
):
    """
    Select a bandwidth policy from network conditions.

    This is a deterministic baseline, not an AI model.
    """

    # Validate the inputs before making a decision.
    if bandwidth_mbps < 0:
        raise ValueError("Bandwidth cannot be negative.")

    if latency_ms < 0:
        raise ValueError("Latency cannot be negative.")

    if not 0 <= packet_loss_pct <= 100:
        raise ValueError("Packet loss must be between 0 and 100.")

    # Protect critical telemetry during an emergency.
    if emergency:
        policy = "REDUCE_VIDEO"
        reason = "Emergency: preserve critical telemetry."

    # Severe congestion or unreliable network.
    elif (
        bandwidth_mbps < 1.0
        or latency_ms > 300
        or packet_loss_pct > 10
    ):
        policy = "DEFER_SENSORS"
        reason = "Severe network congestion or instability."

    # Moderate network degradation.
    elif (
        bandwidth_mbps < 3.0
        or latency_ms > 150
        or packet_loss_pct > 3
    ):
        policy = "PROTECT_TELEMETRY"
        reason = "Network degradation: prioritize telemetry."

    else:
        policy = "BALANCED"
        reason = "Network conditions are within baseline limits."

    return {
        "policy": policy,
        "actions": POLICIES[policy].copy(),
        "reason": reason,
        "input_conditions": {
            "bandwidth_mbps": bandwidth_mbps,
            "latency_ms": latency_ms,
            "packet_loss_pct": packet_loss_pct,
            "emergency": emergency,
        },
    }
