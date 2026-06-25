"""
SAP Security Note Analyzer — Enterprise Dashboard
Per-user workspace isolation. No blocking JS components in startup flow.
"""
from __future__ import annotations
import os
import sys
import uuid
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
[data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stSidebar"] { background: #002A45 !important; }
[data-testid="stSidebar"] * { color: #E8EDF2 !important; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
    padding: 9px 14px; border-radius: 8px; margin-bottom: 3px;
    cursor: pointer; transition: background .15s; font-size: 14px;
}
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,.10);
}
.section-header {
    font-size: 12px; font-weight: 700; letter-spacing: .09em;
    text-transform: uppercase; color: #0070F2;
    border-bottom: 2px solid #E8ECF2; margin: 20px 0 10px; padding-bottom: 5px;
}
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
.badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; }
.badge-red    { background:#FFEBEE; color:#C62828; }
.badge-green  { background:#E8F5E9; color:#2E7D32; }
.badge-blue   { background:#E3F2FD; color:#1565C0; }
.badge-orange { background:#FFF3E0; color:#E65100; }
.badge-purple { background:#F3E5F5; color:#6A1B9A; }
[data-testid="stMetricValue"] { font-size: 18px !important; }
</style>
""", unsafe_allow_html=True)


# ── Step 1: Privacy notice — once per browser tab (session_state) ─────────────
if not st.session_state.get("_privacy_ack"):
    st.markdown("""
<div style="max-width:580px;margin:50px auto 0;padding:36px 40px;
            background:#fff;border-radius:14px;
            box-shadow:0 4px 24px rgba(0,42,69,.14);
            border-top:5px solid #0070F2;">
  <div style="font-size:30px;margin-bottom:8px">🔒</div>
  <h2 style="color:#002A45;margin:0 0 14px;font-size:21px">Privacy &amp; Data Notice</h2>
  <p style="color:#444;line-height:1.7;font-size:14px;margin-bottom:12px">
    This tool keeps your SAP data <b>private to your own workspace only</b>.
  </p>
  <ul style="color:#333;font-size:14px;line-height:2.1;padding-left:20px;margin-bottom:16px">
    <li>🔐 <b>RFC passwords</b> — never stored anywhere</li>
    <li>📋 <b>Run history &amp; results</b> — stay in this browser tab only, cleared on close</li>
    <li>🗂️ <b>RFC profiles &amp; note cache</b> — stored in your <b>private workspace</b>, isolated from all other users</li>
    <li>🌐 All traffic is <b>HTTPS encrypted</b></li>
    <li>❌ No activity logs, no usage tracking, no data shared outside your organisation</li>
  </ul>
  <p style="color:#555;font-size:13px;background:#f0f4ff;padding:10px 14px;border-radius:6px">
    🛡️ This tool performs <b>read-only</b> RFC calls — it <b>never modifies</b> your SAP system.
  </p>
</div>
""", unsafe_allow_html=True)
    st.write("")
    c1, c2, c3 = st.columns([2, 3, 2])
    with c2:
        if st.button("✅  I Understand — Continue", type="primary", use_container_width=True):
            st.session_state["_privacy_ack"] = True
            st.rerun()
    st.stop()


# ── Step 2: Workspace — auto-generated or restored via ID ─────────────────────
from storage.user_store import set_workspace_id, get_workspace_id, new_workspace_id

if not get_workspace_id():
    # Check if user wants to restore a previous workspace
    st.markdown("""
<div style="max-width:520px;margin:40px auto 0;padding:30px 36px;
            background:#fff;border-radius:14px;
            box-shadow:0 4px 24px rgba(0,42,69,.12);
            border-top:5px solid #66BB6A;">
  <div style="font-size:26px;margin-bottom:8px">🗂️</div>
  <h2 style="color:#002A45;margin:0 0 10px;font-size:19px">Set Up Your Workspace</h2>
  <p style="color:#555;font-size:13px;line-height:1.7">
    Each user gets a private workspace. Your RFC profiles, note cache, and settings
    are stored here — invisible to other users.<br><br>
    If you have used this tool before and have your <b>Workspace ID</b>, enter it below
    to restore all your previous data. Otherwise, click <b>Create New Workspace</b>.
  </p>
</div>
""", unsafe_allow_html=True)

    st.write("")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        restore_id = st.text_input(
            "Restore previous workspace",
            placeholder="Enter your Workspace ID (e.g. A3F7B2C1)",
            key="_ws_restore_input",
        ).strip().upper()

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🔄  Restore Workspace", use_container_width=True,
                         disabled=not restore_id):
                wdir = Path("user_data/workspaces") / restore_id
                if wdir.exists():
                    set_workspace_id(restore_id)
                    st.success(f"✅ Workspace **{restore_id}** restored!")
                    st.rerun()
                else:
                    st.error(f"Workspace ID **{restore_id}** not found on this server.")
        with col_b:
            if st.button("✨  Create New Workspace", type="primary", use_container_width=True):
                wid = new_workspace_id()
                set_workspace_id(wid)
                st.session_state["_ws_is_new"] = True
                st.rerun()
    st.stop()

# New workspace welcome banner (shown once)
if st.session_state.pop("_ws_is_new", False):
    wid = get_workspace_id()
    st.success(
        f"👋 **Welcome!** Your private workspace **`{wid}`** has been created.\n\n"
        f"📌 **Save this ID:** `{wid}` — enter it on any new device to restore your data.\n\n"
        "Go to **⚙️ Settings → My Data** to export a full backup or restore from a file."
    )


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

wid = get_workspace_id() or "—"

with st.sidebar:
    st.markdown(
        "<div style='padding:16px 0 4px'>"
        "<span style='font-size:22px;font-weight:800;letter-spacing:.01em'>🔐 SAP Analyzer</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-size:11px;color:#5A8FAA;margin-bottom:6px'>"
        f"🗂️ Workspace: <code style='color:#7EC8E3'>{wid}</code></div>",
        unsafe_allow_html=True,
    )
    st.divider()
    page_label = st.radio("Navigation", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    st.markdown(
        "<div style='font-size:11px;color:#7A8FA0;line-height:1.7;padding:4px 0'>"
        "🔒 Read-only RFC analysis<br>"
        "No SAP changes are ever made<br><br>"
        "© 2025 <b style='color:#afc8d8'>Panchamukesh Chandaka</b><br>"
        "<span style='font-size:10px'>Designed &amp; Developed by<br>Panchamukesh Chandaka</span>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Render selected page ──────────────────────────────────────────────────────
import importlib
module = importlib.import_module(PAGES[page_label])
module.render()
