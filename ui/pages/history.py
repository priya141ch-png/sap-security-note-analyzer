"""Run History — browse and delete past analysis runs."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from ui.run_history import list_runs, delete_run
from ui.components import section


def render() -> None:
    st.title("Run History")
    runs = list_runs()

    if not runs:
        st.info("No analysis runs yet.")
        return

    st.caption(f"🔒 {len(runs)} run(s) in this session — history clears when you close the tab (nothing stored on server)")
    section("All Runs")

    rows = []
    for r in runs:
        c = r.get("counts", {})
        rows.append({
            "Run ID": r["run_id"], "Timestamp": r["timestamp"],
            "SID": r.get("sid", "—"), "Client": r.get("client", "—"),
            "Release": r.get("sap_release", "—"),
            "Notes": len(r.get("notes_checked", [])),
            "Applicable": c.get("Applicable", 0),
            "Not Applicable": c.get("Not Applicable", 0),
            "Already Impl.": c.get("Already Implemented", 0),
            "Manual Review": c.get("Needs Manual Review", 0),
            "Insufficient": c.get("Insufficient Data", 0),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    section("Run Detail")
    picked_id = st.selectbox("Select run", [r["run_id"] for r in runs])
    picked = next(r for r in runs if r["run_id"] == picked_id)

    with st.expander("Notes checked"):
        st.write(", ".join(picked.get("notes_checked", [])) or "—")
    if picked.get("warnings"):
        with st.expander(f"Warnings ({len(picked['warnings'])})"):
            for w in picked["warnings"]:
                st.warning(w)

    with st.expander("⚠️  Delete this run"):
        if st.button(f"Delete {picked_id}", type="secondary"):
            delete_run(picked_id)
            st.success("Deleted.")
            st.rerun()
