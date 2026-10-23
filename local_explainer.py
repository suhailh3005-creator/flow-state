"""
FLOW STATE - Local Policy Explanation Module
Offline, deterministic explanations for policies selected by the existing app.

This module does not call Amazon Bedrock or any external API. It does not
select policies or execute actions. It explains the policy supplied by the
caller and only displays metrics/outcomes that the caller actually provides.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


POLICY_TEXT = {
    "BALANCED": {
        "summary": "The system selected a balanced bandwidth policy.",
        "reason": (
            "The supplied decision indicates that a balanced policy is "
            "appropriate for this scenario. This module does not independently "
            "verify the policy decision."
        ),
        "tradeoff": (
            "A balanced policy aims to avoid unnecessarily favouring one "
            "traffic category over another."
        ),
    },
    "PROTECT_TELEMETRY": {
        "summary": "The system selected the telemetry-protection policy.",
        "reason": (
            "This policy is intended to prioritise telemetry when the decision "
            "logic identifies conditions where telemetry protection matters."
        ),
        "tradeoff": (
            "Prioritising telemetry may leave less capacity for video or other "
            "traffic, depending on the scheduler implementation."
        ),
    },
    "REDUCE_VIDEO": {
        "summary": "The system selected the video-reduction policy.",
        "reason": (
            "This policy is intended to reduce video traffic when the decision "
            "logic determines that conserving bandwidth is needed."
        ),
        "tradeoff": (
            "Reducing video traffic can lower video quality or throughput; "
            "the actual effect depends on the scheduler and simulator."
        ),
    },
    "DEFER_SENSORS": {
        "summary": "The system selected the sensor-deferral policy.",
        "reason": (
            "This policy is intended to defer eligible lower-priority sensor "
            "traffic when the decision logic determines that capacity is "
            "severely constrained."
        ),
        "tradeoff": (
            "Deferring sensor traffic can delay sensor updates. Only defer "
            "traffic that the application considers safe to delay."
        ),
    },
}


def _format_metric(name: str, value: Any) -> str:
    labels = {
        "bandwidth_mbps": ("Available bandwidth", "Mbps"),
        "latency_ms": ("Latency", "ms"),
        "packet_loss_pct": ("Packet loss", "%"),
    }
    label, unit = labels.get(name, (name.replace("_", " ").capitalize(), ""))
    return f"{label}: {value} {unit}".strip()


def explain_decision(
    policy: str,
    metrics: Mapping[str, Any] | None = None,
    actions: Sequence[Any] | None = None,
    observed_outcomes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain an already-selected policy using only data supplied by the app."""
    policy_key = str(policy).strip().upper()
    info = POLICY_TEXT.get(policy_key, {
        "summary": f"The system selected policy: {policy_key or 'UNKNOWN'}.",
        "reason": (
            "No built-in explanation template exists for this policy. Its "
            "purpose is not guessed by this module."
        ),
        "tradeoff": "The implications of this policy are not documented here.",
    })

    metrics = dict(metrics or {})
    actions = [str(a) for a in (actions or []) if a is not None]
    outcomes = dict(observed_outcomes or {})

    metric_lines = [
        _format_metric(k, v) for k, v in metrics.items() if v is not None
    ]
    outcome_lines = [
        _format_metric(k, v) for k, v in outcomes.items() if v is not None
    ]

    lines = [
        info["summary"],
        "",
        "Why this policy:",
        info["reason"],
        "",
        "Trade-off to consider:",
        info["tradeoff"],
    ]

    if metric_lines:
        lines += ["", "Input network conditions:"]
        lines += [f"- {line}" for line in metric_lines]

    if actions:
        lines += ["", "Actions supplied by the application:"]
        lines += [f"- {action}" for action in actions]

    if outcome_lines:
        lines += ["", "Observed simulator outcomes (provided by the application):"]
        lines += [f"- {line}" for line in outcome_lines]
    else:
        lines += [
            "",
            "Observed outcomes: Not provided. No performance improvement is claimed.",
        ]

    lines += [
        "",
        "This is a local, template-based explanation. It does not call an AI "
        "model and does not make or change the policy decision.",
    ]

    return {
        "policy": policy_key or "UNKNOWN",
        "summary": info["summary"],
        "reason": info["reason"],
        "tradeoff": info["tradeoff"],
        "metrics": metrics,
        "actions": actions,
        "observed_outcomes": outcomes,
        "details": "\n".join(lines),
        "source": "local_template",
    }


if __name__ == "__main__":
    # Local smoke test with illustrative values. No network calls are made.
    result = explain_decision(
        policy="PROTECT_TELEMETRY",
        metrics={
            "bandwidth_mbps": 1.0,
            "latency_ms": 300,
            "packet_loss_pct": 8.0,
        },
        actions=["Prioritise telemetry traffic"],
    )
    print(result["details"])
