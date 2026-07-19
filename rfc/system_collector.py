
"""
Live SAP system metadata collector via RFC.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import List

from core.domain_models import LiveSystemInfo, SystemComponent
from rfc.connector import SapRfcConnection, RfcCallError, read_table

logger = logging.getLogger(__name__)


def _parse_db_version(raw: str) -> str:
    """Extract a clean version string from RFC DB version data."""
    if not raw:
        return ""
    m = re.search(r"[\d]+(?:[._][\d]+)+", raw)
    return m.group(0) if m else raw.strip()[:30]


def collect_system_info(conn: SapRfcConnection) -> LiveSystemInfo:
    warnings: List[str] = []

    sid = client = host = sap_release = kernel_release = kernel_patch = ""
    db_system = db_version = os_version = ""

    # Step 1: RFC_SYSTEM_INFO
    try:
        sysinfo = conn.call("RFC_SYSTEM_INFO")
        rfcsi   = sysinfo.get("RFCSI_EXPORT", {})
        sid           = rfcsi.get("RFCSYSID",  "").strip()
        client        = rfcsi.get("RFCCLIENT", "").strip()
        host          = rfcsi.get("RFCHOST",   "").strip()
        sap_release   = rfcsi.get("RFCSAPRL",  "").strip()
        kernel_release = rfcsi.get("RFCKERNRL","").strip()
        db_system     = rfcsi.get("RFCDBSYS",  "").strip()
        logger.info("RFC_SYSTEM_INFO: SID=%s release=%s db=%s", sid, sap_release, db_system)
    except RfcCallError as exc:
        warnings.append(f"RFC_SYSTEM_INFO failed: {exc}")

    # Step 2: Kernel patch level via TH_GET_VMODE
    try:
        vmode = conn.call("TH_GET_VMODE")
        kpatch = vmode.get("PATCH", vmode.get("KERNPATCH", "")).strip()
        if kpatch:
            kernel_patch = kpatch
    except Exception:
        pass

    # Step 3: DB version
    try:
        dbinfo = conn.call("DB_VERSION_GET_SCMON")
        db_version = _parse_db_version(str(dbinfo.get("VERSION", dbinfo.get("DB_VERSION", ""))))
    except Exception:
        pass
    if not db_version:
        try:
            rows = read_table(conn, table="SVERS", fields=["COMP", "RELEASE"], max_rows=5)
            for row in rows:
                if "DB" in row.get("COMP", "").upper():
                    db_version = row.get("RELEASE", "").strip()
                    break
        except Exception:
            pass

    # Step 4: OS version via READ_TEXT or SINFO_GET_OSVER
    try:
        osver = conn.call("SINFO_GET_OSVER")
        os_version = (str(osver.get("OSVER", "")) + " " + str(osver.get("OSBITS", ""))).strip()
    except Exception:
        pass
    if not os_version:
        try:
            sysver = conn.call("RFC_SYSTEM_INFO")
            os_raw = sysver.get("RFCSI_EXPORT", {}).get("RFCOPSYS", "").strip()
            if os_raw:
                os_version = os_raw
        except Exception:
            pass

    # Step 5: CVERS — installed software components
    components: List[SystemComponent] = []
    try:
        try:
            rows = read_table(conn, table="CVERS",
                              fields=["COMPONENT", "RELEASE", "EXTRELEASE", "SP", "PATCH"],
                              max_rows=500)
        except RfcCallError:
            try:
                rows = read_table(conn, table="CVERS",
                                  fields=["COMPONENT", "RELEASE", "SP", "PATCH"],
                                  max_rows=500)
            except RfcCallError:
                rows = read_table(conn, table="CVERS", fields=[], max_rows=500)

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
            if "SAPEXE" in comp_name.upper() and not kernel_patch:
                kernel_patch = row.get("PATCH", "").strip()

        logger.info("CVERS: %d components", len(components))
        if not components:
            warnings.append("CVERS table returned no rows")
    except RfcCallError as exc:
        warnings.append(f"CVERS read failed: {exc}")

    if not components:
        try:
            sysver = conn.call("SYSINFO_GET_VERSION")
            kern = sysver.get("VERSION", "")
            if kern:
                kernel_release = kern.strip()
                warnings.append("Used SYSINFO_GET_VERSION — CVERS unavailable")
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
        db_version=db_version,
        os_version=os_version,
        components=components,
        implemented_notes=[],
        collected_at=datetime.now().isoformat(timespec="seconds"),
        collection_warnings=warnings,
    )


def get_component(system: LiveSystemInfo, name: str):
    target  = name.upper().strip()
    aliases = {target, target.replace("SAP_", ""), "SAP_" + target.replace("SAP_", "")}
    for c in system.components:
        if c.name.upper().strip() in aliases:
            return c
    return None
