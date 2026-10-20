
"""
FLOW STATE - Simulation Metrics
Calculates simulated traffic performance and comparisons.
"""

from scheduler import apply_policy


def calculate_metrics(
    bandwidth_mbps,
    latency_ms,
    packet_loss_pct,
    policy,
):
    """Calculate simplified, explicitly modeled network metrics."""

    if bandwidth_mbps < 0:
        raise ValueError("Bandwidth cannot be negative.")
    if latency_ms < 0:
        raise ValueError("Latency cannot be negative.")
    if not 0 <= packet_loss_pct <= 100:
        raise ValueError("Packet loss must be between 0 and 100.")

    allocation = apply_policy(policy, bandwidth_mbps)

    # Illustrative traffic demand, in Mbps.
    demand = {
        "video": 3.0,
        "telemetry": 1.0,
        "sensors": 1.0,
    }

    delivered = {
        "video": min(allocation["video_mbps"], demand["video"]),
        "telemetry": min(
            allocation["telemetry_mbps"], demand["telemetry"]
        ),
        "sensors": min(
            allocation["sensors_mbps"], demand["sensors"]
        ) if allocation["sensors_enabled"] else 0.0,
    }

    def delivery_ratio(stream):
        if demand[stream] == 0:
            return 1.0
        return min(1.0, delivered[stream] / demand[stream])

    total_demand = sum(demand.values())
    total_delivered = sum(delivered.values())

    # Simple illustrative model: packet loss reduces successful delivery.
    effective_delivery = total_delivered * (
        1 - packet_loss_pct / 100
    )

    return {
        "policy": policy,
        "bandwidth_mbps": round(bandwidth_mbps, 3),
        "latency_ms": round(latency_ms, 2),
        "packet_loss_pct": round(packet_loss_pct, 2),
        "video_delivery_ratio": round(delivery_ratio("video"), 3),
        "telemetry_delivery_ratio": round(
            delivery_ratio("telemetry"), 3
        ),
        "sensor_delivery_ratio": round(
            delivery_ratio("sensors"), 3
        ),
        "total_demand_mbps": total_demand,
        "allocated_delivery_mbps": round(total_delivered, 3),
        "effective_delivery_mbps": round(effective_delivery, 3),
        "demand_satisfaction_pct": round(
            100 * total_delivered / total_demand, 2
        ),
        "allocation": allocation,
    }


def compare_policies(
    bandwidth_mbps,
    latency_ms,
    packet_loss_pct,
):
    """Compare all policies under identical network conditions."""

    policies = [
        "BALANCED",
        "PROTECT_TELEMETRY",
        "REDUCE_VIDEO",
        "DEFER_SENSORS",
    ]

    return [
        calculate_metrics(
            bandwidth_mbps=bandwidth_mbps,
            latency_ms=latency_ms,
            packet_loss_pct=packet_loss_pct,
            policy=policy,
        )
        for policy in policies
    ]


if __name__ == "__main__":
    results = compare_policies(
        bandwidth_mbps=2.0,
        latency_ms=180,
        packet_loss_pct=5.0,
    )

    for result in results:
        print(
            f"{result['policy']}: "
            f"Demand satisfaction = "
            f"{result['demand_satisfaction_pct']}%, "
            f"Telemetry delivery = "
            f"{result['telemetry_delivery_ratio']:.0%}, "
            f"Effective delivery = "
            f"{result['effective_delivery_mbps']} Mbps"
        )
