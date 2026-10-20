
"""
FLOW STATE - Bandwidth Policy Scheduler

Models how traffic is allocated under a selected policy.
This is a simplified simulation, not real network control.
"""

POLICY_SETTINGS = {
    "BALANCED": {
        "video_share": 0.60,
        "telemetry_share": 0.25,
        "sensors_share": 0.15,
        "sensor_enabled": True,
    },
    "PROTECT_TELEMETRY": {
        "video_share": 0.35,
        "telemetry_share": 0.50,
        "sensors_share": 0.15,
        "sensor_enabled": True,
    },
    "REDUCE_VIDEO": {
        "video_share": 0.15,
        "telemetry_share": 0.70,
        "sensors_share": 0.15,
        "sensor_enabled": True,
    },
    "DEFER_SENSORS": {
        "video_share": 0.35,
        "telemetry_share": 0.65,
        "sensors_share": 0.0,
        "sensor_enabled": False,
    },
}


def apply_policy(policy, available_bandwidth_mbps):
    """Allocate available bandwidth according to a selected policy."""

    if available_bandwidth_mbps < 0:
        raise ValueError("Bandwidth cannot be negative.")

    if policy not in POLICY_SETTINGS:
        raise ValueError(f"Unknown policy: {policy}")

    settings = POLICY_SETTINGS[policy]
    bandwidth = available_bandwidth_mbps

    return {
        "policy": policy,
        "available_bandwidth_mbps": round(bandwidth, 3),
        "video_mbps": round(
            bandwidth * settings["video_share"], 3
        ),
        "telemetry_mbps": round(
            bandwidth * settings["telemetry_share"], 3
        ),
        "sensors_mbps": round(
            bandwidth * settings["sensors_share"], 3
        ),
        "sensors_enabled": settings["sensor_enabled"],
    }


if __name__ == "__main__":
    for policy_name in POLICY_SETTINGS:
        print(apply_policy(policy_name, 5.0))
