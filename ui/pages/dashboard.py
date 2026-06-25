"""Dashboard — KPI overview and charts from the most recent analysis."""
from __future__ import annotations
import streamlit as st
from ui.components import kpi_live_overview, section
from ui import charts
from rfc.connector import PYRFC_AVAILABLE, is_relay_connected


def render() -> None:
    st.title("Dashboard")

    result  = st.session_state.get("last_result")
    system  = st.session_state.get("last_system")
    history = []
    try:
        from ui.run_history import list_runs
        history = list_runs()
    except Exception:
        pass

    if not PYRFC_AVAILABLE:
        relay_ok = is_relay_connected()
        if relay_ok:
            st.success(
                "🔗 **Relay connected** — RFC calls are bridged through your VPN laptop. "
                "Live SAP connectivity is active."
            )
        else:
            st.info(
                "🔌 **RFC via Relay** — To run live SAP checks, connect to your office VPN "
                "and double-click **`relay\\relay.bat`** on your laptop. Keep that window open. "
                "No installation required on this machine."
            )

    kpi_live_overview(result, system, history)

    if not result:
        st.info("No analysis run yet. Go to **Note Applicability Check** to start.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        st.plotly_chart(charts.single_result_gauge(result), use_container_width=True)
    with col2:
        st.plotly_chart(charts.evidence_radar(result), use_container_width=True)

    if len(history) > 1:
        section("Run History Trend")
        st.plotly_chart(charts.history_trend(history), use_container_width=True)

    if system and system.components:
        section("System Component Overview")
        col3, col4 = st.columns([1, 1])
        with col3:
            st.plotly_chart(charts.component_sp_bar(system), use_container_width=True)
        with col4:
            st.plotly_chart(charts.implemented_notes_pie(system), use_container_width=True)
