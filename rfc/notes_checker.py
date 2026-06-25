"""
Check implemented SAP Notes by reading CWBNTCUST via RFC_READ_TABLE.

CWBNTCUST columns used:
  NUMM     - Note number (10 chars, zero-padded)
  VERSNO   - Version number
  PRSTATUS - Processing status:
               ' '  (space) = Successfully implemented
               'E'          = Implementation error
               'N'          = Not yet implemented (downloaded only)
               'C'          = Can be implemented
               '!'          = Obsolete / not relevant

We treat PRSTATUS = ' ' (space) as "Already Implemented".
"""

from __future__ import annotations
import logging
from typing import List, Set

from rfc.connector import SapRfcConnection, RfcCallError, read_table

logger = logging.getLogger(__name__)


def fetch_implemented_notes(conn: SapRfcConnection) -> tuple[List[str], str]:
    """
    Return (implemented_note_numbers, warning_message).
    implemented_note_numbers contains zero-stripped note numbers where PRSTATUS = ' '.
    """
    try:
        rows = read_table(
            conn,
            table="CWBNTCUST",
            fields=["NUMM", "VERSNO", "PRSTATUS"],
            max_rows=10000,
        )
        implemented: List[str] = []
        for row in rows:
            prstatus = row.get("PRSTATUS", "N").strip()
            # ' ' (space, i.e. empty after strip) = successfully implemented
            if prstatus == "" or prstatus == " ":
                note_num = row.get("NUMM", "").lstrip("0")
                if note_num:
                    implemented.append(note_num)
        logger.info("CWBNTCUST: %d implemented notes", len(implemented))
        return implemented, ""
    except RfcCallError as exc:
        warn = f"CWBNTCUST read failed: {exc} — check S_TABU_DIS auth for CWBNTCUST"
        logger.warning(warn)
        return [], warn


def is_note_implemented(note_number: str, implemented_notes: List[str]) -> bool:
    """Check if a note number (any padding) is in the implemented list."""
    stripped = note_number.lstrip("0")
    return stripped in implemented_notes


def get_note_cwbntcust_status(
    conn: SapRfcConnection, note_number: str
) -> tuple[bool, str, str]:
    """
    Check a single note in CWBNTCUST.
    Returns (found, prstatus, warning).
    """
    padded = note_number.zfill(10)
    try:
        rows = read_table(
            conn,
            table="CWBNTCUST",
            fields=["NUMM", "VERSNO", "PRSTATUS"],
            where=[f"NUMM EQ '{padded}'"],
            max_rows=10,
        )
        if not rows:
            return False, "", ""
        prstatus = rows[0].get("PRSTATUS", "N").strip()
        return True, prstatus, ""
    except RfcCallError as exc:
        return False, "", str(exc)
