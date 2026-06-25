"""Results & Evidence — full drilldown of the last analysis result."""
from __future__ import annotations
import json
import pandas as pd
import streamlit as st
from ui.components import section
from ui import charts

_STATUS_ICON = {
    "Applicable":           "🔴",
    "Not Applicable":       "🟢",
    "Already Implemented":  "🔵",
    "Needs Manual Review":  "🟡",
    "Insufficient Data":    "⚪",
}


def render() -> None:
    st.title("Results & Evidence")

    result = st.session_state.get("last_result")
    system = st.session_state.get("last_system")

    if not result:
        st.info("No results yet — run a check from **Note Applicability Check**.")
        return

    icon = _STATUS_ICON.get(result.status, "⬜")
    st.markdown(f"<h2 style='margin-bottom:4px'>{icon} {result.status}</h2>",
                unsafe_allow_html=True)
    st.caption(
        f"Note **{result.note_number}** · {result.note_title or '—'} · "
        f"Severity: **{result.note_severity or '—'}** · CVSS: **{result.note_cvss or '—'}** · "
        f"System: **{result.sid}** client **{result.client}** · Checked: {result.checked_at}"
    )

    tab_ev, tab_inv, tab_chart, tab_json = st.tabs([
        "📋 Evidence", "🖥️ System Inventory", "📊 Charts", "🔎 Raw JSON"])

    with tab_ev:
        ev = result.evidence
        section("Decision")
        st.info(f"**Reason:** {ev.reason}")
        st.success(f"**Recommended Action:** {result.recommended_action}")

        section("Component Check")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Required Component", ev.component.required_component)
        c2.metric("Component Found", "✅ Yes" if ev.component.component_found else "❌ No")
        c3.metric("Installed Release", ev.component.installed_release or "—")
        c4.metric("Required Release",  ev.component.required_release  or "—")
        if ev.component.release_match is not None:
            if ev.component.release_match:
                st.success("Release match: ✅")
            else:
                st.error("Release mismatch: ❌ (different release — not in scope)")

        section("Support Package Check")
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Installed SP", ev.sp.installed_sp or "—")
        c6.metric("Required SP From", ev.sp.required_sp_from or "—")
        c7.metric("Required SP To", ev.sp.required_sp_to or "—")
        c8.metric("SP In Range",
                  ("✅ Yes" if ev.sp.in_range else "❌ No")
                  if ev.sp.in_range is not None else "N/A")

        section("Note Implementation Check (CWBNTCUST)")
        c9, c10, c11, c12 = st.columns(4)
        c9.metric("In CWBNTCUST", "Yes" if ev.implementation.note_in_cwbntcust else "No")
        c10.metric("PRSTATUS", ev.implementation.prstatus or "—")
        c11.metric("Already Implemented", "✅ Yes" if ev.implementation.already_implemented else "No")
        c12.metric("Confidence", f"{result.confidence:.0%}")

        section("Kernel")
        st.code(f"Kernel release: {ev.kernel_release or '—'}   Patch level: {ev.kernel_patch or '—'}")
        st.progress(result.confidence)

    with tab_inv:
        if system:
            section(f"{system.sid} — {len(system.components)} Components")
            if system.components:
                df = pd.DataFrame([{
                    "Component": c.name, "Release": c.release,
                    "SP": c.sp_level, "Patch": c.patch_level,
                } for c in system.components])
                q = st.text_input("Filter", key="res_comp_q", placeholder="SAP_BASIS…")
                if q:
                    df = df[df["Component"].str.contains(q, case=False)]
                st.dataframe(df, use_container_width=True, hide_index=True)

            section(f"Implemented Notes ({len(system.implemented_notes)})")
            if system.implemented_notes:
                cols = st.columns(6)
                for i, n in enumerate(system.implemented_notes[:48]):
                    cols[i % 6].code(n)
        else:
            st.info("Collect inventory first.")

    with tab_chart:
        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(charts.single_result_gauge(result), use_container_width=True)
        with col2:
            st.plotly_chart(charts.evidence_radar(result), use_container_width=True)
        if system:
            st.plotly_chart(charts.component_sp_bar(system), use_container_width=True)

    with tab_json:
        from storage.report_generator import _r2d
        st.json(json.dumps(_r2d(result), indent=2))
