"""Logs page — tail the application log file."""
from __future__ import annotations
from pathlib import Path
import streamlit as st
from ui.components import section

_LOG_FILE = Path("logs/app.log")


def render() -> None:
    st.title("Application Logs")

    if not _LOG_FILE.exists():
        st.info("No log file found yet. Logs are written to `logs/app.log`.")
        return

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        lines = st.number_input("Last N lines", min_value=20, max_value=2000, value=200, step=50)
    with col2:
        level_filter = st.selectbox("Filter level", ["ALL", "ERROR", "WARNING", "INFO"])
    with col3:
        keyword = st.text_input("Keyword search", placeholder="RFC, CVERS, error…")

    if st.button("🔄 Refresh"):
        st.rerun()

    all_lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()

    # Filter
    filtered = all_lines
    if level_filter != "ALL":
        filtered = [l for l in filtered if level_filter in l]
    if keyword:
        filtered = [l for l in filtered if keyword.lower() in l.lower()]

    tail = filtered[-int(lines):]

    section(f"Last {len(tail)} lines  (total: {len(all_lines)})")

    # Colour-code by level
    coloured = []
    for line in tail:
        if "ERROR" in line:
            coloured.append(f"🔴 {line}")
        elif "WARNING" in line:
            coloured.append(f"🟡 {line}")
        elif "INFO" in line:
            coloured.append(f"🔵 {line}")
        else:
            coloured.append(f"   {line}")

    st.code("\n".join(coloured), language="")
