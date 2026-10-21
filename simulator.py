
"""
FLOW STATE - UAV Network Simulator
A reproducible simulation; does not control real drones.
"""

import random

from decisions import choose_policy


def generate_scenario(seed=None, scenario="mixed"):
    """Generate a simulated UAV network condition."""

    rng = random.Random(seed)

    scenarios = {
        "normal": (5.0, 70, 1.0),
        "moderate": (2.0, 180, 5.0),
        "severe": (0.5, 350, 15.0),
        "emergency": (1.5, 220, 6.0),
    }

    if scenario == "mixed":
        scenario = rng.choice(list(scenarios))

    if scenario not in scenarios:
        raise ValueError(f"Unknown scenario: {scenario}")

    bandwidth, latency, packet_loss = scenarios[scenario]

    # Add small, reproducible variations to the network.
    bandwidth = max(0.0, bandwidth + rng.uniform(-0.2, 0.2))
    latency = max(0.0, latency + rng.uniform(-15, 15))
    packet_loss = min(
        100.0,
        max(0.0, packet_loss + rng.uniform(-0.5, 0.5)),
    )

    return {
        "scenario": scenario,
        "bandwidth_mbps": round(bandwidth, 2),
        "latency_ms": round(latency, 2),
        "packet_loss_pct": round(packet_loss, 2),
        "emergency": scenario == "emergency",
    }


def simulate_step(seed=None, scenario="mixed"):
    """Generate a scenario and choose a bandwidth-management policy."""

    network = generate_scenario(seed=seed, scenario=scenario)

    decision = choose_policy(
        bandwidth_mbps=network["bandwidth_mbps"],
        latency_ms=network["latency_ms"],
        packet_loss_pct=network["packet_loss_pct"],
        emergency=network["emergency"],
    )

    return {
        **network,
        "policy": decision["policy"],
        "actions": decision["actions"],
        "reason": decision["reason"],
    }


def run_simulation(steps=20, seed=42):
    """Run multiple reproducible simulated network scenarios."""

    if steps < 1:
        raise ValueError("steps must be at least 1.")

    rng = random.Random(seed)
    results = []

    for _ in range(steps):
        scenario_seed = rng.randint(0, 1_000_000_000)
        results.append(
            simulate_step(seed=scenario_seed, scenario="mixed")
        )

    return results


if __name__ == "__main__":
    for index, result in enumerate(run_simulation(), start=1):
        print(f"\n--- Simulation step {index} ---")
        print(f"Scenario: {result['scenario']}")
        print(f"Bandwidth: {result['bandwidth_mbps']} Mbps")
        print(f"Latency: {result['latency_ms']} ms")
        print(f"Packet loss: {result['packet_loss_pct']}%")
        print(f"Policy: {result['policy']}")
        print(f"Reason: {result['reason']}")
        print(f"Actions: {result['actions']}")
