
import os

import streamlit as st

from ai_agent import DecisionInferenceError, choose_ai_policy
from decisions import choose_policy
from scheduler import apply_policy
from metrics import calculate_metrics, compare_policies
from simulator import run_simulation

st.set_page_config(
    page_title="FLOW STATE",
    page_icon="🚁",
    layout="wide",
)

st.title("🚁 FLOW STATE")
st.subheader("UAV Bandwidth Management Simulator")
st.caption(
    "Local prototype | Deterministic baseline policies | "
    "Simulated network conditions"
)

st.sidebar.header("Network configuration")

DEFAULT_INPUTS = {
    "flow_state_bandwidth": 5.0,
    "flow_state_latency": 80,
    "flow_state_packet_loss": 1.0,
    "flow_state_emergency": False,
    "flow_state_decision_mode": "Deterministic baseline",
}


def reset_inputs():
    for key, value in DEFAULT_INPUTS.items():
        st.session_state[key] = value
    st.session_state.pop("flow_state_last_decision", None)


with st.sidebar.form("network_configuration"):
    bandwidth = st.slider(
        "Available bandwidth (Mbps)", 0.0, 10.0, 5.0, 0.5,
        key="flow_state_bandwidth",
    )
    latency = st.slider(
        "Network latency (ms)", 0, 500, 80, 10,
        key="flow_state_latency",
    )
    packet_loss = st.slider(
        "Packet loss (%)", 0.0, 20.0, 1.0, 0.5,
        key="flow_state_packet_loss",
    )
    emergency = st.checkbox(
        "Emergency situation", value=False, key="flow_state_emergency"
    )
    decision_mode = st.segmented_control(
        "Decision mode",
        ["Deterministic baseline", "Strands Decider AI"],
        key="flow_state_decision_mode",
        default="Deterministic baseline",
        width="stretch",
    )
    submitted = st.form_submit_button(
        "Apply inputs / request new AI decision", type="primary"
    )

st.sidebar.button("Reset inputs", on_click=reset_inputs)
st.sidebar.caption(
    "Input changes take effect on submit. In AI mode, each submit requests a fresh decision."
)

conditions = {
    "bandwidth_mbps": bandwidth,
    "latency_ms": latency,
    "packet_loss_pct": packet_loss,
    "emergency": emergency,
}
baseline_decision = choose_policy(**conditions)
service_config = (
    os.getenv("FLOW_STATE_AI_URL", "http://127.0.0.1:8000"),
    os.getenv("FLOW_STATE_AI_TIMEOUT_SECONDS", "30"),
    os.getenv("FLOW_STATE_AI_FALLBACK", "1"),
)
decision_key = (
    bandwidth,
    latency,
    packet_loss,
    emergency,
    decision_mode,
    *service_config,
)
inference_error = None
needs_ai_decision = False

if submitted:
    if decision_mode == "Strands Decider AI":
        try:
            selected_decision = choose_ai_policy(**conditions)
        except (DecisionInferenceError, ValueError, TypeError) as exc:
            inference_error = str(exc)
            selected_decision = {
                **baseline_decision,
                "source": "deterministic_fallback",
                "fallback_used": True,
                "fallback_reason": "The AI request could not be completed; the deterministic baseline is shown.",
                "diagnostics": f"{type(exc).__name__}: {exc}",
                "confidence": None,
                "safety_override": False,
            }
        st.session_state["flow_state_last_decision"] = {
            "key": decision_key,
            "decision": selected_decision,
        }
    else:
        st.session_state["flow_state_last_decision"] = {
            "key": decision_key,
            "decision": {
                **baseline_decision,
                "source": "deterministic_baseline",
                "fallback_used": False,
                "fallback_reason": None,
                "diagnostics": None,
                "confidence": None,
                "safety_override": emergency,
                "override_reason": (
                    "Emergency input requires REDUCE_VIDEO to preserve high-priority telemetry."
                    if emergency else None
                ),
            },
        }

stored_decision = st.session_state.get("flow_state_last_decision")
if stored_decision and stored_decision["key"] == decision_key:
    decision = stored_decision["decision"]
else:
    decision = {
        **baseline_decision,
        "source": "deterministic_baseline",
        "fallback_used": False,
        "fallback_reason": None,
        "diagnostics": None,
        "confidence": None,
        "safety_override": emergency,
        "override_reason": (
            "Emergency input requires REDUCE_VIDEO to preserve high-priority telemetry."
            if emergency else None
        ),
    }
    needs_ai_decision = decision_mode == "Strands Decider AI"

allocation = apply_policy(
    decision["policy"],
    bandwidth,
)

metrics = calculate_metrics(
    bandwidth_mbps=bandwidth,
    latency_ms=latency,
    packet_loss_pct=packet_loss,
    policy=decision["policy"],
)

st.success("Simulation ready")

c1, c2, c3 = st.columns(3)
c1.metric("Bandwidth", f"{bandwidth:.2f} Mbps")
c2.metric("Latency", f"{latency} ms")
c3.metric("Packet loss", f"{packet_loss:.1f}%")

st.divider()
st.header("Policy decision")
st.subheader(decision["policy"])
st.write(decision["reason"])
if decision_mode == "Deterministic baseline":
    st.info("Decision source: deterministic baseline", title="Baseline decision")
    if emergency:
        st.warning(
            "Emergency input requires REDUCE_VIDEO to preserve high-priority telemetry.",
            title="Emergency override",
        )
else:
    if decision["fallback_used"]:
        st.warning(
            decision.get("fallback_reason") or "AI inference failed; baseline policy is shown.",
            title="Deterministic fallback used",
        )
    elif decision["source"] == "mock":
        st.warning("Decision source: mock inference response", title="Mock decision")
    elif needs_ai_decision:
        st.info(
            "The AI service has not been contacted for these inputs. Submit the form to request a decision.",
            title="AI decision not requested",
        )
    else:
        st.info("Decision source: Strands Decider inference", title="AI service responded")
    model_policy = decision.get("model_policy")
    if model_policy is not None:
        st.caption(f"Model recommendation: {model_policy}")
        if decision["confidence"] is not None:
            st.progress(
                decision["confidence"],
                text=f"Model-reported confidence: {decision['confidence']:.0%}",
            )
            st.caption("Confidence is informational; no cutoff is applied to policy selection.")
        if model_policy != baseline_decision["policy"]:
            st.warning(
                f"Model recommendation ({model_policy}) differs from deterministic baseline "
                f"({baseline_decision['policy']}). Review both policies for this scenario.",
                title="AI and baseline disagree",
            )
    elif decision["fallback_used"]:
        st.caption("Model recommendation and confidence are unavailable for this fallback.")
    if inference_error:
        with st.expander("Technical diagnostics"):
            st.code(decision.get("diagnostics") or inference_error)
    elif decision.get("diagnostics"):
        with st.expander("Technical diagnostics"):
            st.code(decision["diagnostics"])
    st.caption(f"Baseline policy for these same conditions: {baseline_decision['policy']}")
    if decision.get("safety_override"):
        st.warning(
            decision.get("override_reason", "Emergency safety override applied."),
            title="Emergency override",
        )
    if decision_mode == "Strands Decider AI" and not decision.get("fallback_used") and needs_ai_decision:
        st.caption("The displayed policy is the deterministic baseline until an AI request is submitted.")

left, right = st.columns(2)

with left:
    st.markdown("### Traffic allocation")
    st.json(allocation)

with right:
    st.markdown("### Simulated performance")
    st.metric(
        "Demand satisfaction",
        f"{metrics['demand_satisfaction_pct']:.1f}%",
    )
    st.metric(
        "Telemetry delivery ratio",
        f"{metrics['telemetry_delivery_ratio']:.0%}",
    )
    st.metric(
        "Effective delivery",
        f"{metrics['effective_delivery_mbps']:.3f} Mbps",
    )

st.divider()
st.header("Compare all policies")
st.caption(
    "All policies use identical inputs. Results follow the "
    "simplified traffic-demand model in metrics.py."
)

comparison = compare_policies(
    bandwidth_mbps=bandwidth,
    latency_ms=latency,
    packet_loss_pct=packet_loss,
)

st.dataframe(
    [
        {
            "Policy": row["policy"],
            "Demand satisfaction (%)": row["demand_satisfaction_pct"],
            "Telemetry delivery (%)": round(
                row["telemetry_delivery_ratio"] * 100, 1
            ),
            "Video delivery (%)": round(
                row["video_delivery_ratio"] * 100, 1
            ),
            "Sensor delivery (%)": round(
                row["sensor_delivery_ratio"] * 100, 1
            ),
            "Effective delivery (Mbps)": row["effective_delivery_mbps"],
        }
        for row in comparison
    ],
    width="stretch",
    hide_index=True,
)

if decision_mode == "Strands Decider AI":
    selected_metrics = calculate_metrics(
        bandwidth_mbps=bandwidth,
        latency_ms=latency,
        packet_loss_pct=packet_loss,
        policy=decision["policy"],
    )
    baseline_metrics = calculate_metrics(
        bandwidth_mbps=bandwidth,
        latency_ms=latency,
        packet_loss_pct=packet_loss,
        policy=baseline_decision["policy"],
    )
    st.subheader("AI versus baseline on identical conditions")
    st.caption(
        "The AI-mode row shows the final policy after any fallback or safety override. "
        "The model recommendation and confidence are shown above. All values below "
        "are simulated metrics, not field performance."
    )
    st.dataframe(
        [
            {
                "Decision": "Strands Decider AI",
                "Policy": decision["policy"],
                "Demand satisfaction (%)": selected_metrics["demand_satisfaction_pct"],
                "Telemetry delivery (%)": round(
                    selected_metrics["telemetry_delivery_ratio"] * 100, 1
                ),
                "Effective delivery (Mbps)": selected_metrics["effective_delivery_mbps"],
            },
            {
                "Decision": "Deterministic baseline",
                "Policy": baseline_decision["policy"],
                "Demand satisfaction (%)": baseline_metrics["demand_satisfaction_pct"],
                "Telemetry delivery (%)": round(
                    baseline_metrics["telemetry_delivery_ratio"] * 100, 1
                ),
                "Effective delivery (Mbps)": baseline_metrics["effective_delivery_mbps"],
            },
        ],
        width="stretch",
        hide_index=True,
    )

st.divider()
st.header("Repeatable scenario simulation")

steps = st.number_input(
    "Number of simulated steps",
    min_value=1,
    max_value=100,
    value=10,
    step=1,
)

if st.button("Run scenario simulation", type="primary"):
    results = run_simulation(steps=int(steps), seed=42)

    st.write("Generated scenarios and selected deterministic baseline policies")
    st.dataframe(
        [
            {
                "Scenario": row["scenario"],
                "Bandwidth (Mbps)": row["bandwidth_mbps"],
                "Latency (ms)": row["latency_ms"],
                "Packet loss (%)": row["packet_loss_pct"],
                "Policy": row["policy"],
                "Reason": row["reason"],
            }
            for row in results
        ],
        width="stretch",
        hide_index=True,
    )

st.caption(
    "Network conditions, traffic allocation, and performance figures are simulated; "
    "they are not field measurements or real UAV network control. Selecting AI mode "
    "does not guarantee inference: check the displayed source and fallback status."
)
