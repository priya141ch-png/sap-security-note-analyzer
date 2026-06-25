"""Reusable UI components — KPI cards, section headers."""
from __future__ import annotations
import streamlit as st


def section(title: str) -> None:
    st.markdown(f'<div class="section-header">{title}</div>', unsafe_allow_html=True)


def _kpi(label: str, value, sub: str = "", variant: str = "") -> str:
    cls = f"kpi-card {variant}".strip()
    return (
        f'<div class="{cls}">'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        + (f'<div class="kpi-sub">{sub}</div>' if sub else "")
        + "</div>"
    )


def show_validation(landscape, notes: list) -> None:
    """Show a validation summary table after running the upload pipeline."""
    import pandas as pd
    st.subheader("Validation Summary")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("**Systems parsed**")
        if landscape and landscape.systems:
            rows = [{"SID": s.sid, "Release": getattr(s, "release", "—"),
                     "Environment": getattr(s, "environment", "—"),
                     "Components": len(getattr(s, "components", []))}
                    for s in landscape.systems]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No systems found.")
    with col2:
        st.caption("**Notes parsed**")
        if notes:
            rows = [{"Note #": n.note_number, "Title": (n.title or "")[:50],
                     "Severity": getattr(n, "severity", "—"),
                     "Warnings": len(getattr(n, "parser_warnings", []))}
                    for n in notes]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No notes parsed.")


def show_risk(risk_list: list) -> None:
    """Display risk summary table for a list of SidRiskSummary objects."""
    import pandas as pd
    if not risk_list:
        st.info("No risk data available.")
        return
    rows = []
    for r in sorted(risk_list, key=lambda x: x.risk_score, reverse=True):
        rows.append({
            "SID": r.sid,
            "Risk Score": round(r.risk_score, 1),
            "Applicable": getattr(r, "applicable_count", "—"),
            "Avg CVSS": round(getattr(r, "avg_cvss", 0), 1),
            "Environment": getattr(r, "environment", "—"),
            "Critical": getattr(r, "severity_counts", {}).get("Critical", 0),
            "High": getattr(r, "severity_counts", {}).get("High", 0),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def show_results(results: list, notes: list, key_prefix: str = "") -> None:
    """Display applicability results as a sortable table."""
    import pandas as pd
    if not results:
        st.info("No results to display.")
        return
    note_map = {n.note_number: n for n in (notes or [])}
    rows = []
    for r in results:
        meta = note_map.get(getattr(r, "note_number", ""), None)
        rows.append({
            "Note #": getattr(r, "note_number", "—"),
            "Title": (meta.title[:60] if meta and meta.title else "—"),
            "Status": getattr(r, "status", "—"),
            "Confidence": f"{getattr(r, 'confidence', 0):.0%}",
            "SID": getattr(r, "sid", "—"),
            "Severity": (meta.severity if meta else "—"),
            "CVSS": (meta.cvss_score if meta else "—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def kpi_live_overview(result, system, history: list) -> None:
    """KPI card row for the dashboard (live RFC analysis)."""
    runs    = len(history)
    sid     = system.sid if system else "—"
    release = system.sap_release if system else "—"
    comps   = len(system.components) if system else 0
    impl    = len(system.implemented_notes) if system else 0

    status = result.status if result else "—"
    conf   = f"{result.confidence:.0%}" if result else "—"
    note   = result.note_number if result else "—"

    _STATUS_VAR = {
        "Applicable":           "critical",
        "Not Applicable":       "ok",
        "Already Implemented":  "info",
        "Needs Manual Review":  "medium",
        "Insufficient Data":    "",
    }
    var = _STATUS_VAR.get(status, "")

    cards = (
        _kpi("System SID",   sid,    release)
        + _kpi("Components", comps,  "from CVERS")
        + _kpi("Impl. Notes", impl,  "in CWBNTCUST", "ok" if impl else "")
        + _kpi("Last Note #",  note,  "checked")
        + _kpi("Decision",    status, f"confidence {conf}", var)
        + _kpi("Total Runs",  runs,   "in history")
    )
    st.markdown(f'<div class="kpi-grid">{cards}</div>', unsafe_allow_html=True)
