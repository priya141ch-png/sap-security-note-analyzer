"""
Fetch SAP Security Note metadata directly from a connected SAP system via RFC.

SAP stores note data in internal tables (CWBNTHEAD, CWBNTSOPC, etc.).
This avoids the SAP Support Portal entirely — no S-user / 2FA needed.
Requires an active RFC connection (local pyrfc or relay).
"""
from __future__ import annotations
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# SAP internal note tables (available on all ABAP systems with SNOTE)
_NOTE_TABLES = {
    "header":     "CWBNTHEAD",   # Note header: NUMM, VERSNO, TITLE
    "header_alt": "CWBNTSNO",    # Alternative header table name (older systems)
    "conditions": "CWBNTSOPC",   # Component/SP conditions: NUMM, COMPONENT, RELEASE, PATCHFR, PATCHTO
    "conds_alt":  "CWBNTSOPL",   # Alternative conditions table
}


def fetch_note_from_system(
    conn,
    note_number: str,
) -> Tuple[Optional[dict], str]:
    """
    Read note metadata from the connected SAP system.
    Returns (note_dict, error_message).

    note_dict keys: title, severity, cvss_score, applicability_matrix
    applicability_matrix: list of {component, release, sp_from, sp_to}
    """
    from rfc.connector import read_table, RfcCallError

    padded = note_number.zfill(10)
    note_dict = {
        "note_number": note_number,
        "title": "",
        "severity": "",
        "cvss_score": "",
        "applicability_matrix": [],
        "source": "rfc",
    }

    # ── 1. Fetch note title ───────────────────────────────────────────────────
    title = _fetch_title(conn, padded, read_table, RfcCallError)
    note_dict["title"] = title

    # ── 2. Fetch applicability matrix (component/SP conditions) ──────────────
    matrix, warn = _fetch_conditions(conn, padded, read_table, RfcCallError)
    note_dict["applicability_matrix"] = matrix

    if not title and not matrix:
        return None, (
            f"Note {note_number} not found in this SAP system's note database "
            f"(CWBNTHEAD / CWBNTSOPC). "
            f"The note may not have been downloaded to this system via SNOTE yet."
        )

    if warn:
        logger.warning("Note conditions warning: %s", warn)

    return note_dict, ""


def _fetch_title(conn, padded: str, read_table, RfcCallError) -> str:
    """Try CWBNTHEAD then CWBNTSNO for the note title."""
    for table, lang_where in [
        ("CWBNTHEAD", [f"NUMM EQ '{padded}'", "AND SPRSL EQ 'E'"]),
        ("CWBNTHEAD", [f"NUMM EQ '{padded}'"]),
        ("CWBNTSNO",  [f"NUMM EQ '{padded}'", "AND SPRSL EQ 'E'"]),
        ("CWBNTSNO",  [f"NUMM EQ '{padded}'"]),
    ]:
        try:
            rows = read_table(conn, table=table, fields=["NUMM", "TITLE"],
                              where=lang_where, max_rows=5)
            if rows:
                return rows[0].get("TITLE", "").strip()
        except RfcCallError:
            pass
        except Exception:
            pass
    return ""


def _fetch_conditions(conn, padded: str, read_table, RfcCallError) -> Tuple[list, str]:
    """Read component/SP applicability conditions from CWBNTSOPC or CWBNTSOPL."""
    matrix = []
    warn = ""

    for table, fields in [
        ("CWBNTSOPC", ["NUMM", "COMPONENT", "RELEASE", "PATCHFR", "PATCHTO"]),
        ("CWBNTSOPC", ["NUMM", "COMPONENT", "RELEASE"]),
        ("CWBNTSOPL", ["NUMM", "COMPONENT", "RELEASE", "PATCHFR", "PATCHTO"]),
    ]:
        try:
            rows = read_table(conn, table=table, fields=fields,
                              where=[f"NUMM EQ '{padded}'"], max_rows=200)
            for row in rows:
                comp = row.get("COMPONENT", "").strip()
                if not comp:
                    continue
                matrix.append({
                    "component":  comp,
                    "release":    row.get("RELEASE", "").strip(),
                    "sp_from":    row.get("PATCHFR", "").strip(),
                    "sp_to":      row.get("PATCHTO", "").strip(),
                })
            if matrix:
                return matrix, ""
        except RfcCallError as exc:
            warn = str(exc)
            continue
        except Exception as exc:
            warn = str(exc)
            continue

    return matrix, warn
