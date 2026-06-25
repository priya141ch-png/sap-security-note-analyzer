"""RFC Connection Profiles — grouped by Client organisation."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime

import streamlit as st

from core.domain_models import RfcProfile
from rfc.connector import PYRFC_AVAILABLE, is_relay_connected, test_connection
from storage.credentials import (
    delete_profile, encrypt_password, list_profiles,
    save_profile, update_test_result,
)
from ui.components import section

_ENV_OPTIONS   = ["", "Production", "Quality / UAT", "Development", "Sandbox", "Training"]
_LANG_OPTIONS  = ["EN", "DE", "FR", "ES", "JA", "ZH"]


def render() -> None:
    st.title("RFC Connection Profiles")
    st.caption("Organise your SAP systems by Client. Each Client can have multiple systems (Dev/QA/Prod).")

    if not PYRFC_AVAILABLE:
        if is_relay_connected():
            st.success("🔗 **Relay connected** — connection tests run through your VPN laptop.")
        else:
            st.info(
                "🔌 **RFC via Relay** — Save profiles here. "
                "Connect to VPN and run **`relay\\relay.bat`** on your laptop to enable live checks."
            )

    profiles = list_profiles()

    # ── Existing profiles grouped by client ──────────────────────────────────
    if profiles:
        section("Saved Profiles")

        # Group by client_group (blank → "Ungrouped")
        groups: dict[str, list] = defaultdict(list)
        for p in profiles:
            groups[p.client_group or "Ungrouped"].append(p)

        for group_name in sorted(groups.keys()):
            grp_profiles = groups[group_name]
            ok_count  = sum(1 for p in grp_profiles if p.last_test_ok)
            fail_count = sum(1 for p in grp_profiles if p.last_tested and not p.last_test_ok)

            # Client header row
            st.markdown(
                f"<div style='background:#002A45;color:#fff;padding:8px 14px;"
                f"border-radius:8px 8px 0 0;margin-top:12px;display:flex;"
                f"align-items:center;gap:10px'>"
                f"<span style='font-size:16px'>🏢</span>"
                f"<b style='font-size:15px'>{group_name}</b>"
                f"<span style='font-size:12px;margin-left:auto;opacity:.75'>"
                f"{len(grp_profiles)} system(s)"
                f"{'  ✅ '+str(ok_count) if ok_count else ''}"
                f"{'  ❌ '+str(fail_count) if fail_count else ''}"
                f"</span></div>",
                unsafe_allow_html=True,
            )

            for p in grp_profiles:
                env_badge = (
                    f"<span style='background:#EF5350;color:#fff;padding:1px 7px;"
                    f"border-radius:10px;font-size:11px'>{p.environment}</span>"
                    if p.environment == "Production"
                    else f"<span style='background:#42A5F5;color:#fff;padding:1px 7px;"
                         f"border-radius:10px;font-size:11px'>{p.environment}</span>"
                    if p.environment
                    else ""
                )
                icon = "✅" if p.last_test_ok else "❌" if p.last_tested else "⬜"
                with st.expander(
                    f"{icon}  {p.name}   {p.host}  ·  SY{p.sysnr}  ·  client {p.client}"
                ):
                    st.markdown(env_badge, unsafe_allow_html=True)
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Host", p.host)
                    c2.metric("SysNr", p.sysnr)
                    c3.metric("Client", p.client)
                    c4.metric("Environment", p.environment or "—")
                    st.caption(
                        f"RFC User: `{p.user}` | Lang: {p.lang} | "
                        f"Timeout: {p.timeout}s"
                        + (f" | {p.description}" if p.description else "")
                    )
                    if p.last_tested:
                        st.caption(
                            f"Last test: {p.last_tested}  →  "
                            f"**{'✅ OK' if p.last_test_ok else '❌ FAILED'}**"
                        )

                    ct1, ct2, ct3 = st.columns([3, 2, 2])
                    with ct1:
                        test_pw = st.text_input(
                            "Password", type="password",
                            key=f"tpw_{p.name}", label_visibility="collapsed",
                            placeholder="Enter password to test connection",
                        )
                    with ct2:
                        if st.button("🔗 Test Connection", key=f"test_{p.name}"):
                            if not test_pw:
                                st.warning("Enter the password first.")
                            else:
                                with st.spinner("Testing…"):
                                    ok, msg = test_connection(
                                        {"host": p.host, "sysnr": p.sysnr,
                                         "client": p.client, "user": p.user,
                                         "lang": p.lang, "timeout": p.timeout},
                                        test_pw,
                                    )
                                update_test_result(p.name, ok)
                                (st.success if ok else st.error)(msg)
                    with ct3:
                        if st.button("🗑️ Delete", key=f"del_{p.name}"):
                            delete_profile(p.name)
                            st.success(f"'{p.name}' deleted.")
                            st.rerun()

    st.divider()

    # ── Add / Edit profile ────────────────────────────────────────────────────
    section("Add New Profile")

    # Auto-suggest existing client group names
    existing_groups = sorted({p.client_group for p in profiles if p.client_group})

    with st.form("new_profile_form", clear_on_submit=True):
        st.markdown("**Client Organisation**")
        cg_col1, cg_col2 = st.columns([2, 2])
        with cg_col1:
            client_group_select = st.selectbox(
                "Existing Client", ["— Create new —"] + existing_groups,
                key="cg_select",
            )
        with cg_col2:
            client_group_new = st.text_input(
                "New Client Name",
                placeholder="e.g. Daimler Trucks",
                disabled=(client_group_select != "— Create new —"),
            )

        st.markdown("**System Details**")
        col1, col2 = st.columns(2)
        with col1:
            name        = st.text_input("Profile Name *", placeholder="DAIMLER-PRD")
            host        = st.text_input("App Server Host *", placeholder="sap-prd.daimler.com")
            sysnr       = st.text_input("System Number *", value="00")
            sap_client  = st.text_input("SAP Client *", value="100")
        with col2:
            user        = st.text_input("RFC User *", placeholder="RFC_READ")
            password    = st.text_input("Password *", type="password")
            environment = st.selectbox("Environment", _ENV_OPTIONS)
            lang        = st.selectbox("Language", _LANG_OPTIONS)
            timeout     = st.number_input("Timeout (s)", min_value=5, max_value=300, value=30)
        description = st.text_area("Description (optional)", height=50)

        if st.form_submit_button("💾  Save Profile", type="primary", use_container_width=True):
            # Resolve client group
            cg = (client_group_new.strip()
                  if client_group_select == "— Create new —"
                  else client_group_select)

            missing = [f for f, v in [
                ("Name", name), ("Host", host), ("System Number", sysnr),
                ("SAP Client", sap_client), ("User", user), ("Password", password),
            ] if not v]

            if missing:
                st.error(f"Required fields missing: {', '.join(missing)}")
            elif _profile_exists(name, profiles):
                st.error(f"Profile '{name}' already exists. Delete it first.")
            else:
                save_profile(RfcProfile(
                    name=name, host=host, sysnr=sysnr, client=sap_client,
                    user=user, password_enc=encrypt_password(password),
                    lang=lang, timeout=timeout, description=description,
                    client_group=cg, environment=environment,
                    created_at=datetime.now().isoformat(timespec="seconds"),
                ))
                st.success(f"✅ Profile **{name}** saved under client **{cg or 'Ungrouped'}**.")
                st.rerun()

    st.divider()
    st.info(
        "💡 **Tip:** Group all systems belonging to the same customer under one **Client** name "
        "(e.g. *Daimler Trucks*). This lets you select all systems for that client at once "
        "when running a note check.\n\n"
        "**Min. RFC authorisations:** `S_RFC` (RFC_PING, RFC_SYSTEM_INFO, RFC_READ_TABLE) "
        "and `S_TABU_DIS` for tables CVERS, CWBNTCUST."
    )


def _profile_exists(name: str, profiles: list) -> bool:
    return any(p.name == name for p in profiles)
