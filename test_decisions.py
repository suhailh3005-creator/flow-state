
from decisions import choose_policy

test_cases = [
    {
        "name": "Normal network",
        "inputs": {
            "bandwidth_mbps": 10,
            "latency_ms": 40,
            "packet_loss_pct": 0.5,
        },
        "expected": "BALANCED",
    },
    {
        "name": "Moderate congestion",
        "inputs": {
            "bandwidth_mbps": 2,
            "latency_ms": 100,
            "packet_loss_pct": 1,
        },
        "expected": "PROTECT_TELEMETRY",
    },
    {
        "name": "Severe congestion",
        "inputs": {
            "bandwidth_mbps": 0.5,
            "latency_ms": 350,
            "packet_loss_pct": 12,
        },
        "expected": "DEFER_SENSORS",
    },
    {
        "name": "Emergency",
        "inputs": {
            "bandwidth_mbps": 10,
            "latency_ms": 40,
            "packet_loss_pct": 0.5,
            "emergency": True,
        },
        "expected": "REDUCE_VIDEO",
    },
]

for case in test_cases:
    result = choose_policy(**case["inputs"])
    passed = result["policy"] == case["expected"]

    print(
        f"{'PASS' if passed else 'FAIL'} | "
        f"{case['name']} | "
        f"Expected: {case['expected']} | "
        f"Got: {result['policy']}"
    )
