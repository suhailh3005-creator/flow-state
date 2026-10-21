
import streamlit as st

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

bandwidth = st.sidebar.slider(
    "Available bandwidth (Mbps)", 0.0, 10.0, 5.0, 0.5
)
latency = st.sidebar.slider(
    "Network latency (ms)", 0, 500, 80, 10
)
packet_loss = st.sidebar.slider(
    "Packet loss (%)", 0.0, 20.0, 1.0, 0.5
)
emergency = st.sidebar.checkbox("Emergency situation", value=False)

if st.sidebar.button("Reset inputs"):
    st.rerun()

decision = choose_policy(
    bandwidth_mbps=bandwidth,
    latency_ms=latency,
    packet_loss_pct=packet_loss,
    emergency=emergency,
)

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
    use_container_width=True,
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

    st.write("Generated scenarios and selected baseline policies")
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
        use_container_width=True,
        hide_index=True,
    )

st.caption(
    "AI integration pending: this version uses deterministic rules, "
    "not Strands Decider 2B. Performance figures are simulated."
)
