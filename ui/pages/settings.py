"""Settings — note metadata cache management, app configuration."""
from __future__ import annotations
import streamlit as st
from storage.note_metadata import list_cached_notes, delete_note
from ui.components import section
import pandas as pd


def render() -> None:
    st.title("Settings")

    # ── My Data — workspace export / import ───────────────────────────────────
    _my_data_section()

    st.divider()

    # ── SAP Support Portal S-user ─────────────────────────────────────────────
    _suser_settings()

    st.divider()

    # ── Note Metadata Cache ───────────────────────────────────────────────────
    section("Note Metadata Cache")
    st.caption(
        "The local cache stores parsed SAP Note metadata (from uploaded files or manual entry). "
        "This enables applicability checks without re-uploading notes every time."
    )

    cached = list_cached_notes()
    if cached:
        rows = [{
            "Note #": n.note_number, "Title": n.title[:60],
            "Severity": n.severity, "CVSS": n.cvss_score,
            "Source": n.source, "Cached At": n.cached_at,
            "Matrix Rows": len(n.applicability_matrix),
            "Warnings": len(n.parser_warnings),
        } for n in cached]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        del_num = st.text_input("Note number to remove from cache")
        if st.button("🗑️ Remove from Cache", type="secondary"):
            if del_num:
                delete_note(del_num)
                st.success(f"Note {del_num} removed from cache.")
                st.rerun()

        if st.button("🗑️ Clear Entire Cache", type="secondary"):
            for n in cached:
                delete_note(n.note_number)
            st.success("Cache cleared.")
            st.rerun()
    else:
        st.info("Cache is empty. Upload note files or enter metadata manually in the Note Applicability Check page.")

    st.divider()

    # ── Live Access URLs (shown when running on GCP) ──────────────────────────
    _show_live_urls()

    st.divider()

    # ── Environment info ──────────────────────────────────────────────────────
    section("Environment")
    import os
    from rfc.connector import PYRFC_AVAILABLE, is_relay_connected
    _relay_ok = is_relay_connected()
    col1, col2 = st.columns(2)
    with col1:
        if PYRFC_AVAILABLE:
            st.metric("RFC Mode", "✅ Direct (pyrfc)")
        elif _relay_ok:
            st.metric("RFC Mode", "🔗 Relay (connected)")
        else:
            st.metric("RFC Mode", "🔌 Relay (waiting)")
        st.metric("AUTH_ENABLED", os.environ.get("AUTH_ENABLED", "false"))
        st.metric("APP_ENV", os.environ.get("APP_ENV", "development"))
    with col2:
        from pathlib import Path
        st.metric("Cached Notes", len(cached))
        from ui.run_history import list_runs
        st.metric("Run History (session)", len(list_runs()))
        st.metric("Log File Size", _file_size("logs/app.log"))

    st.divider()
    section("Authorization Requirements for RFC User")
    st.markdown("""
Create a dedicated **read-only RFC user** in SAP (transaction SU01) with these minimum authorizations:

| Authorization Object | Field | Value |
|---|---|---|
| `S_RFC` | RFC_TYPE | FUGR |
| `S_RFC` | RFC_NAME | RFC_PING, RFC_SYSTEM_INFO, RFC_READ_TABLE |
| `S_RFC` | ACTVT | 16 |
| `S_TABU_DIS` | DICBERCLS | SS (for CVERS, CWBNTCUST) |
| `S_TABU_DIS` | ACTVT | 03 |

Use transaction **PFCG** to create a role with these objects and assign to the RFC user.
    """)


def _my_data_section() -> None:
    """Workspace export, import, and identity section."""
    from storage.user_store import get_workspace_id, export_workspace, import_workspace
    from streamlit_local_storage import LocalStorage
    _ls = LocalStorage()

    section("🗂️ My Data — Workspace & Privacy")
    wid = get_workspace_id() or "—"

    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown(
            f"<div style='background:#f0f6ff;border-radius:8px;padding:14px 18px;"
            f"border-left:4px solid #0070F2;margin-bottom:8px'>"
            f"<b>Your Workspace ID:</b> <code style='font-size:16px;color:#002A45'>{wid}</code><br>"
            f"<span style='font-size:12px;color:#607080'>This ID is stored in <b>your browser only</b>. "
            f"All your RFC profiles and note cache are private to this workspace.</span></div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.info("💡 **New device?** Export your data below, then import it on the new browser to restore everything.")

    tab_export, tab_import, tab_reset = st.tabs([
        "⬇️  Export My Data",
        "⬆️  Restore / Import",
        "🗑️  Reset Workspace",
    ])

    with tab_export:
        st.markdown("""
**Export all your workspace data** — RFC profiles, note cache, and settings — as a single backup file.
Upload this file on any new device to restore your complete workspace instantly.
""")
        if st.button("📦  Generate Backup File", type="primary"):
            backup = export_workspace()
            st.download_button(
                label="⬇️  Download .sap-backup",
                data=backup,
                file_name=f"sap-workspace-{wid}.sap-backup",
                mime="application/json",
                use_container_width=True,
            )
        st.caption("⚠️ Keep this file safe — it contains encrypted SAP connection profile data.")

    with tab_import:
        st.markdown("""
**Restore from a previous backup** — upload your `.sap-backup` file to load your RFC profiles,
note cache, and settings from a previous device or browser.
""")
        uploaded = st.file_uploader(
            "Upload .sap-backup file",
            type=["sap-backup", "json"],
            key="ws_backup_upload",
        )
        if uploaded:
            try:
                restored_wid = import_workspace(uploaded.read())
                _ls.setItem("sap_workspace_id", restored_wid)
                from storage.user_store import set_workspace_id
                set_workspace_id(restored_wid)
                st.success(
                    f"✅ Workspace **{restored_wid}** restored successfully! "
                    "Your RFC profiles and note cache are now available."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Import failed: {exc}")

    with tab_reset:
        st.warning(
            "⚠️ **This will permanently delete your workspace** — all RFC profiles, "
            "note cache, and settings stored on this server will be removed. "
            "This cannot be undone. Export first if you want to keep your data."
        )
        confirm = st.text_input("Type your workspace ID to confirm deletion:", placeholder=wid)
        if st.button("🗑️  Delete My Workspace", type="secondary"):
            if confirm == wid:
                from storage.user_store import delete_workspace
                delete_workspace(wid)
                _ls.deleteItem("sap_workspace_id")
                _ls.deleteItem("sap_privacy_ack")
                st.success("Workspace deleted. Refreshing...")
                st.rerun()
            else:
                st.error("Workspace ID doesn't match. Nothing was deleted.")


def _suser_settings() -> None:
    from storage.credentials import load_suser, save_suser, delete_suser
    section("SAP Support Portal — S-User Credentials")
    st.caption(
        "Used for **automatic note fetching** — enter your S-user once and the app will "
        "download SAP Security Notes directly from support.sap.com without any manual download. "
        "Credentials are stored encrypted (AES-128 Fernet)."
    )
    s_user, s_pass = load_suser()
    if s_user:
        st.success(f"✅ S-user **{s_user}** is configured.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Remove S-user credentials", type="secondary"):
                delete_suser()
                st.success("S-user credentials removed.")
                st.rerun()
        with col2:
            update = st.checkbox("Update credentials")
        if update:
            _suser_form(s_user)
    else:
        st.info("No S-user configured yet. Enter credentials below to enable automatic note fetching.")
        _suser_form("")


def _suser_form(existing_user: str) -> None:
    from storage.credentials import save_suser
    with st.form("suser_form"):
        u = st.text_input("S-User ID", value=existing_user, placeholder="S0001234567")
        p = st.text_input("Password", type="password", placeholder="SAP Support Portal password")
        if st.form_submit_button("💾 Save S-User Credentials", type="primary"):
            if u and p:
                save_suser(u, p)
                st.success(f"S-user **{u}** saved (encrypted).")
                st.rerun()
            else:
                st.error("Both S-user ID and password are required.")


def _show_live_urls() -> None:
    """Read URLS.txt written by start_gcp.sh and display both public URLs."""
    from pathlib import Path
    urls_file = Path(__file__).resolve().parent.parent.parent / "URLS.txt"
    if not urls_file.exists():
        return
    section("Live Access URLs")
    content = urls_file.read_text()
    lines = {
        k.strip(): v.strip()
        for line in content.splitlines()
        if ":" in line
        for k, _, v in [line.partition(":")]
        if v.strip().startswith("http")
    }
    ui_url = lines.get("UI", lines.get("UI (share this with colleagues)", ""))
    relay_url = lines.get("Relay", lines.get("Relay URL (put this in relay/relay.bat)", ""))

    if ui_url:
        st.success(f"**App URL (share with colleagues):** {ui_url}")
        st.code(ui_url, language=None)
    if relay_url:
        st.info(f"**Relay URL (for relay.bat on VPN laptop):** {relay_url}")
        st.code(relay_url, language=None)
        st.caption("Copy this URL into `relay/relay.bat` on your office laptop, then run relay.bat while on VPN to enable RFC.")


def _file_size(path: str) -> str:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return "—"
    size = p.stat().st_size
    return f"{size/1024:.1f} KB" if size < 1_000_000 else f"{size/1_000_000:.1f} MB"
