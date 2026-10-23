#!/usr/bin/env python3
"""Write a reproducible baseline evaluation without contacting model services."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decisions import choose_policy  # noqa: E402
from metrics import calculate_metrics  # noqa: E402

SCENARIOS = (
    {"name": "Normal", "bandwidth_mbps": 5.0, "latency_ms": 70, "packet_loss_pct": 1.0, "emergency": False},
    {"name": "Moderate", "bandwidth_mbps": 2.0, "latency_ms": 180, "packet_loss_pct": 5.0, "emergency": False},
    {"name": "Severe", "bandwidth_mbps": 0.5, "latency_ms": 350, "packet_loss_pct": 15.0, "emergency": False},
    {"name": "Emergency", "bandwidth_mbps": 1.5, "latency_ms": 220, "packet_loss_pct": 6.0, "emergency": True},
)


def build_report() -> dict:
    rows = []
    for scenario in SCENARIOS:
        inputs = {key: value for key, value in scenario.items() if key != "name"}
        decision = choose_policy(**inputs)
        metrics = calculate_metrics(
            bandwidth_mbps=inputs["bandwidth_mbps"],
            latency_ms=inputs["latency_ms"],
            packet_loss_pct=inputs["packet_loss_pct"],
            policy=decision["policy"],
        )
        rows.append({
            "scenario": scenario["name"],
            "inputs": inputs,
            "policy": decision["policy"],
            "reason": decision["reason"],
            "simulated_metrics": metrics,
        })
    return {
        "result_kind": "deterministic baseline evaluation with simulated metrics",
        "model_calls": 0,
        "scenarios": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "reports" / "offline-evaluation.json",
        help="JSON output path (default: reports/offline-evaluation.json)",
    )
    args = parser.parse_args(argv)
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote offline evaluation (0 model calls): {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
