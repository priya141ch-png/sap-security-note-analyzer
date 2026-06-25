"""Risk Deep-Dive page — per-SID gauges and detailed risk breakdown."""

from __future__ import annotations
import streamlit as st
from ui.components import section, show_risk
from ui import charts


def render() -> None:
    st.title("Risk Deep-Dive")

    risk = st.session_state.get("risk", [])
    results = st.session_state.get("results", [])
    notes = st.session_state.get("notes", [])

    if not risk:
        st.info("Run an analysis first to see risk data.")
        return

    # ── Top gauges row ───────────────────────────────────────────────────────
    section("Risk Score Gauges — Top SIDs")
    top = sorted(risk, key=lambda s: s.risk_score, reverse=True)[:6]
    cols = st.columns(min(len(top), 3))
    for i, rs in enumerate(top):
        with cols[i % 3]:
            st.plotly_chart(charts.risk_gauge(rs.risk_score, rs.sid),
                            use_container_width=True)

    st.divider()

    # ── Risk bar ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns([1, 1])
    with col1:
        st.plotly_chart(charts.risk_bar(risk), use_container_width=True)
    with col2:
        st.plotly_chart(charts.exposure_scatter(risk), use_container_width=True)

    section("Severity Stack per SID")
    st.plotly_chart(charts.severity_per_sid(risk), use_container_width=True)

    # ── Table ────────────────────────────────────────────────────────────────
    section("Risk Summary Table")
    show_risk(risk)

    # ── SID drilldown ────────────────────────────────────────────────────────
    st.divider()
    section("SID Drilldown — Applicable Notes")
    from ui.components import show_results
    sids = sorted({r.sid for r in results})
    picked = st.selectbox("Select SID", sids, key="risk_sid_pick")
    sid_results = [r for r in results if r.sid == picked and r.status == "Applicable"]
    if sid_results:
        show_results(sid_results, notes, key_prefix=f"risk_{picked}")
    else:
        st.success(f"No applicable notes for {picked}.")
