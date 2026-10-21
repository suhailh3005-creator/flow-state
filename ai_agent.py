"""HTTP adapter for the Strands Decider typed-choice inference server.

This module deliberately knows only the server's choice result and the four
policy identifiers. Scheduler actions always come from :mod:`decisions`.
"""

from __future__ import annotations

import math
import os
from numbers import Real
from typing import Any
from urllib.parse import urlsplit

import requests

from decisions import POLICIES, choose_policy

ALLOWED_POLICIES = frozenset(POLICIES)
DEFAULT_SERVICE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0


class DecisionInferenceError(RuntimeError):
    """The inference service failed or returned an invalid decision."""


def _validate_inputs(
    bandwidth_mbps: Real,
    latency_ms: Real,
    packet_loss_pct: Real,
    emergency: bool,
) -> None:
    for name, value in (
        ("bandwidth_mbps", bandwidth_mbps),
        ("latency_ms", latency_ms),
        ("packet_loss_pct", packet_loss_pct),
    ):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"{name} must be a real number.")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
    if bandwidth_mbps < 0:
        raise ValueError("Bandwidth cannot be negative.")
    if latency_ms < 0:
        raise ValueError("Latency cannot be negative.")
    if not 0 <= packet_loss_pct <= 100:
        raise ValueError("Packet loss must be between 0 and 100.")
    if not isinstance(emergency, bool):
        raise TypeError("emergency must be a bool.")


def _timeout_value(timeout_seconds: float | None) -> float:
    value = (
        float(os.getenv("FLOW_STATE_AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
        if timeout_seconds is None
        else timeout_seconds
    )
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("timeout_seconds must be a positive real number.")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_seconds must be a positive finite number.")
    return float(value)


def _fallback(
    inputs: dict[str, Any], error: Exception, enabled: bool
) -> dict[str, Any]:
    if not enabled:
        raise DecisionInferenceError(str(error)) from error
    decision = choose_policy(**inputs)
    if isinstance(error, requests.Timeout):
        message = "The AI service did not respond before the configured timeout."
    elif isinstance(error, requests.ConnectionError):
        message = "Could not connect to the AI service. Check that it is running and the URL is correct."
    elif isinstance(error, requests.HTTPError):
        message = "The AI service returned an HTTP error."
    elif isinstance(error, DecisionInferenceError):
        message = "The AI service returned an invalid or unsupported decision."
    else:
        message = "The AI service request failed."
    return {
        "policy": decision["policy"],
        "actions": decision["actions"],
        "reason": decision["reason"],
        "fallback_reason": message,
        "diagnostics": f"{type(error).__name__}: {error}",
        "source": "deterministic_fallback",
        "fallback_used": True,
        "model_policy": None,
        "confidence": None,
        "safety_override": False,
    }


def _parse_response(payload: Any) -> tuple[str, float | None, str]:
    if not isinstance(payload, dict):
        raise DecisionInferenceError("Inference response must be a JSON object.")
    if not isinstance(payload.get("usage"), dict):
        raise DecisionInferenceError("Inference response is missing usage metadata.")
    answers = payload.get("answers")
    answer = answers.get("policy") if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        raise DecisionInferenceError("Inference response is missing answers.policy.")
    model_name = payload.get("model")
    if not isinstance(model_name, str) or not model_name.strip():
        raise DecisionInferenceError("Inference response is missing its model identifier.")
    if answer.get("type") != "choice":
        raise DecisionInferenceError("Inference response policy answer is not a choice.")
    policy = answer.get("choice")
    if not isinstance(policy, str) or policy not in ALLOWED_POLICIES:
        raise DecisionInferenceError("Model returned an unsupported policy identifier.")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != ALLOWED_POLICIES:
        raise DecisionInferenceError("Inference response is missing valid policy probabilities.")
    probability_values = []
    for probability in probabilities.values():
        if isinstance(probability, bool) or not isinstance(probability, Real):
            raise DecisionInferenceError("Policy probabilities must be numeric.")
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise DecisionInferenceError("Policy probabilities must be finite values from 0 to 1.")
        probability_values.append(float(probability))
    if not math.isclose(sum(probability_values), 1.0, abs_tol=0.02):
        raise DecisionInferenceError("Policy probabilities must sum to approximately 1.")
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, Real):
        raise DecisionInferenceError("Inference response is missing numeric model confidence.")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise DecisionInferenceError("Model confidence must be finite and between 0 and 1.")
    confidence = float(confidence)
    source = "mock" if isinstance(model_name, str) and model_name.strip().lower() in {
        "mock", "mock-strands-decider", "test-mock"
    } else "strands_decider"
    usage = payload["usage"]
    for field in ("input_tokens", "output_tokens"):
        token_count = usage.get(field, 0)
        if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0:
            raise DecisionInferenceError(f"Inference usage field {field} must be a non-negative integer.")
    return policy, confidence, source


def choose_ai_policy(
    bandwidth_mbps: Real,
    latency_ms: Real,
    packet_loss_pct: Real,
    emergency: bool = False,
    *,
    service_url: str | None = None,
    timeout_seconds: float | None = None,
    fallback_enabled: bool | None = None,
    http_post: Any = None,
) -> dict[str, Any]:
    """Request one constrained policy choice from Strands Decider.

    Returns ``policy``, authoritative ``actions``, ``reason``, ``source``,
    ``fallback_used``, and model ``confidence`` (or ``None`` when unavailable).
    ``fallback_reason`` and developer-facing ``diagnostics`` are populated only
    when fallback is used. ``safety_override`` identifies an emergency override.
    ``FLOW_STATE_AI_URL`` defaults to ``http://127.0.0.1:8000``;
    ``FLOW_STATE_AI_TIMEOUT_SECONDS`` defaults to 30. ``FLOW_STATE_AI_FALLBACK``
    defaults to enabled. Explicit keyword values override these environment
    settings. ``http_post`` is an injection point for offline tests.
    """
    _validate_inputs(bandwidth_mbps, latency_ms, packet_loss_pct, emergency)
    timeout = _timeout_value(timeout_seconds)
    if fallback_enabled is None:
        fallback_setting = os.getenv("FLOW_STATE_AI_FALLBACK", "1").strip().lower()
        if fallback_setting in {"1", "true", "yes", "on"}:
            fallback_enabled = True
        elif fallback_setting in {"0", "false", "no", "off"}:
            fallback_enabled = False
        else:
            raise ValueError("FLOW_STATE_AI_FALLBACK must be a boolean setting.")
    if not isinstance(fallback_enabled, bool):
        raise TypeError("fallback_enabled must be a bool.")
    raw_url = os.getenv("FLOW_STATE_AI_URL", DEFAULT_SERVICE_URL) if service_url is None else service_url
    if not isinstance(raw_url, str) or not raw_url:
        raise ValueError("service_url must be a non-empty HTTP or HTTPS URL.")
    parsed_url = urlsplit(raw_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ValueError("service_url must be an HTTP or HTTPS base URL without credentials or query values.")
    url = raw_url.rstrip("/")

    inputs = {
        "bandwidth_mbps": bandwidth_mbps,
        "latency_ms": latency_ms,
        "packet_loss_pct": packet_loss_pct,
        "emergency": emergency,
    }
    request_body = {
        "state": inputs,
        "questions": {
            "policy": {
                "type": "choice",
                "instructions": (
                    "Choose the bandwidth-management policy that best fits the "
                    "network state. Select exactly one permitted policy identifier."
                ),
                "criteria": {
                    "BALANCED": "Normal allocation when network conditions are healthy.",
                    "PROTECT_TELEMETRY": "Reduce video and prioritize high-priority telemetry.",
                    "REDUCE_VIDEO": "Minimize video and prioritize high-priority telemetry.",
                    "DEFER_SENSORS": "Reduce video, prioritize telemetry, and defer sensors.",
                },
            }
        },
    }
    post = http_post or requests.post
    try:
        response = post(
            f"{url}/v1/systemone",
            json=request_body,
            headers={"Content-Type": "application/json"},
            timeout=(min(5.0, timeout), timeout),
        )
        response.raise_for_status()
        try:
            policy, confidence, source = _parse_response(response.json())
        except (ValueError, TypeError) as exc:
            raise DecisionInferenceError(f"Malformed inference JSON: {exc}") from exc
    except Exception as exc:
        result = _fallback(inputs, exc, fallback_enabled)
    else:
        result = {
            "policy": policy,
            "actions": POLICIES[policy].copy(),
            "reason": "Policy selected by Strands Decider from the simulated network conditions.",
            "fallback_reason": None,
            "diagnostics": None,
            "source": source,
            "fallback_used": False,
            "model_policy": policy,
            "confidence": confidence,
            "safety_override": False,
        }

    # Safety constraint is applied after inference; model output cannot replace
    # the scheduler mapping or weaken telemetry priority in an emergency.
    if emergency:
        model_policy = result.get("model_policy")
        result = {
            **result,
            "policy": "REDUCE_VIDEO",
            "actions": POLICIES["REDUCE_VIDEO"].copy(),
            "reason": "Deterministic emergency safety override: preserve high-priority telemetry.",
            "safety_override": True,
            "override_reason": (
                "Deterministic emergency override selected REDUCE_VIDEO. "
                f"Model recommendation: {model_policy}."
                if model_policy is not None
                else "Deterministic emergency override selected REDUCE_VIDEO; model recommendation unavailable."
            ),
        }
    return result
