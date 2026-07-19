"""Live System Inventory — show components and implemented notes from last RFC collection."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from rfc.connector import (
    PYRFC_AVAILABLE, build_connection, is_relay_connected, relay_call,
)
from rfc.system_collector import collect_system_info
from rfc.notes_checker import fetch_implemented_notes
from storage.credentials import decrypt_password, list_profiles
from ui.components import section


def render() -> None:
    st.title("Live System Inventory")

    system = st.session_state.get("last_system")

    if system:
        _show_inventory(system)
        st.divider()

    # Allow fresh collection
    section("Collect Fresh Inventory")
    profiles = list_profiles()
    if not profiles:
        st.info("Add an RFC profile first (RFC Connection Profiles page).")
        return
    relay_ok = is_relay_connected()
    if not PYRFC_AVAILABLE:
        if relay_ok:
            st.success("🔗 **Relay connected** — inventory will be collected through your VPN laptop.")
        else:
            st.info(
                "🔌 **RFC via Relay** — To collect live inventory, connect to office VPN and run "
                "**`relay\relay.bat`** on your laptop. No installation needed on this machine."
            )
            return

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        sel_profile = st.selectbox("RFC Profile", [p.name for p in profiles])
    with col2:
        pw = st.text_input("Password", type="password", key="inv_pw")
    with col3:
        st.write("")
        st.write("")
        run = st.button("🔄 Collect Now", type="primary")

    if run:
        if not pw:
            st.error("Enter the RFC password.")
            return
        profile = next(p for p in profiles if p.name == sel_profile)
        profile_dict = {"host": profile.host, "sysnr": profile.sysnr, "client": profile.client,
                        "user": profile.user, "lang": profile.lang, "timeout": profile.timeout}
        prog = st.progress(0.0)
        try:
            if PYRFC_AVAILABLE:
                conn = build_connection(profile_dict, pw)
                conn.connect()
                prog.progress(0.3, text="Connected — reading CVERS…")
                system = collect_system_info(conn)
                prog.progress(0.7, text="Reading CWBNTCUST…")
                impl, warn = fetch_implemented_notes(conn)
                system.implemented_notes = impl
                if warn:
                    system.collection_warnings.append(warn)
                conn.close()
            else:
                # Route through relay client running on VPN laptop
                prog.progress(0.2, text="Sending to relay client…")
                r1 = relay_call("system_info", profile_dict, pw)
                if not r1.get("ok"):
                    raise RuntimeError(f"Relay system_info failed: {r1.get('error', 'unknown')}")
                from core.domain_models import LiveSystemInfo, SystemComponent
                raw = r1["data"]
                system = LiveSystemInfo(
                    sid=raw.get("sid", ""),
                    client=raw.get("client", ""),
                    host=raw.get("host", ""),
                    sap_release=raw.get("sap_release", ""),
                    kernel_release=raw.get("kernel_release", ""),
                    kernel_patch=raw.get("kernel_patch", ""),
                    db_system=raw.get("db_system", ""),
                    db_version=raw.get("db_version", ""),
                    os_version=raw.get("os_version", ""),
                    components=[SystemComponent(**c) for c in raw.get("components", [])],
                    implemented_notes=raw.get("implemented_notes", []),
                    collected_at=raw.get("collected_at", ""),
                    collection_warnings=raw.get("collection_warnings", []),
                )
                prog.progress(0.7, text="Reading implemented notes…")
                r2 = relay_call("implemented_notes", profile_dict, pw)
                if r2.get("ok"):
                    system.implemented_notes = r2.get("data", [])
                    if r2.get("error"):
                        system.collection_warnings.append(r2["error"])

            prog.progress(1.0)
            st.session_state["last_system"] = system
            st.success(
                f"Inventory collected from **{system.sid}** — "
                f"{len(system.components)} components, "
                f"{len(system.implemented_notes)} implemented notes."
            )
            _show_inventory(system)
        except Exception as exc:
            prog.empty()
            st.error(f"Collection failed: {exc}")

def _show_inventory(system) -> None:
    section(f"System: {system.sid}  |  Client {system.client}  |  {system.host}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SAP Release", system.sap_release)
    c2.metric("Kernel", f"{system.kernel_release} PL{system.kernel_patch}")
    c3.metric("DB System", system.db_system or "—")
    c4.metric("Collected", system.collected_at or "—")

    section("Software Components (CVERS)")
    if system.components:
        df = pd.DataFrame([{
            "Component": c.name, "Release": c.release,
            "SP Level": c.sp_level, "Patch Level": c.patch_level,
            "Description": c.description,
        } for c in system.components])
        q = st.text_input("Filter components", placeholder="SAP_BASIS…", key="inv_filter")
        if q:
            df = df[df["Component"].str.contains(q, case=False) |
                    df["Description"].str.contains(q, case=False)]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(df)} components")
    else:
        st.warning("No components found — check RFC_READ_TABLE authorization for CVERS.")

    section(f"Implemented Notes ({len(system.implemented_notes)})")
    if system.implemented_notes:
        cols = st.columns(6)
        for i, n in enumerate(system.implemented_notes[:60]):
            cols[i % 6].code(n)
        if len(system.implemented_notes) > 60:
            st.caption(f"… and {len(system.implemented_notes) - 60} more")
    else:
        st.info("No implemented notes found (or CWBNTCUST not accessible).")

    if system.collection_warnings:
        with st.expander(f"⚠️ Warnings ({len(system.collection_warnings)})"):
            for w in system.collection_warnings:
                st.warning(w)
