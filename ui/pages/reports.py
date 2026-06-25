"""Reports — generate and download Excel, PDF, JSON from last analysis."""
from __future__ import annotations
from datetime import datetime
import streamlit as st
from storage.report_generator import export_excel, export_json, export_pdf
from ui.components import section


def render() -> None:
    st.title("Reports")

    result  = st.session_state.get("last_result")
    system  = st.session_state.get("last_system")
    notes   = st.session_state.get("last_notes", [])
    run_id  = st.session_state.get("last_run_id", datetime.now().strftime("%Y%m%d"))

    if not result or not system:
        st.info("No analysis results yet. Run a check from **Note Applicability Check**.")
        return

    st.caption(f"Run: `{run_id}` · Note: `{result.note_number}` · System: `{result.sid}` client `{result.client}`")
    st.divider()
    section("Generate & Download")

    if st.button("⚡ Generate All Reports", type="primary", use_container_width=True):
        with st.spinner("Building reports…"):
            try:
                st.session_state["rpt_excel"] = export_excel([result], system, notes)
                st.session_state["rpt_pdf"]   = export_pdf([result], system)
                st.session_state["rpt_json"]  = export_json([result], system, notes)
                st.success("All reports ready.")
            except Exception as exc:
                st.error(f"Report generation failed: {exc}")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**📊 Excel**")
        st.caption("Summary · Evidence · Inventory · Note Metadata")
        st.download_button("⬇ Download Excel",
                           data=st.session_state.get("rpt_excel", b""),
                           file_name=f"sap_{result.note_number}_{result.sid}_{run_id}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           disabled="rpt_excel" not in st.session_state,
                           use_container_width=True)
    with c2:
        st.markdown("**📄 PDF**")
        st.caption("Audit-ready PDF with full evidence")
        st.download_button("⬇ Download PDF",
                           data=st.session_state.get("rpt_pdf", b""),
                           file_name=f"sap_{result.note_number}_{result.sid}_{run_id}.pdf",
                           mime="application/pdf",
                           disabled="rpt_pdf" not in st.session_state,
                           use_container_width=True)
    with c3:
        st.markdown("**🔗 JSON**")
        st.caption("Machine-readable for SIEM / ticketing integration")
        st.download_button("⬇ Download JSON",
                           data=st.session_state.get("rpt_json", b""),
                           file_name=f"sap_{result.note_number}_{result.sid}_{run_id}.json",
                           mime="application/json",
                           disabled="rpt_json" not in st.session_state,
                           use_container_width=True)
