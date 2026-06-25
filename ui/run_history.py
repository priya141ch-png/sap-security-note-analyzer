"""
Run history — stored in Streamlit session_state only.
Nothing is written to disk; history is cleared when the browser tab closes.
This ensures each user's activity is completely private to their own session.
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)

_SESSION_KEY = "_run_history"


def _get_store() -> list:
    """Return the in-session run list, creating it if needed."""
    try:
        import streamlit as st
        if _SESSION_KEY not in st.session_state:
            st.session_state[_SESSION_KEY] = []
        return st.session_state[_SESSION_KEY]
    except Exception:
        return []


def save_run(
    system,
    notes: list,
    results: list,
    risk: list = None,
) -> str:
    ts = datetime.now()
    run_id = ts.strftime("%Y%m%d_%H%M%S")
    counts = {s: sum(1 for r in results if getattr(r, "status", "") == s) for s in [
        "Applicable", "Not Applicable", "Already Implemented",
        "Needs Manual Review", "Insufficient Data",
    ]}
    if hasattr(system, "systems"):          # Landscape (upload pipeline)
        sids = [s.sid for s in system.systems]
        sid_str = ",".join(sids[:5]) + ("…" if len(sids) > 5 else "")
        meta = {
            "run_id": run_id,
            "timestamp": ts.isoformat(timespec="seconds"),
            "mode": "upload",
            "sid": sid_str,
            "systems": len(sids),
            "notes_checked": [getattr(n, "note_number", str(n)) for n in notes],
            "counts": counts,
            "risk_scores": {getattr(r, "sid", ""): round(getattr(r, "risk_score", 0), 1)
                            for r in (risk or [])},
        }
    else:                                   # LiveSystemInfo (live RFC)
        meta = {
            "run_id": run_id,
            "timestamp": ts.isoformat(timespec="seconds"),
            "mode": "live",
            "sid": getattr(system, "sid", ""),
            "client": getattr(system, "client", ""),
            "host": getattr(system, "host", ""),
            "sap_release": getattr(system, "sap_release", ""),
            "notes_checked": [getattr(n, "note_number", str(n)) for n in notes],
            "counts": counts,
            "warnings": getattr(system, "collection_warnings", []),
        }
    store = _get_store()
    store.insert(0, meta)   # newest first
    return run_id


def list_runs() -> List[dict]:
    return list(_get_store())


def delete_run(run_id: str) -> None:
    store = _get_store()
    store[:] = [r for r in store if r.get("run_id") != run_id]
