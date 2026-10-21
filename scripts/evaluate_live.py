#!/usr/bin/env python3
"""Run one small live evaluation against the configured local Strands service."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_agent import DEFAULT_SERVICE_URL, choose_ai_policy  # noqa: E402
from decisions import choose_policy  # noqa: E402
from metrics import calculate_metrics  # noqa: E402

SCENARIOS = (
    {"name": "Normal", "bandwidth_mbps": 5.0, "latency_ms": 70, "packet_loss_pct": 1.0, "emergency": False},
    {"name": "Moderate", "bandwidth_mbps": 2.0, "latency_ms": 180, "packet_loss_pct": 5.0, "emergency": False},
    {"name": "Severe", "bandwidth_mbps": 0.5, "latency_ms": 350, "packet_loss_pct": 15.0, "emergency": False},
    {"name": "Emergency", "bandwidth_mbps": 1.5, "latency_ms": 220, "packet_loss_pct": 6.0, "emergency": True},
)


def default_output_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return ROOT / "reports" / f"live-evaluation-{stamp}.json"


def run_evaluation(
    output_path: str | Path | None = None,
    *,
    service_url: str | None = None,
    timeout_seconds: float | None = None,
    http_post: Any = None,
    require_real_service: bool = True,
) -> tuple[dict[str, Any], Path, bool]:
    """Evaluate each fixed scenario once and serialize a JSON report.

    ``http_post`` is only a test seam. The CLI never supplies it and rejects
    responses the adapter identifies as mocks.
    """
    report_path = Path(output_path) if output_path is not None else default_output_path()
    rows: list[dict[str, Any]] = []
    complete = True
    stop_reason: str | None = None
    effective_url = service_url or os.getenv("FLOW_STATE_AI_URL", DEFAULT_SERVICE_URL)
    effective_timeout: float | str = timeout_seconds if timeout_seconds is not None else os.getenv(
        "FLOW_STATE_AI_TIMEOUT_SECONDS", "30"
    )

    for scenario in SCENARIOS:
        inputs = {key: value for key, value in scenario.items() if key != "name"}
        metric_inputs = {
            key: inputs[key]
            for key in ("bandwidth_mbps", "latency_ms", "packet_loss_pct")
        }
        baseline = choose_policy(**inputs)
        row: dict[str, Any] = {
            "scenario": scenario["name"],
            "inputs": inputs,
            "model_recommendation": None,
            "model_confidence": None,
            "baseline_recommendation": baseline["policy"],
            "final_policy": baseline["policy"],
            "safety_override": bool(inputs["emergency"]),
            "simulated_metrics": {
                "final_policy": calculate_metrics(**metric_inputs, policy=baseline["policy"]),
                "baseline_policy": calculate_metrics(**metric_inputs, policy=baseline["policy"]),
            },
            "request_latency_ms": None,
            "source": None,
            "fallback_used": False,
            "fallback_reason": None,
            "error": None,
            "status": "not_attempted",
        }

        if stop_reason is not None:
            row["error"] = f"Not attempted after prior service failure: {stop_reason}"
            row["fallback_used"] = True
            row["fallback_reason"] = "Deterministic baseline retained; no additional request was sent."
            rows.append(row)
            continue

        started = perf_counter()
        try:
            kwargs: dict[str, Any] = {
                "service_url": service_url,
                "timeout_seconds": timeout_seconds,
                "fallback_enabled": True,
            }
            if http_post is not None:
                kwargs["http_post"] = http_post
            decision = choose_ai_policy(**inputs, **kwargs)
            row["request_latency_ms"] = round((perf_counter() - started) * 1000, 2)
            row["source"] = decision["source"]
            if decision["fallback_used"]:
                row["final_policy"] = decision["policy"]
                row["safety_override"] = decision["safety_override"]
                row["fallback_used"] = True
                row["fallback_reason"] = decision.get("fallback_reason")
                row["error"] = decision.get("diagnostics") or decision["fallback_reason"]
                row["status"] = "fallback"
                complete = False
                stop_reason = row["error"]
            elif require_real_service and decision["source"] != "strands_decider":
                row["fallback_used"] = True
                row["fallback_reason"] = "Non-live response rejected; deterministic baseline retained."
                row["error"] = (
                    f"Expected a real Strands response; adapter source was {decision['source']!r}."
                )
                row["status"] = "error"
                row["source"] = decision["source"]
                complete = False
                stop_reason = row["error"]
            else:
                row["model_recommendation"] = decision.get("model_policy")
                row["model_confidence"] = decision.get("confidence")
                row["final_policy"] = decision["policy"]
                row["safety_override"] = decision["safety_override"]
                row["status"] = "complete"
        except Exception as exc:
            row["request_latency_ms"] = round((perf_counter() - started) * 1000, 2)
            row["final_policy"] = baseline["policy"]
            row["safety_override"] = bool(inputs["emergency"])
            row["fallback_used"] = True
            row["fallback_reason"] = "Deterministic baseline retained because live inference failed."
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["status"] = "error"
            row["source"] = "deterministic_fallback"
            complete = False
            stop_reason = row["error"]

        final_policy = row["final_policy"]
        row["simulated_metrics"]["final_policy"] = calculate_metrics(
            **metric_inputs, policy=final_policy
        )
        rows.append(row)

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "service_url": effective_url,
        "timeout_seconds": effective_timeout,
        "result_kind": "live Strands inference with simulated FLOW STATE metrics",
        "complete": complete,
        "scenarios": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report, report_path, complete


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="JSON report path (default: ignored reports/ file)")
    parser.add_argument("--service-url", help="Override FLOW_STATE_AI_URL for this run")
    parser.add_argument("--timeout", type=float, help="Override FLOW_STATE_AI_TIMEOUT_SECONDS")
    args = parser.parse_args(argv)

    try:
        report, path, complete = run_evaluation(
            args.output,
            service_url=args.service_url,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        print(f"Live evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {'complete' if complete else 'incomplete'} live evaluation: {path}")
    for row in report["scenarios"]:
        print(
            f"{row['scenario']}: status={row['status']}, "
            f"model={row['model_recommendation']}, baseline={row['baseline_recommendation']}, "
            f"final={row['final_policy']}, latency_ms={row['request_latency_ms']}"
        )
        if row["error"]:
            print(f"  error: {row['error']}", file=sys.stderr)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
