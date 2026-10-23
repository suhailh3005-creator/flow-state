"""FLOW STATE: a calm, local-first UAV bandwidth-management simulator."""

from __future__ import annotations

import html
import os
from pathlib import Path

import streamlit as st

from ai_agent import DecisionInferenceError, choose_ai_policy
from bedrock_explainer import BedrockExplanationError, explain_decision
from decisions import choose_policy
from metrics import calculate_metrics, compare_policies
from scheduler import apply_policy
from simulator import run_simulation


st.set_page_config(
    page_title="FLOW STATE — UAV network simulator",
    page_icon="✳",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SUPPORTED_THEMES = ("Dark", "Light")
DEFAULT_THEME = "Dark"

if "flow_state_theme" not in st.session_state:
    st.session_state["flow_state_theme"] = DEFAULT_THEME
if "_prev_flow_state_theme" not in st.session_state:
    st.session_state["_prev_flow_state_theme"] = DEFAULT_THEME


def on_theme_change() -> None:
    chosen = st.session_state.get("flow_state_theme")
    if chosen not in SUPPORTED_THEMES:
        st.session_state["flow_state_theme"] = st.session_state.get(
            "_prev_flow_state_theme", DEFAULT_THEME
        )
    else:
        st.session_state["_prev_flow_state_theme"] = chosen


active_theme = st.session_state.get("flow_state_theme") or st.session_state.get(
    "_prev_flow_state_theme", DEFAULT_THEME
)

CSS = Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
theme_override_css = ""
if active_theme == "Light":
    theme_override_css = """
/* Active theme override: Light */
:root, [data-testid="stAppViewContainer"], [data-testid="stApp"], .stApp {
  --color-background: #F8F9FA;
  --color-surface: #FFFFFF;
  --color-surface-secondary: #EDF2F7;
  --color-surface-elevated: #E2E8F0;
  --color-text: #1A202C;
  --color-text-secondary: #4A5568;
  --color-text-secondary-readable: #2D3748;
  --color-text-muted: #718096;
  --color-accent: #0F766E;
  --color-accent-hover: #115E59;
  --color-accent-subtle: rgba(15, 118, 110, 0.12);
  --color-accent-blue: #1D4ED8;
  --color-success: #15803D;
  --color-warning: #B45309;
  --color-error: #C53030;
  --color-sage: #15803D;
  --color-border: #CBD5E0;
  --color-card-shadow: rgba(0, 0, 0, 0.06);
  --color-overview-shadow: rgba(0, 0, 0, 0.08);
  --color-primary-button-text: #FFFFFF;
  --color-secondary-button-bg: rgba(15, 118, 110, 0.08);
  --color-secondary-button-border: rgba(15, 118, 110, 0.42);
  --color-secondary-button-hover-bg: rgba(15, 118, 110, 0.15);
  --color-overview-orbit: rgba(15, 118, 110, 0.2);
  --color-overview-orbit-subtle: rgba(15, 118, 110, 0.15);
  --color-overview-orbit-faint: rgba(15, 118, 110, 0.12);
  --color-explanation-bg: rgba(15, 118, 110, 0.06);
  --color-explanation-border: rgba(15, 118, 110, 0.35);
}
"""
st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Source+Sans+3:wght@400;500;600;700&display=swap" rel="stylesheet">
    """,
    unsafe_allow_html=True,
)
st.html(f"<style>\n{CSS}\n{theme_override_css}\n</style>")

DEFAULT_INPUTS = {
    "flow_state_bandwidth": 5.0,
    "flow_state_latency": 80,
    "flow_state_packet_loss": 1.0,
    "flow_state_emergency": False,
    "flow_state_decision_mode": "Deterministic baseline",
}


def reset_inputs() -> None:
    for key, value in DEFAULT_INPUTS.items():
        st.session_state[key] = value
    st.session_state.pop("flow_state_last_decision", None)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def source_label(decision: dict, decision_mode: str, needs_ai_decision: bool) -> tuple[str, str]:
    if decision.get("source") == "mock":
        return "Mock Strands response", "coral"
    if decision.get("source") == "strands_decider":
        return "Strands Decider 2B · live response", "sage"
    if decision.get("fallback_used"):
        return "Deterministic fallback", "coral"
    if decision_mode == "Strands Decider AI" and needs_ai_decision:
        return "AI decision not requested · showing baseline", "coral"
    return "Deterministic baseline", "sage"


def render_policy_card(
    decision: dict,
    baseline_decision: dict,
    decision_mode: str,
    needs_ai_decision: bool,
    emergency: bool,
) -> None:
    label, tone = source_label(decision, decision_mode, needs_ai_decision)
    policy_tone = "coral" if emergency else "sage"
    model_policy = decision.get("model_policy")
    confidence = decision.get("confidence")
    facts = [f"Baseline <strong>{esc(baseline_decision['policy'])}</strong>"]
    if model_policy:
        facts.insert(0, f"Strands recommendation <strong>{esc(model_policy)}</strong>")
    if confidence is not None:
        facts.append(f"Model confidence <strong>{confidence:.0%}</strong>")

    st.markdown(
        f"""
        <article class="result-card" aria-label="Policy decision result">
          <div class="result-top">
            <div>
              <div class="section-kicker">Decision result</div>
              <h2 class="result-title">{esc(decision['policy'])}</h2>
              <div class="result-reason">{esc(decision['reason'])}</div>
            </div>
            <div>
              <span class="policy-pill {policy_tone}">{'Emergency override' if emergency else 'Selected policy'}</span>
              <div style="height:8px"></div>
              <span class="source-pill {tone}">{esc(label)}</span>
            </div>
          </div>
          <div class="result-facts">{' '.join(f'<span class="fact-chip">{item}</span>' for item in facts)}</div>
        </article>
        """,
        unsafe_allow_html=True,
    )

    if decision_mode == "Strands Decider AI" and not decision.get("fallback_used"):
        if model_policy and model_policy != baseline_decision["policy"]:
            st.info(
                f"The model recommended {model_policy}; the deterministic baseline recommends "
                f"{baseline_decision['policy']}. The recommendation is advisory, and both "
                "are shown for the same simulated conditions."
            )
    if decision.get("fallback_used"):
        st.warning(
            decision.get("fallback_reason")
            or "AI inference did not complete; the deterministic baseline is shown.",
            icon="↩",
        )
        diagnostics = decision.get("diagnostics")
        if diagnostics:
            with st.expander("Technical details"):
                st.code(diagnostics)
    if decision.get("safety_override") or emergency:
        st.warning(
            decision.get(
                "override_reason",
                "Emergency mode is active. REDUCE_VIDEO is applied to preserve high-priority telemetry.",
            ),
            icon="◇",
        )


def render_allocation(allocation: dict, bandwidth_mbps: float) -> None:
    streams = (
        ("telemetry", allocation["telemetry_mbps"], "telemetry"),
        ("video", allocation["video_mbps"], "video"),
        ("sensors", allocation["sensors_mbps"], "sensors"),
    )
    segments = []
    labels = []
    for label, amount, tone in streams:
        percentage = (amount / bandwidth_mbps * 100) if bandwidth_mbps else 0
        segments.append(
            f'<span class="allocation-segment {tone}" style="width:{percentage:.4f}%" '
            f'title="{label.title()}: {amount:.3f} Mbps"></span>'
        )
        labels.append(
            f'<div class="allocation-legend-item"><span class="legend-dot {tone}"></span>{label.title()}'
            f'<strong>{amount:.3f} Mbps</strong></div>'
        )
    alt_text = "; ".join(f"{name}: {value:.3f} Mbps" for name, value, _ in streams)
    st.markdown(
        f"""
        <div class="allocation-card">
          <div class="section-kicker">Traffic allocation · simulated</div>
          <div class="allocation-bar" role="img" aria-label="{esc(alt_text)}">{''.join(segments)}</div>
          <div class="allocation-legend">{''.join(labels)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_grid(bandwidth: float, latency: int, loss: float, metrics: dict) -> None:
    values = (
        ("Available bandwidth", f"{bandwidth:.2f}", "Mbps · simulated input"),
        ("Network latency", f"{latency}", "ms · simulated input"),
        ("Packet loss", f"{loss:.1f}", "% · simulated input"),
        ("Telemetry delivery", f"{metrics['telemetry_delivery_ratio']:.0%}", "calculated estimate"),
    )
    tiles = []
    for label, value, note in values:
        tiles.append(
            f'<div class="metric-tile"><div class="metric-label">{esc(label)}</div>'
            f'<div class="metric-number">{esc(value)}<span style="font-size:.82rem;font-weight:500">'
            f' {esc(note.split(" · ")[0] if " · " in note else "")}</span></div>'
            f'<div class="metric-note">{esc(note)}</div></div>'
        )
    st.markdown(f'<div class="metric-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)


def render_comparison_table(rows: list[dict]) -> None:
    """Render the existing computed policy results in an accessible editorial table."""
    headers = (
        "Selected", "Policy", "Demand satisfaction (%)", "Telemetry delivery (%)",
        "Video delivery (%)", "Sensor delivery (%)", "Effective delivery (Mbps)",
    )
    head = "".join(f"<th scope=\"col\">{esc(label)}</th>" for label in headers)
    body = []
    for row in rows:
        selected = row["Selected"] == "Current"
        cells = []
        for label in headers:
            value = row[label]
            if label == "Selected":
                value = '<span class="current-marker">Current</span>' if selected else '<span aria-label="Not selected">—</span>'
            else:
                value = esc(value)
            cells.append(f"<td>{value}</td>")
        body.append(f'<tr class="{"is-selected" if selected else ""}">{"".join(cells)}</tr>')
    st.markdown(
        f"""
        <div class="comparison-scroll" role="region" aria-label="Policy comparison table" tabindex="0">
          <table class="comparison-table">
            <caption>Calculated policy outcomes for the same simulated network inputs</caption>
            <thead><tr>{head}</tr></thead>
            <tbody>{''.join(body)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


nav_cols = st.columns([3.1, 0.9], vertical_alignment="center")
with nav_cols[0]:
    st.markdown(
        """
        <nav class="quiet-nav" aria-label="FLOW STATE product navigation">
          <div class="brand-lockup">
            <svg class="brand-mark" viewBox="0 0 40 40" role="img" aria-label="FLOW STATE flight path mark">
              <rect x="1" y="1" width="38" height="38" rx="13" class="brand-mark-bg"/>
              <path d="M8 25.5c5.3 0 5.2-11 10.8-11 5.2 0 4.8 11 10.4 11 1.2 0 2.1-.4 3-.9" fill="none" stroke="var(--color-accent)" stroke-width="2.1" stroke-linecap="round"/>
              <circle cx="8" cy="25.5" r="2" fill="var(--color-accent-blue)"/><circle cx="32" cy="24.6" r="2" fill="var(--color-sage)"/>
            </svg>
            <div class="brand-name"><strong>FLOW STATE</strong><span>UAV network simulator</span></div>
          </div>
          <div class="nav-statuses">
            <span class="nav-pill sage">Simulation environment</span>
            <span class="nav-pill">Strands · local request on evaluate</span>
          </div>
        </nav>
        """,
        unsafe_allow_html=True,
    )
with nav_cols[1]:
    st.segmented_control(
        "Theme",
        options=["Dark", "Light"],
        key="flow_state_theme",
        on_change=on_theme_change,
        label_visibility="collapsed",
    )

bandwidth_value = st.session_state.get("flow_state_bandwidth", DEFAULT_INPUTS["flow_state_bandwidth"])
latency_value = st.session_state.get("flow_state_latency", DEFAULT_INPUTS["flow_state_latency"])
loss_value = st.session_state.get("flow_state_packet_loss", DEFAULT_INPUTS["flow_state_packet_loss"])
emergency_value = st.session_state.get("flow_state_emergency", DEFAULT_INPUTS["flow_state_emergency"])
initial_baseline = choose_policy(bandwidth_value, latency_value, loss_value, emergency_value)
initial_policy = (
    st.session_state.get("flow_state_last_decision", {}).get("decision", {}).get("policy")
    or initial_baseline["policy"]
)

st.markdown(
    f"""
    <section class="hero-grid" aria-label="FLOW STATE overview">
      <div class="hero-copy">
        <div class="eyebrow">Intelligent network management</div>
        <h1>Keep every signal in balance.</h1>
        <p>Explore how bandwidth, latency, and packet loss shape UAV communications. Test adaptive traffic policies and see how the system responds.</p>
        <div class="hero-tags"><span class="hero-tag">Strands Decider 2B</span><span class="hero-tag">Adaptive traffic policies</span></div>
      </div>
      <aside class="overview-card" aria-label="Current simulated network overview">
        <div class="overview-top"><div><div class="overview-label">Current policy · simulated</div>
          <div class="overview-policy">{esc(initial_policy)}</div></div>
          <span class="policy-pill {'coral' if emergency_value else 'sage'}">{'Emergency' if emergency_value else 'Ready to evaluate'}</span>
        </div>
        <div class="overview-grid">
          <div><div class="overview-value">{bandwidth_value:.2f} Mbps</div><div class="overview-mini-label">Bandwidth</div></div>
          <div><div class="overview-value">{latency_value} ms</div><div class="overview-mini-label">Latency</div></div>
          <div><div class="overview-value">{loss_value:.1f}%</div><div class="overview-mini-label">Packet loss</div></div>
        </div>
        <div class="overview-rule"></div>
        <div class="overview-foot"><span class="status-dot"></span>Traffic shares follow the selected policy</div>
      </aside>
    </section>
    """,
    unsafe_allow_html=True,
)

st.markdown('<span id="simulator"></span><div class="section-kicker">The simulator</div><h2 class="section-heading">Shape your network conditions</h2><p class="section-intro">Adjust the scenario, choose how a policy is selected, then evaluate the simulated network.</p>', unsafe_allow_html=True)

with st.container(border=True, key="simulator_workspace"):
    with st.form("network_configuration"):
        input_cols = st.columns(3, gap="large")
        with input_cols[0]:
            st.markdown('<div class="field-note">Capacity available to carry telemetry, video, and sensor traffic.</div>', unsafe_allow_html=True)
            bandwidth = st.slider(
                "Available bandwidth (Mbps)", 0.0, 10.0, 5.0, 0.5,
                key="flow_state_bandwidth",
                help="Simulated link capacity. This value is not measured from a real UAV.",
            )
        with input_cols[1]:
            st.markdown('<div class="field-note">Delay on the simulated link, from sender to receiver.</div>', unsafe_allow_html=True)
            latency = st.slider(
                "Network latency (ms)", 0, 500, 80, 10,
                key="flow_state_latency",
                help="Simulated end-to-end delay in milliseconds.",
            )
        with input_cols[2]:
            st.markdown('<div class="field-note">Share of packets assumed lost in this scenario.</div>', unsafe_allow_html=True)
            packet_loss = st.slider(
                "Packet loss (%)", 0.0, 20.0, 1.0, 0.5,
                key="flow_state_packet_loss",
                help="Simulated packet loss. The metric model applies this to successful delivery.",
            )

        mode_cols = st.columns([1.1, 1.2, 1.2], gap="large", vertical_alignment="center")
        with mode_cols[0]:
            emergency = st.checkbox(
                "Emergency mode", value=False, key="flow_state_emergency",
                help="When active, REDUCE_VIDEO takes precedence to preserve high-priority telemetry.",
            )
        with mode_cols[1]:
            decision_mode = st.segmented_control(
                "Decision mode",
                ["Deterministic baseline", "Strands Decider AI"],
                key="flow_state_decision_mode",
                default="Deterministic baseline",
                width="stretch",
                help="AI mode requests one constrained choice from the configured local Strands service when evaluated.",
            )
        with mode_cols[2]:
            submitted = st.form_submit_button("Evaluate network", type="primary", use_container_width=True)

    if emergency:
        st.markdown('<div class="emergency-note">Emergency mode is active. The deterministic safety override selects <strong>REDUCE_VIDEO</strong> and keeps telemetry at high priority.</div>', unsafe_allow_html=True)

reset_col, note_col = st.columns([1, 3], vertical_alignment="center")
with reset_col:
    st.button("Restore defaults", key="flow_state_reset", on_click=reset_inputs, type="secondary")
with note_col:
    st.caption("Input changes are applied when you evaluate. In AI mode, only an explicit evaluation submits an inference request.")

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
    bandwidth, latency, packet_loss, emergency, decision_mode, *service_config,
)
needs_ai_decision = False

if submitted:
    if decision_mode == "Strands Decider AI":
        try:
            selected_decision = choose_ai_policy(**conditions)
        except (DecisionInferenceError, ValueError, TypeError) as exc:
            selected_decision = {
                **baseline_decision,
                "source": "deterministic_fallback",
                "fallback_used": True,
                "fallback_reason": "The AI request could not be completed; the deterministic baseline is shown.",
                "diagnostics": f"{type(exc).__name__}: {exc}",
                "confidence": None,
                "safety_override": emergency,
                "override_reason": (
                    "Deterministic emergency override selected REDUCE_VIDEO to preserve high-priority telemetry."
                    if emergency else None
                ),
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

allocation = apply_policy(decision["policy"], bandwidth)
metrics = calculate_metrics(
    bandwidth_mbps=bandwidth,
    latency_ms=latency,
    packet_loss_pct=packet_loss,
    policy=decision["policy"],
)

st.markdown('<div class="section-kicker">The outcome</div><h2 class="section-heading">Your network, in balance.</h2><p class="section-intro">A policy recommendation for this simulated scenario, with its source and safety state kept visible.</p>', unsafe_allow_html=True)
render_policy_card(decision, baseline_decision, decision_mode, needs_ai_decision, emergency)

if decision_mode == "Strands Decider AI" and decision.get("model_policy") is not None and decision.get("confidence") is not None:
    st.progress(decision["confidence"], text=f"Model-reported confidence · {decision['confidence']:.0%} (informational)")
elif needs_ai_decision:
    st.caption("Strands has not been contacted for these inputs. Evaluate the network to request a decision.")

st.markdown('<div style="height:22px"></div><div class="section-kicker">How capacity is shared</div><h2 class="section-heading">Traffic allocation</h2><p class="section-intro">The policy distributes the available simulated bandwidth across three traffic streams.</p>', unsafe_allow_html=True)
render_allocation(allocation, bandwidth)

st.markdown('<div style="height:22px"></div><div class="section-kicker">Calculated from this scenario</div><h2 class="section-heading">Network outlook</h2><p class="section-intro">Inputs and delivery estimates are simulated; these are not UAV measurements.</p>', unsafe_allow_html=True)
render_metric_grid(bandwidth, latency, packet_loss, metrics)
outlook_cols = st.columns(2)
with outlook_cols[0]:
    st.metric("Demand satisfaction", f"{metrics['demand_satisfaction_pct']:.1f}%", help="Simulated delivery against the model's illustrative traffic demand.")
with outlook_cols[1]:
    st.metric("Effective delivery", f"{metrics['effective_delivery_mbps']:.3f} Mbps", help="Calculated delivery after applying simulated packet loss.")

# Bedrock is optional and explains the already selected policy only.
st.markdown('<div style="height:22px"></div><div class="section-kicker">Optional explanation</div><h2 class="section-heading">Nova Lite explanation</h2>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown('<div class="explanation-panel"><strong>Amazon Bedrock explains this policy; it does not choose or change it.</strong><br><span class="explanation-note">Generate an explanation only when you choose the button. Model access is required.</span></div>', unsafe_allow_html=True)
    explanation_key = (
        bandwidth, latency, packet_loss, emergency, decision["policy"], decision["reason"],
    )
    if st.button("Generate Nova Lite explanation", key="flow_state_explain_bedrock", type="secondary"):
        with st.spinner("Requesting an explanation from Amazon Bedrock…"):
            try:
                explanation = explain_decision(
                    bandwidth_mbps=bandwidth,
                    latency_ms=latency,
                    packet_loss_pct=packet_loss,
                    policy=decision["policy"],
                    reason=decision["reason"],
                    emergency=emergency,
                )
                st.session_state["flow_state_bedrock_result"] = {
                    "key": explanation_key, "text": explanation, "error": None,
                }
            except (BedrockExplanationError, ValueError, TypeError) as exc:
                st.session_state["flow_state_bedrock_result"] = {
                    "key": explanation_key,
                    "text": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    bedrock_result = st.session_state.get("flow_state_bedrock_result")
    if bedrock_result and bedrock_result.get("key") == explanation_key:
        if bedrock_result.get("text"):
            st.markdown(bedrock_result["text"])
            st.caption("Generated by Amazon Bedrock Nova Lite. Network inputs and outcomes remain simulated.")
        elif bedrock_result.get("error"):
            st.warning("Amazon Bedrock is unavailable or returned an invalid response. Showing local explanatory text; no AWS response was generated.")
            local_explanations = {
                "BALANCED": "BALANCED keeps a compromise among video, telemetry, and sensor traffic under the current simulated conditions.",
                "PROTECT_TELEMETRY": "PROTECT_TELEMETRY shifts capacity toward essential telemetry when the simulated link is constrained.",
                "REDUCE_VIDEO": "REDUCE_VIDEO limits video traffic to free simulated capacity for higher-priority communications.",
                "DEFER_SENSORS": "DEFER_SENSORS delays nonessential sensor traffic to conserve simulated capacity for higher-priority data.",
            }
            if emergency:
                st.markdown("**Emergency override remains active.** Explanatory text does not change the selected policy.")
            st.markdown(local_explanations.get(decision["policy"], "The selected policy follows the simulator's rules."))
            st.caption("Local fallback explanation · not generated by Bedrock or an LLM.")

st.markdown('<div style="height:22px"></div><div class="section-kicker">Same conditions, four policies</div><h2 class="section-heading">Compare all policies</h2><p class="section-intro">Every row uses the same simulated network inputs and the existing traffic-demand model.</p>', unsafe_allow_html=True)
comparison = compare_policies(
    bandwidth_mbps=bandwidth,
    latency_ms=latency,
    packet_loss_pct=packet_loss,
)
comparison_rows = []
for row in comparison:
    comparison_rows.append({
        "Selected": "Current" if row["policy"] == decision["policy"] else "",
        "Policy": row["policy"],
        "Demand satisfaction (%)": row["demand_satisfaction_pct"],
        "Telemetry delivery (%)": round(row["telemetry_delivery_ratio"] * 100, 1),
        "Video delivery (%)": round(row["video_delivery_ratio"] * 100, 1),
        "Sensor delivery (%)": round(row["sensor_delivery_ratio"] * 100, 1),
        "Effective delivery (Mbps)": row["effective_delivery_mbps"],
    })
render_comparison_table(comparison_rows)

if decision_mode == "Strands Decider AI":
    st.markdown("#### AI and baseline · identical conditions")
    st.caption("Final AI-mode metrics include any deterministic fallback or emergency override. All values below are simulated.")
    selected_metrics = calculate_metrics(
        bandwidth_mbps=bandwidth, latency_ms=latency,
        packet_loss_pct=packet_loss, policy=decision["policy"],
    )
    baseline_metrics = calculate_metrics(
        bandwidth_mbps=bandwidth, latency_ms=latency,
        packet_loss_pct=packet_loss, policy=baseline_decision["policy"],
    )
    st.dataframe([
        {
            "Decision": "Strands Decider AI · final policy",
            "Policy": decision["policy"],
            "Demand satisfaction (%)": selected_metrics["demand_satisfaction_pct"],
            "Telemetry delivery (%)": round(selected_metrics["telemetry_delivery_ratio"] * 100, 1),
            "Effective delivery (Mbps)": selected_metrics["effective_delivery_mbps"],
        },
        {
            "Decision": "Deterministic baseline",
            "Policy": baseline_decision["policy"],
            "Demand satisfaction (%)": baseline_metrics["demand_satisfaction_pct"],
            "Telemetry delivery (%)": round(baseline_metrics["telemetry_delivery_ratio"] * 100, 1),
            "Effective delivery (Mbps)": baseline_metrics["effective_delivery_mbps"],
        },
    ], width="stretch", hide_index=True)

st.markdown('<div style="height:22px"></div><div class="section-kicker">Repeatable scenarios</div><h2 class="section-heading">Explore a small flight set</h2><p class="section-intro">Generate a seeded sequence of simulated conditions and baseline decisions.</p>', unsafe_allow_html=True)
scenario_cols = st.columns([1, 2], vertical_alignment="bottom")
with scenario_cols[0]:
    steps = st.number_input("Number of simulated steps", min_value=1, max_value=100, value=10, step=1)
with scenario_cols[1]:
    run_scenarios = st.button("Run scenario simulation", key="flow_state_run_simulation", type="secondary")
if run_scenarios:
    results = run_simulation(steps=int(steps), seed=42)
    st.dataframe([
        {
            "Scenario": row["scenario"],
            "Bandwidth (Mbps)": row["bandwidth_mbps"],
            "Latency (ms)": row["latency_ms"],
            "Packet loss (%)": row["packet_loss_pct"],
            "Policy": row["policy"],
            "Reason": row["reason"],
        }
        for row in results
    ], width="stretch", hide_index=True)

st.markdown(
    """
    <footer class="product-footer">
      <div><strong>FLOW STATE</strong><br>A thoughtful approach to UAV network management.<br><a href="https://github.com/suhailh3005-creator/flow-state" target="_blank" rel="noreferrer">Project repository</a></div>
      <div>All network conditions and performance values are simulated, not field measurements.</div>
    </footer>
    """,
    unsafe_allow_html=True,
)
