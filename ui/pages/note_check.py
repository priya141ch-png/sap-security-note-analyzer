"""
Note Applicability Check — multi-client, multi-system analysis.

Flow:
  1. Enter SAP Note number(s)
  2. Select target systems — by client group, individually, or all
  3. Enter RFC password (shared or per-profile)
  4. Click Run → checks all selected systems sequentially
  5. Aggregated results table + per-system evidence + download reports
"""
from __future__ import annotations
import json
import logging
import pathlib
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime

import streamlit as st

from adapters.note_parser import parse_note
from adapters.pdf_note_parser import parse_note_pdf
from core.domain_models import LiveSystemInfo, NoteMetadata, SystemComponent
from core.live_engine import evaluate_live
from rfc.connector import (
    PYRFC_AVAILABLE,
    build_connection, test_connection, is_relay_connected, relay_call,
)
from rfc.notes_checker import fetch_implemented_notes
from rfc.system_collector import collect_system_info
from storage.credentials import list_profiles, load_suser, save_suser, delete_suser
from storage.note_metadata import (
    build_manual_metadata, build_rfc_metadata, get_note, note_from_sap_note, save_note,
)
from storage.report_generator import export_excel, export_json, export_pdf
from ui.components import section
from ui.run_history import save_run

logger = logging.getLogger(__name__)

_STATUS_ICON = {
    "Applicable":           "🔴",
    "Not Applicable":       "🟢",
    "Already Implemented":  "🔵",
    "Needs Manual Review":  "🟡",
    "Insufficient Data":    "⚪",
}
_STATUS_COLOR = {
    "Applicable":           "#FFEBEE",
    "Not Applicable":       "#E8F5E9",
    "Already Implemented":  "#E3F2FD",
    "Needs Manual Review":  "#FFF8E1",
    "Insufficient Data":    "#F5F5F5",
}


def render() -> None:
    st.title("🛡️ Note Applicability Check")
    st.caption("Check one SAP Security Note against one or multiple SAP systems across all your clients.")

    if not PYRFC_AVAILABLE:
        if is_relay_connected():
            st.success("🔗 **Relay connected** — live RFC checks will run through your VPN laptop.")
        else:
            st.info(
                "🔌 **RFC via Relay** — connect to VPN and run **`relay\\relay.bat`** on your laptop to enable live checks."
            )

    profiles = list_profiles()
    if not profiles:
        st.warning("⚠️ No RFC profiles saved yet. Go to **🔗 RFC Connection Profiles** to add your SAP systems.")
        return

    # ── Step 1: Note number ───────────────────────────────────────────────────
    section("Step 1 — SAP Security Note")
    note_number = st.text_input(
        "SAP Note Number *",
        placeholder="e.g. 3194159",
        key="nc_note_number",
    ).strip()

    cached_note = get_note(note_number) if note_number else None

    if note_number:
        if cached_note:
            col_m, col_pdf, col_c = st.columns([7, 2, 1])
            with col_m:
                st.success(
                    f"✅ Metadata loaded — **{cached_note.title or note_number}** "
                    f"| Severity: {cached_note.severity or '—'} "
                    f"| CVSS: {cached_note.cvss_score or '—'} "
                    f"| Matrix rows: {len(cached_note.applicability_matrix)}"
                )
                with st.expander("View full metadata"):
                    _show_note_meta(cached_note)
            with col_pdf:
                pdf_bytes = _get_note_pdf(note_number)
                if pdf_bytes:
                    st.download_button(
                        "📄 View PDF",
                        data=pdf_bytes,
                        file_name=f"SAP_Note_{note_number}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        help="Download the note PDF to open in your PDF viewer",
                    )
            with col_c:
                if st.button("🔄", help="Clear cache and re-download"):
                    from storage.note_metadata import delete_note
                    delete_note(note_number)
                    st.rerun()
        else:
            _fetch_note_section(note_number)
            cached_note = get_note(note_number)

    # ── Step 2: System selection ──────────────────────────────────────────────
    section("Step 2 — Select Target Systems")

    # Group profiles by client
    groups: dict[str, list] = defaultdict(list)
    for p in profiles:
        groups[p.client_group or "Ungrouped"].append(p)

    selected_profiles: list = []

    st.caption("Select the SAP systems you want to check. You can select all systems in a client, or pick individually.")

    # Quick-select buttons
    qc1, qc2, qc3 = st.columns([2, 2, 4])
    with qc1:
        if st.button("☑️ Select All Systems"):
            for p in profiles:
                st.session_state[f"sel_{p.name}"] = True
    with qc2:
        if st.button("☐ Deselect All"):
            for p in profiles:
                st.session_state[f"sel_{p.name}"] = False

    st.write("")

    for group_name in sorted(groups.keys()):
        grp = groups[group_name]

        # Client header with "select all in client" button
        hc1, hc2 = st.columns([5, 2])
        with hc1:
            st.markdown(
                f"<div style='background:#002A45;color:#fff;padding:7px 14px;"
                f"border-radius:6px;font-size:14px;font-weight:600'>"
                f"🏢 {group_name} &nbsp;<span style='opacity:.65;font-weight:400'>"
                f"({len(grp)} system{'s' if len(grp)>1 else ''})</span></div>",
                unsafe_allow_html=True,
            )
        with hc2:
            if st.button(f"Select all in {group_name}", key=f"selall_{group_name}"):
                for p in grp:
                    st.session_state[f"sel_{p.name}"] = True

        # System checkboxes in a row
        cols = st.columns(min(len(grp), 4))
        for i, p in enumerate(grp):
            with cols[i % 4]:
                env_label = f" [{p.environment}]" if p.environment else ""
                test_icon = "✅" if p.last_test_ok else "❌" if p.last_tested else "⬜"
                checked = st.checkbox(
                    f"{test_icon} **{p.name}**{env_label}  \n`{p.host}`",
                    key=f"sel_{p.name}",
                    value=st.session_state.get(f"sel_{p.name}", False),
                )
                if checked:
                    selected_profiles.append(p)
        st.write("")

    if selected_profiles:
        st.info(
            f"**{len(selected_profiles)} system(s) selected:** "
            + ", ".join(
                f"{p.client_group + ' / ' if p.client_group else ''}{p.name}"
                for p in selected_profiles
            )
        )
    else:
        st.warning("Select at least one system above to run the check.")

    # ── Step 3: Password + Run ────────────────────────────────────────────────
    section("Step 3 — RFC Password & Run")

    st.caption(
        "Enter the RFC password. If all your selected systems share the same RFC user password, "
        "one field is enough. The password is never stored."
    )

    rfc_password = st.text_input(
        "RFC Password *",
        type="password",
        key="nc_rfc_password",
        help="Used only for this check — never stored",
    )

    rfc_ready   = PYRFC_AVAILABLE or is_relay_connected()
    can_run     = bool(note_number and selected_profiles and rfc_password and rfc_ready)

    if not rfc_ready:
        st.button("▶  Run Check", disabled=True, use_container_width=True)
        st.caption("🔌 Waiting for relay — connect to VPN and start relay.bat.")
    elif not note_number:
        st.button("▶  Run Check", disabled=True, use_container_width=True,
                  help="Enter a SAP Note number first.")
    elif not selected_profiles:
        st.button("▶  Run Check", disabled=True, use_container_width=True,
                  help="Select at least one system.")
    elif not rfc_password:
        st.button("▶  Run Check", disabled=True, use_container_width=True,
                  help="Enter the RFC password.")
    else:
        if st.button(
            f"▶  Run Check on {len(selected_profiles)} System{'s' if len(selected_profiles)>1 else ''}",
            type="primary", use_container_width=True,
        ):
            _run_multi_check(
                note_number=note_number,
                profiles=selected_profiles,
                plain_password=rfc_password,
                note_meta=cached_note,
            )


# ── Multi-system check ────────────────────────────────────────────────────────

def _run_multi_check(note_number: str, profiles: list, plain_password: str,
                     note_meta) -> None:
    """Run the note check against each selected profile sequentially."""

    if not note_meta:
        note_meta = NoteMetadata(note_number=note_number)

    total   = len(profiles)
    results = []   # list of (profile, system, result) or (profile, None, error_str)

    overall_prog  = st.progress(0.0, text=f"Checking 0 / {total} systems…")
    status_area   = st.empty()

    for idx, profile in enumerate(profiles):
        label = (f"{profile.client_group} / {profile.name}"
                 if profile.client_group else profile.name)
        status_area.info(f"⏳ [{idx+1}/{total}] Connecting to **{label}** ({profile.host})…")

        try:
            system, error = _collect_system(profile, plain_password, status_area, label)
            if error:
                results.append((profile, None, error))
            else:
                result = evaluate_live(system, note_meta)
                results.append((profile, system, result))
                save_run(system, [note_meta], [result])
        except Exception as exc:
            logger.exception("Error on %s", profile.name)
            results.append((profile, None, str(exc)))

        overall_prog.progress(
            (idx + 1) / total,
            text=f"Checking {idx+1} / {total} systems…",
        )

    overall_prog.empty()
    status_area.empty()

    # Store in session for Results & Evidence page
    st.session_state["multi_results"]   = results
    st.session_state["multi_note_meta"] = note_meta
    st.session_state["last_notes"]      = [note_meta]

    _show_multi_results(results, note_meta, note_number, plain_password)


def _collect_system(profile, plain_password: str, status_area, label: str):
    """Connect to one system and return (LiveSystemInfo, None) or (None, error_str)."""
    profile_dict = {
        "host": profile.host, "sysnr": profile.sysnr, "client": profile.client,
        "user": profile.user, "lang": profile.lang, "timeout": profile.timeout,
    }

    # Test connection
    ok, msg = test_connection(profile_dict, plain_password)
    if not ok:
        return None, f"Connection failed: {msg}"

    if PYRFC_AVAILABLE:
        conn = build_connection(profile_dict, plain_password)
        conn.connect()
        system = collect_system_info(conn)
        impl_notes, impl_warn = fetch_implemented_notes(conn)
        system.implemented_notes = impl_notes
        if impl_warn:
            system.collection_warnings.append(impl_warn)
        conn.close()
    else:
        r1 = relay_call("system_info", profile_dict, plain_password)
        if not r1.get("ok"):
            return None, r1.get("error", "system_info relay call failed")
        d = r1["data"]
        system = LiveSystemInfo(
            sid=d.get("sid", ""),
            client=d.get("client", ""),
            host=d.get("host", ""),
            sap_release=d.get("sap_release", ""),
            kernel_release=d.get("kernel_release", ""),
            kernel_patch=d.get("kernel_patch", ""),
            db_system=d.get("db_system", ""),
            collected_at=d.get("collected_at", ""),
            collection_warnings=list(d.get("collection_warnings", [])),
            components=[
                SystemComponent(
                    name=c["name"], release=c.get("release", ""),
                    sp_level=c.get("sp_level", ""),
                    patch_level=c.get("patch_level", ""),
                    description=c.get("description", ""),
                )
                for c in d.get("components", [])
            ],
        )
        r2 = relay_call("implemented_notes", profile_dict, plain_password)
        impl_notes = r2.get("data", []) if r2.get("ok") else []
        if not r2.get("ok"):
            system.collection_warnings.append(
                f"Could not read implemented notes: {r2.get('error','')}"
            )
        system.implemented_notes = impl_notes

    # Attach profile metadata to system for display
    system._profile_name       = profile.name
    system._client_group       = profile.client_group or "Ungrouped"
    system._environment        = profile.environment or "—"
    return system, None


# ── Results display ───────────────────────────────────────────────────────────

def _show_multi_results(results: list, note_meta, note_number: str,
                        plain_password: str) -> None:
    """Show aggregated results table + per-system evidence."""
    import pandas as pd

    section("Results — All Systems")

    ok_rows   = [(p, sys, r) for p, sys, r in results if sys is not None]
    err_rows  = [(p, err)    for p, sys, err in results if sys is None]

    # ── Summary KPI strip ─────────────────────────────────────────────────────
    counts = defaultdict(int)
    for _, _, r in ok_rows:
        counts[r.status] += 1

    kpi_cols = st.columns(5)
    for i, (status, icon) in enumerate(_STATUS_ICON.items()):
        kpi_cols[i].metric(f"{icon} {status}", counts.get(status, 0))

    st.write("")

    # ── Aggregated table ──────────────────────────────────────────────────────
    rows = []
    for profile, system, result in ok_rows:
        rows.append({
            "Client":       getattr(system, "_client_group", "—"),
            "System":       profile.name,
            "SID":          system.sid,
            "Environment":  getattr(system, "_environment", "—"),
            "SAP Release":  system.sap_release,
            "Status":       f"{_STATUS_ICON.get(result.status,'')} {result.status}",
            "Confidence":   f"{result.confidence:.0%}",
            "Component":    result.evidence.component.required_component,
            "Installed SP": result.evidence.sp.installed_sp or "—",
            "In CWBNTCUST": "✅" if result.evidence.implementation.note_in_cwbntcust else "❌",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Failed connections
    if err_rows:
        with st.expander(f"⚠️ {len(err_rows)} system(s) failed to connect"):
            for profile, err in err_rows:
                st.error(f"**{profile.name}** ({profile.host}): {err}")

    # ── Per-system expandable evidence ───────────────────────────────────────
    if ok_rows:
        section("Per-System Evidence")
        for profile, system, result in ok_rows:
            icon  = _STATUS_ICON.get(result.status, "⬜")
            color = _STATUS_COLOR.get(result.status, "#fff")
            label = (f"{getattr(system,'_client_group','')!s} / {profile.name}"
                     if getattr(system, "_client_group", "") else profile.name)

            with st.expander(f"{icon}  {label}  —  {system.sid}  [{result.status}]"):
                st.markdown(
                    f"<div style='background:{color};padding:10px 14px;"
                    f"border-radius:6px;margin-bottom:10px'>"
                    f"<b>{icon} {result.status}</b> &nbsp;·&nbsp; {result.evidence.reason}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("SID",          system.sid)
                c2.metric("SAP Release",  system.sap_release)
                c3.metric("Components",   len(system.components))
                c4.metric("Confidence",   f"{result.confidence:.0%}")

                ev = result.evidence
                c5, c6, c7, c8 = st.columns(4)
                c5.metric("Component",      ev.component.required_component)
                c6.metric("Installed SP",   ev.sp.installed_sp or "—")
                c7.metric("Required SP",
                          f"{ev.sp.required_sp_from}–{ev.sp.required_sp_to}"
                          if ev.sp.required_sp_from else "—")
                c8.metric("In CWBNTCUST",
                          "✅ Yes" if ev.implementation.note_in_cwbntcust else "❌ No")

                if system.collection_warnings:
                    for w in system.collection_warnings:
                        st.warning(w)

                st.info(f"**Recommended action:** {result.recommended_action}")

                # Version checks (kernel / DB / OS)
                ver_checks = getattr(result.evidence, "version_checks", [])
                if ver_checks:
                    st.markdown("**Version Checks:**")
                    for vc in ver_checks:
                        icon = {"ok": "✅", "affected": "⚠️", "unknown": "❓"}.get(vc.status, "—")
                        st.markdown(
                            f"{icon} **{vc.dimension.upper()}**: "
                            f"Required `{vc.required}` | Installed `{vc.installed}`"
                            + (f"  _({vc.note})_" if vc.note else "")
                        )

                # Inline note summary (no nested expander — already inside one)
                note_symp = getattr(result, "note_symptoms", "")
                note_sol  = getattr(result, "note_solution", "")
                if note_symp or note_sol:
                    st.markdown("---")
                    if note_symp:
                        st.markdown("**About this note:** " + note_symp[:400])
                    if note_sol:
                        st.markdown("**Solution:** " + note_sol[:400])

    # ── Download reports ──────────────────────────────────────────────────────
    if ok_rows:
        st.divider()
        section("Download Reports")
        all_results = [r for _, _, r in ok_rows]
        # Use first system for header (multi-system report)
        first_sys = ok_rows[0][1]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        dc1, dc2, dc3 = st.columns(3)
        with dc1:
            st.download_button(
                "⬇️ Excel Report (all systems)",
                data=export_excel(all_results, first_sys, [note_meta]),
                file_name=f"sap_note_{note_number}_multi_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with dc2:
            st.download_button(
                "⬇️ PDF Report",
                data=export_pdf(all_results, first_sys),
                file_name=f"sap_note_{note_number}_multi_{ts}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        with dc3:
            st.download_button(
                "⬇️ JSON",
                data=export_json(all_results, first_sys, [note_meta]),
                file_name=f"sap_note_{note_number}_multi_{ts}.json",
                mime="application/json",
                use_container_width=True,
            )


# ── Note metadata helpers ─────────────────────────────────────────────────────

def _show_note_meta(note, inside_expander: bool = False) -> None:
    """Show note header metrics + what the note is about + solution.

    When called inside a st.expander (inside_expander=True), nested expanders
    are replaced with plain sections — Streamlit forbids nesting expanders.
    """
    cols = st.columns(4)
    cols[0].metric("Note #",   note.note_number)
    cols[1].metric("Severity", note.severity or "—")
    cols[2].metric("CVSS",     note.cvss_score or "—")
    cols[3].metric("Affected Releases", len([e for e in note.applicability_matrix if e.entry_type == "validity"]))
    if note.title:
        st.markdown(f"**{note.title}**")

    # ── What the note is about ────────────────────────────────────────────────
    if note.symptoms:
        st.markdown("**What is this note about?**")
        st.markdown(note.symptoms)

    # ── Proposed solution ─────────────────────────────────────────────────────
    if note.solution:
        st.markdown("---")
        st.markdown("**Proposed Solution**")
        st.markdown(note.solution)
        if getattr(note, "workaround", ""):
            st.markdown("**Workaround / Other Terms:**")
            st.markdown(note.workaround)

    # ── Version requirements (if any extracted) ───────────────────────────────
    ver_info = []
    if getattr(note, "kernel_min", ""):
        ver_info.append(f"Kernel >= {note.kernel_min}")
    if getattr(note, "db_type", ""):
        ver_info.append(f"DB: {note.db_type} >= {note.db_version_min or '?'}")
    if getattr(note, "os_type", ""):
        ver_info.append(f"OS: {note.os_type} >= {note.os_version_min or '?'}")
    if ver_info:
        st.info("Version requirements detected: " + " | ".join(ver_info))

    # ── Affected release matrix ───────────────────────────────────────────────
    validity = [e for e in note.applicability_matrix if e.entry_type == "validity"]
    if validity:
        import pandas as pd
        rows = [{"Component": e.component, "Release From": e.release, "Release To": e.release_to}
                for e in validity]
        st.markdown("**Affected Software Component Versions:**")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _fetch_note_section(note_number: str) -> None:
    """
    Note fetch UI — auto-downloads PDF from SAP portal using saved S-user credentials.
    Falls back to file upload if login fails (e.g. 2FA required).
    """
    portal_url = f"https://me.sap.com/notes/{note_number}"
    s_user, s_pass = load_suser()

    # --- Poll background download ---
    _poll_dl(note_number)

    col_dl, col_view = st.columns([2, 1])

    with col_dl:
        if st.button(
            f"⬇️  Download Note {note_number}",
            type="primary", use_container_width=True,
            help="Downloads note PDF from SAP portal using your saved S-user credentials",
            key=f"dl_{note_number}",
        ):
            if not s_user or not s_pass:
                st.session_state["_show_suser_form"] = True
                st.warning("⚠️ Enter your SAP S-user credentials below first.")
            else:
                _start_dl(note_number, s_user, s_pass)
                st.rerun()

    with col_view:
        existing_pdf = _get_note_pdf(note_number)
        if existing_pdf:
            st.download_button(
                "📄 View Note PDF",
                data=existing_pdf,
                file_name=f"SAP_Note_{note_number}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="Open the downloaded note PDF",
            )
        else:
            st.link_button(
                f"🔗 View Note {note_number}",
                portal_url,
                use_container_width=True,
                help="Opens this note on SAP Support Portal in a new browser tab",
            )

    # ── S-user credentials ────────────────────────────────────────────────────
    show_form = st.session_state.get("_show_suser_form", not bool(s_user))
    if s_user and not show_form:
        with st.expander(f"🔑 SAP S-user: `{s_user}` — click to change"):
            _suser_credentials_form()
    else:
        st.info("🔑 Enter your SAP S-user credentials — saved encrypted, used only to download notes.")
        _suser_credentials_form()

    # ── Upload fallback (shown if download failed) ────────────────────────────
    if st.session_state.get("_show_upload"):
        with st.expander("📄 Upload note file (PDF or HTML)", expanded=True):
            st.caption(
                f"Open [SAP portal]({portal_url}) → log in → download the PDF → upload here."
            )
            _note_upload_form(note_number)

    # ── Manual entry fallback ─────────────────────────────────────────────────
    with st.expander("✏️ Enter note metadata manually"):
        _manual_metadata_form(note_number)


def _rfc_fetch_note(note_number: str) -> None:
    """Fetch note metadata from the connected SAP system via RFC."""
    from rfc.note_fetcher import fetch_note_from_system
    import dataclasses

    profiles = list_profiles()
    if not profiles:
        st.error("No RFC profiles configured.")
        return

    # Pick a profile — prefer one that was last successfully tested
    profile = next((p for p in profiles if p.last_test_ok), profiles[0])

    # Need RFC password for the connection
    rfc_pw = st.session_state.get("nc_rfc_password", "")
    if not rfc_pw:
        st.warning(
            "⚠️ Enter the RFC password in **Step 3** below, then click Download again. "
            "The RFC connection needs it to read note data from the SAP system."
        )
        return

    with st.spinner(f"Fetching Note {note_number} from {profile.host} via RFC…"):
        try:
            if PYRFC_AVAILABLE:
                conn = build_connection(profile, rfc_pw)
                conn.connect()
                note_dict, error = fetch_note_from_system(conn, note_number)
                conn.close()
            else:
                pd = dataclasses.asdict(profile) if dataclasses.is_dataclass(profile) else vars(profile)
                result = relay_call("fetch_note", pd, rfc_pw, note_number=note_number)
                if not result.get("ok"):
                    error = result.get("error", "Relay fetch failed")
                    note_dict = None
                else:
                    note_dict = result.get("data")
                    error = ""
        except Exception as exc:
            note_dict = None
            error = str(exc)

    if error or not note_dict:
        st.warning(
            f"⚠️ Could not fetch Note {note_number} from the SAP system: "
            f"{error or 'No data returned'}\n\n"
            "The note may not have been downloaded to this system via transaction SNOTE yet. "
            "Use the **Upload note file** option below to import from SAP portal."
        )
        st.session_state["_show_upload"] = True
        return

    meta = build_rfc_metadata(note_dict)
    save_note(meta)
    st.success(
        f"✅ Note **{note_number}** fetched from SAP system — "
        f"**{meta.title or '(no title)'}** | "
        f"{len(meta.applicability_matrix)} applicability entr{'ies' if len(meta.applicability_matrix) != 1 else 'y'}"
    )
    st.rerun()


def _suser_credentials_form() -> None:
    s_user, _ = load_suser()
    with st.form("suser_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            new_user = st.text_input("S-user ID", value=s_user, placeholder="S0001234567")
        with c2:
            new_pass = st.text_input("S-user Password", type="password",
                                     placeholder="Enter password")
        cols = st.columns([2, 1])
        with cols[0]:
            if st.form_submit_button("💾 Save Credentials", use_container_width=True,
                                     type="primary"):
                if new_user and new_pass:
                    save_suser(new_user, new_pass)
                    st.session_state["_show_suser_form"] = False
                    st.success("✅ S-user credentials saved (encrypted in your workspace).")
                    st.rerun()
                else:
                    st.error("Both S-user ID and password are required.")
        with cols[1]:
            if s_user and st.form_submit_button("🗑️ Remove", use_container_width=True):
                delete_suser()
                st.rerun()


_DL_DIR = pathlib.Path(tempfile.gettempdir()) / "sap_dl"
_DL_DIR.mkdir(exist_ok=True)


def _dl_result_file(note_number: str) -> pathlib.Path:
    return _DL_DIR / f"{note_number}.json"


def _start_dl(note_number: str, s_user: str, s_pass: str) -> None:
    """Kick off background download thread and set running flag in session state."""
    rf = _dl_result_file(note_number)
    rf.unlink(missing_ok=True)
    st.session_state[f"_dl_{note_number}"] = "running"

    def worker():
        try:
            from adapters.sap_me_fetcher import fetch_note_json_me
            note_dict, err = fetch_note_json_me(note_number, s_user, s_pass)
            if err:
                rf.write_text(json.dumps({"error": err}))
            else:
                rf.write_text(json.dumps({"ok": True, "note_dict": note_dict}))
        except Exception as exc:
            import traceback
            rf.write_text(json.dumps({"error": traceback.format_exc()}))

    threading.Thread(target=worker, daemon=True).start()


def _poll_dl(note_number: str) -> None:
    """On each rerun, check if the background download finished."""
    status = st.session_state.get(f"_dl_{note_number}")
    if not status:
        return

    rf = _dl_result_file(note_number)
    if status == "running":
        if rf.exists():
            result = json.loads(rf.read_text())
            rf.unlink(missing_ok=True)
            if result.get("error"):
                err_msg = result.get("error", "")[:300]
                st.error("Download failed: " + err_msg)
                st.session_state[f"_dl_{note_number}"] = "error"
                st.session_state["_show_upload"] = True
            else:
                try:
                    from adapters.me_note_parser import parse_note_json_me
                    note_dict = result["note_dict"]
                    sap_note  = parse_note_json_me(note_dict)
                    if not sap_note:
                        st.error("Fetched note data but could not parse it.")
                        st.session_state[f"_dl_{note_number}"] = "error"
                        return
                    meta = note_from_sap_note(sap_note, source="auto-downloaded (me.sap.com)")
                    save_note(meta)
                    _save_note_json(note_number, note_dict)
                    st.session_state[f"_dl_{note_number}"] = "done"
                    st.session_state[f"_dl_title_{note_number}"] = sap_note.title or ""
                    if sap_note.parser_warnings:
                        st.session_state[f"_dl_warn_{note_number}"] = " | ".join(sap_note.parser_warnings)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Parse error: {exc}")
                    st.session_state[f"_dl_{note_number}"] = "error"
        else:
            st.info(f"Fetching Note {note_number} from me.sap.com (logging in... ~60s)")
            time.sleep(3)
            st.rerun()
        return

    if status == "done":
        title = st.session_state.get(f"_dl_title_{note_number}", "")
        st.success(f"Note {note_number} downloaded: {title}")
        warn = st.session_state.get(f"_dl_warn_{note_number}", "")
        if warn:
            st.warning(f"Parser warnings: {warn}")
        del st.session_state[f"_dl_{note_number}"]


def _save_note_pdf(note_number: str, pdf_bytes: bytes) -> None:
    """Save raw PDF to workspace for later viewing."""
    try:
        from storage.user_store import workspace_dir
        pdf_dir = workspace_dir("note_pdfs")
        (pdf_dir / f"{note_number}.pdf").write_bytes(pdf_bytes)
    except Exception as exc:
        logger.warning("Could not save PDF to workspace: %s", exc)


def _get_note_pdf(note_number: str) -> bytes | None:
    """Read saved PDF from workspace."""
    try:
        from storage.user_store import workspace_dir
        pdf_path = workspace_dir("note_pdfs") / f"{note_number}.pdf"
        if pdf_path.exists():
            return pdf_path.read_bytes()
    except Exception:
        pass
    return None


def _save_note_json(note_number: str, note_dict: dict) -> None:
    """Save note JSON dict from me.sap.com API to workspace for View Note."""
    try:
        import json
        from storage.user_store import workspace_dir
        json_dir = workspace_dir("note_pdfs")
        (json_dir / f"{note_number}.json").write_text(
            json.dumps(note_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Could not save note JSON to workspace: %s", exc)


def _get_note_json(note_number: str) -> dict | None:
    """Read saved note JSON dict from workspace."""
    try:
        import json
        from storage.user_store import workspace_dir
        p = workspace_dir("note_pdfs") / f"{note_number}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _note_upload_form(note_number: str) -> None:
    uploaded = st.file_uploader("Note file (PDF or HTML)", type=["html", "htm", "pdf"],
                                key="note_file_upload")
    if uploaded:
        _parse_and_cache(note_number, uploaded)


def _parse_and_cache(note_number: str, uploaded) -> None:
    data = uploaded.read()
    with st.spinner(f"Parsing {uploaded.name}…"):
        try:
            sap_note = (parse_note_pdf(data, uploaded.name)
                        if uploaded.name.lower().endswith(".pdf")
                        else parse_note(data, uploaded.name))
        except Exception as exc:
            st.error(f"Parse error: {exc}")
            return
    if not sap_note:
        st.error("Could not parse. Try the Upload File tab or Enter Manually.")
        return
    meta = note_from_sap_note(sap_note, source="uploaded")
    save_note(meta)
    st.success(f"✅ Note **{note_number}** loaded — {sap_note.title or '(no title)'}")
    if sap_note.parser_warnings:
        st.warning("Parser warnings: " + " | ".join(sap_note.parser_warnings))



    st.rerun()


def _manual_metadata_form(note_number: str) -> None:
    with st.form("manual_note_form"):
        c1, c2 = st.columns(2)
        with c1:
            m_title    = st.text_input("Note Title")
            m_severity = st.selectbox("Severity", ["", "Critical", "High", "Medium", "Low"])
            m_cvss     = st.number_input("CVSS Score", min_value=0.0, max_value=10.0,
                                         step=0.1, value=0.0)
        with c2:
            m_comp   = st.text_input("Affected Component *", placeholder="SAP_BASIS")
            m_rel    = st.text_input("Release *",            placeholder="756")
            m_sp_from = st.text_input("SP From *",           placeholder="0000")
            m_sp_to   = st.text_input("SP To *",             placeholder="0008")
        if st.form_submit_button("💾 Save Manual Metadata", use_container_width=True):
            if not (note_number and m_comp and m_rel):
                st.error("Note number, component, and release are required.")
            else:
                save_note(build_manual_metadata(
                    note_number, m_title, m_severity, m_cvss,
                    m_comp, m_rel, m_sp_from, m_sp_to,
                ))
                st.success(f"Metadata saved for note {note_number}.")
                st.rerun()
