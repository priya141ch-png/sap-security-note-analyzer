"""
Live SAP system metadata collector.
Reads system info, installed components (CVERS), and kernel via RFC.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import List

from core.domain_models import LiveSystemInfo, SystemComponent
from rfc.connector import SapRfcConnection, RfcCallError, read_table

logger = logging.getLogger(__name__)


def collect_system_info(conn: SapRfcConnection) -> LiveSystemInfo:
    """
    Collect complete system metadata from a live SAP connection.
    Combines RFC_SYSTEM_INFO + CVERS table read.
    """
    warnings: List[str] = []

    # ── Step 1: Basic system info ─────────────────────────────────────────────
    sid = client = host = sap_release = kernel_release = kernel_patch = db_system = ""
    try:
        sysinfo = conn.call("RFC_SYSTEM_INFO")
        rfcsi = sysinfo.get("RFCSI_EXPORT", {})
        sid           = rfcsi.get("RFCSYSID", "").strip()
        client        = rfcsi.get("RFCCLIENT", "").strip()
        host          = rfcsi.get("RFCHOST", "").strip()
        sap_release   = rfcsi.get("RFCSAPRL", "").strip()   # e.g. "756"
        kernel_release = rfcsi.get("RFCKERNRL", "").strip()  # e.g. "7.77"
        db_system     = rfcsi.get("RFCDBSYS", "").strip()
        logger.info("RFC_SYSTEM_INFO: SID=%s client=%s release=%s", sid, client, sap_release)
    except RfcCallError as exc:
        warnings.append(f"RFC_SYSTEM_INFO failed: {exc}")
        logger.warning("RFC_SYSTEM_INFO error: %s", exc)

    # ── Step 2: Installed components from CVERS ───────────────────────────────
    components: List[SystemComponent] = []
    try:
        rows = read_table(
            conn,
            table="CVERS",
            fields=["COMPONENT", "RELEASE", "EXTRELEASE", "SP", "PATCH"],
            max_rows=500,
        )
        for row in rows:
            comp_name = row.get("COMPONENT", "").strip()
            if not comp_name:
                continue
            components.append(SystemComponent(
                name=comp_name,
                release=row.get("RELEASE", "").strip(),
                sp_level=row.get("SP", "").strip(),
                patch_level=row.get("PATCH", "").strip(),
                description="",
            ))
            # Enrich kernel from SAPEXE component
            comp_upper = comp_name.upper()
            if "SAPEXE" in comp_upper and not kernel_patch:
                kernel_patch = row.get("PATCH", "").strip()

        logger.info("CVERS: %d components found", len(components))
        if not components:
            warnings.append("CVERS table returned no rows — check RFC_READ_TABLE authorization")
    except RfcCallError as exc:
        warnings.append(f"CVERS read failed: {exc} — check S_TABU_DIS authorization for CVERS")
        logger.warning("CVERS read error: %s", exc)

    # ── Step 3: Fallback — read CVERS via /SDF/SMON or SINFO ─────────────────
    if not components:
        try:
            # Some systems expose SYSINFO_GET_VERSION
            sysver = conn.call("SYSINFO_GET_VERSION")
            kern = sysver.get("VERSION", "")
            if kern:
                kernel_release = kern.strip()
                warnings.append("Used SYSINFO_GET_VERSION for kernel — CVERS unavailable")
        except Exception:
            pass

    return LiveSystemInfo(
        sid=sid,
        client=client,
        host=host,
        sap_release=sap_release,
        kernel_release=kernel_release,
        kernel_patch=kernel_patch,
        db_system=db_system,
        components=components,
        implemented_notes=[],    # filled by notes_checker
        collected_at=datetime.now().isoformat(timespec="seconds"),
        collection_warnings=warnings,
    )


def get_component(system: LiveSystemInfo, name: str) -> SystemComponent | None:
    """Find a specific component by name (case-insensitive, strips SAP_ prefix variants)."""
    target = name.upper().strip()
    aliases = {target, target.replace("SAP_", ""), "SAP_" + target.replace("SAP_", "")}
    for c in system.components:
        if c.name.upper().strip() in aliases:
            return c
    return None
