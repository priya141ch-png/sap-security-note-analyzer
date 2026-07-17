"""
SAP Security Note Analyzer — Enterprise Dashboard
9-page sidebar navigation for live RFC-based analysis.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import streamlit as st

st.set_page_config(
    page_title="SAP Security Note Analyzer",
    page_icon="🔐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global styles ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Hide Streamlit's auto-generated file-based page nav at top of sidebar */
[data-testid="stSidebarNav"] { display: none !important; }

/* Sidebar background */
[data-testid="stSidebar"] { background: #002A45 !important; }
[data-testid="stSidebar"] * { color: #E8EDF2 !important; }

/* Nav radio items */
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
    padding: 9px 14px; border-radius: 8px; margin-bottom: 3px;
    cursor: pointer; transition: background .15s; font-size: 14px;
}
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,.10);
}

/* Section headers */
.section-header {
    font-size: 12px; font-weight: 700; letter-spacing: .09em;
    text-transform: uppercase; color: #0070F2;
    border-bottom: 2px solid #E8ECF2; margin: 20px 0 10px; padding-bottom: 5px;
}

/* KPI grid */
.kpi-grid { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
.kpi-card {
    flex: 1 1 140px; min-width: 120px; background: #fff;
    border: 1px solid #D9DDE3; border-radius: 10px;
    padding: 14px 18px; border-left: 4px solid #0070F2;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
}
.kpi-card.critical { border-left-color: #EF5350; }
.kpi-card.ok       { border-left-color: #66BB6A; }
.kpi-card.info     { border-left-color: #42A5F5; }
.kpi-card.medium   { border-left-color: #FFA726; }
.kpi-label { font-size: 11px; color: #607080; text-transform: uppercase; letter-spacing:.06em; }
.kpi-value { font-size: 22px; font-weight: 700; color: #002A45; line-height: 1.2; }
.kpi-sub   { font-size: 11px; color: #8090A0; margin-top: 2px; }

/* Status badges */
.badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; }
.badge-red    { background:#FFEBEE; color:#C62828; }
.badge-green  { background:#E8F5E9; color:#2E7D32; }
.badge-blue   { background:#E3F2FD; color:#1565C0; }
.badge-orange { background:#FFF3E0; color:#E65100; }
.badge-purple { background:#F3E5F5; color:#6A1B9A; }

[data-testid="stMetricValue"] { font-size: 18px !important; }

/* Privacy / copyright footer in sidebar */
.sidebar-footer {
    position: fixed; bottom: 0; left: 0; width: 240px;
    padding: 10px 16px 14px; background: #001e33;
    border-top: 1px solid rgba(255,255,255,.08);
    font-size: 10px; color: #7A8FA0 !important;
    line-height: 1.6;
}
</style>
""", unsafe_allow_html=True)


# ── Privacy notice (once per session) ─────────────────────────────────────────
if not st.session_state.get("_privacy_ack"):
    @st.dialog("🔒 Privacy & Data Notice")
    def _show_privacy():
        st.markdown("""
**Your data stays private.**

- 🔐 RFC passwords are **never stored** — used only for the current check
- 📋 Run history and results are kept **in your browser session only** and are cleared when you close the tab
- 🛡️ RFC connection profiles are stored **encrypted** on the server
- 🌐 All traffic between your browser and the server is **encrypted via HTTPS**
- ❌ No activity logs, no usage tracking, no data shared outside your organization's VPN

This tool performs **read-only** RFC calls — it never modifies your SAP system.
        """)
        if st.button("✅  I understand — Continue", type="primary", use_container_width=True):
            st.session_state["_privacy_ack"] = True
            st.rerun()
    _show_privacy()
    st.stop()


# ── Optional auth ─────────────────────────────────────────────────────────────
def _check_auth() -> bool:
    if os.environ.get("AUTH_ENABLED", "false").lower() != "true":
        return True
    if st.session_state.get("authenticated"):
        return True
    import bcrypt
    stored_hash = os.environ.get("APP_PASSWORD_HASH", "")
    st.markdown("## 🔐 SAP Security Note Analyzer")
    pw = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        try:
            if stored_hash and bcrypt.checkpw(pw.encode(), stored_hash.encode()):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid password.")
        except Exception:
            st.error("Auth configuration error.")
    return False


if not _check_auth():
    st.stop()


# ── Navigation ────────────────────────────────────────────────────────────────
PAGES = {
    "🏠  Dashboard":                "ui.pages.dashboard",
    "🔗  RFC Connection Profiles":  "ui.pages.rfc_profiles",
    "🛡️  Note Applicability Check": "ui.pages.note_check",
    "🖥️  Live System Inventory":    "ui.pages.inventory",
    "✅  Results & Evidence":       "ui.pages.results",
    "📊  Reports":                  "ui.pages.reports",
    "🕒  Run History":              "ui.pages.history",
    "📝  Logs":                     "ui.pages.logs_page",
    "⚙️  Settings":                 "ui.pages.settings",
}

with st.sidebar:
    st.markdown(
        "<div style='padding:18px 0 4px'>"
        "<span style='font-size:24px;font-weight:800;letter-spacing:.01em'>🔐 SAP Analyzer</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()
    page_label = st.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.markdown(
        "<div style='font-size:11px;color:#7A8FA0;line-height:1.7;padding:4px 0'>"
        "🔒 Read-only RFC analysis<br>"
        "No SAP changes are ever made<br><br>"
        "© 2024 <b style='color:#afc8d8'>Panchamukesh Chandaka</b><br>"
        "<span style='font-size:10px'>Designed &amp; Developed by<br>Panchamukesh Chandaka</span>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Lazy-load and render selected page ───────────────────────────────────────
import importlib
module = importlib.import_module(PAGES[page_label])
module.render()
