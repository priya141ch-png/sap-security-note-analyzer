
"""
adapters/me_note_parser.py
Converts note_dict from fetch_note_json_me() -> SapSecurityNote.
"""
from __future__ import annotations
import logging
import re
from html import unescape
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from core.domain_models import NoteApplicabilityMatrixEntry, NotePrerequisite, SapSecurityNote

logger = logging.getLogger(__name__)

_PRIORITY_SEVERITY = {
    "very high priority":                 "Critical",
    "hot news":                           "Critical",
    "correction with very high priority": "Critical",
    "high priority":                      "High",
    "correction with high priority":      "High",
    "medium priority":                    "Medium",
    "correction with medium priority":    "Medium",
    "low priority":                       "Low",
    "correction with low priority":       "Low",
}

_RE_KERNEL = re.compile(
    r"(?:sap\s+)?kernel\s*(?:patch\s*(?:level|number)?|release|version)?\s*[:\-]?\s*(\d[\d./]*)",
    re.I,
)

_RE_DB = [
    (re.compile(r"hana\s+(?:2\.0\s+)?(?:sps|sp)\s*(\d+)", re.I),              "HANA"),
    (re.compile(r"oracle\s+(?:database\s+)?(\d+(?:[cg])?)", re.I),              "Oracle"),
    (re.compile(r"microsoft\s+sql\s+server\s+(\d{4})", re.I),                   "MSSQL"),
    (re.compile(r"(?:ibm\s+)?db2\s+(?:for\s+[\w/]+\s+)?v?(\d+\.\d+)", re.I),  "DB2"),
    (re.compile(r"sybase\s+(?:ase\s+)?(\d+\.\d+)", re.I),                      "Sybase"),
    (re.compile(r"maxdb\s+(?:version\s+)?(\d+\.\d+)", re.I),                   "MaxDB"),
]

_RE_OS = [
    (re.compile(r"red\s*hat\s+(?:enterprise\s+linux|rhel)\s+(\d+)", re.I),  "RHEL"),
    (re.compile(r"suse\s+linux\s+enterprise\s*(?:server)?\s+(\d+)", re.I),  "SLES"),
    (re.compile(r"windows\s+server\s+(\d{4})", re.I),                       "Windows Server"),
    (re.compile(r"aix\s+(\d+\.\d+)", re.I),                                 "AIX"),
    (re.compile(r"solaris\s+(\d+)", re.I),                                   "Solaris"),
    (re.compile(r"hp-?ux\s+(\d+\.\d+)", re.I),                              "HP-UX"),
]


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    except Exception:
        return unescape(re.sub(r"<[^>]+>", " ", html)).strip()


def _extract_section(long_text_html: str, section_ids: List[str]) -> str:
    if not long_text_html:
        return ""
    try:
        soup = BeautifulSoup(long_text_html, "lxml")
        for sid in section_ids:
            heading = soup.find(["h2", "h3", "h4"], id=sid)
            if not heading:
                heading = soup.find(
                    ["h2", "h3", "h4"],
                    string=re.compile(rf"^\s*{re.escape(sid)}\s*$", re.I),
                )
            if heading:
                parts = []
                for sib in heading.find_next_siblings():
                    if sib.name in ("h2", "h3", "h4"):
                        break
                    parts.append(sib.get_text(" "))
                return re.sub(r"\s+", " ", " ".join(parts)).strip()
    except Exception:
        pass
    return ""


def _map_severity(priority_text: str) -> str:
    key = (priority_text or "").lower()
    for k, v in _PRIORITY_SEVERITY.items():
        if k in key:
            return v
    return ""


def _extract_cvss(long_text_html: str) -> float:
    if not long_text_html:
        return 0.0
    m = re.search(r"CVSS[^:]*:\s*([\d.]+)", long_text_html, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0


def _extract_kernel_requirement(text: str) -> Tuple[str, str]:
    if not text:
        return "", ""
    matches = _RE_KERNEL.findall(text)
    if not matches:
        return "", ""
    versions = sorted(set(matches))
    return versions[0], (versions[-1] if len(versions) > 1 else "")


def _extract_db_requirement(text: str) -> Tuple[str, str]:
    for pattern, db_name in _RE_DB:
        m = pattern.search(text)
        if m:
            return db_name, m.group(1)
    return "", ""


def _extract_os_requirement(text: str) -> Tuple[str, str]:
    for pattern, os_name in _RE_OS:
        m = pattern.search(text)
        if m:
            return os_name, m.group(1)
    return "", ""


def _build_applicability(validity_items: list, support_packages: list) -> List[NoteApplicabilityMatrixEntry]:
    """
    Build matrix entries.
    - validity_items: From/To are RELEASE numbers (e.g. 750 -> 758).
    - support_packages: give the fix SP for a specific release.
    """
    entries: List[NoteApplicabilityMatrixEntry] = []

    for v in (validity_items or []):
        comp = v.get("SoftwareComponent", "")
        frm  = str(v.get("From", "")).strip()
        to   = str(v.get("To", "")).strip()
        if comp:
            entries.append(NoteApplicabilityMatrixEntry(
                component=comp,
                release=frm,
                release_to=to,
                sp_from="",
                sp_to="",
                entry_type="validity",
            ))

    for sp in (support_packages or []):
        comp    = sp.get("SoftwareComponent", "")
        rel     = str(sp.get("Release", "")).strip()
        sp_name = sp.get("SupportPackage", "")
        patch   = sp.get("PatchLevel", "")
        if comp and rel:
            entries.append(NoteApplicabilityMatrixEntry(
                component=comp,
                release=rel,
                release_to=rel,
                sp_from="",
                sp_to=sp_name,
                patch_level=patch,
                entry_type="support_package",
            ))

    return entries


def parse_note_json_me(note_dict: dict) -> Optional[SapSecurityNote]:
    if not note_dict:
        return None

    warnings: list = []
    long_html  = note_dict.get("long_text_html", "")
    plain_text = _html_to_text(long_html)

    note_number = str(note_dict.get("number", "")).strip()
    if not note_number:
        warnings.append("Note number missing from API response")

    title = note_dict.get("title", "")
    if " - " in title:
        title = title.split(" - ", 1)[1].strip()

    severity = _map_severity(note_dict.get("priority", ""))
    if not severity:
        warnings.append(f"Could not map priority '{note_dict.get('priority', '')}' to severity")

    cvss       = _extract_cvss(long_html)
    symptoms   = _extract_section(long_html, ["Symptom", "Symptoms", "Problem", "Description"])
    solution   = _extract_section(long_html, ["Solution", "Cause and Solution", "Resolution"])
    workaround = _extract_section(long_html, ["Workaround", "Interim Solution", "Other Terms", "Work Around"])

    if not symptoms:
        warnings.append("Symptom section not found in LongText")
    if not solution:
        warnings.append("Solution section not found in LongText")

    kernel_min, kernel_max  = _extract_kernel_requirement(plain_text)
    db_type, db_version_min = _extract_db_requirement(plain_text)
    os_type, os_version_min = _extract_os_requirement(plain_text)

    components: List[str] = []
    comp_key = note_dict.get("component_key", "")
    if comp_key:
        components.append(comp_key)
    for v in note_dict.get("validity_items", []):
        sc = v.get("SoftwareComponent", "")
        if sc and sc not in components:
            components.append(sc)

    matrix  = _build_applicability(note_dict.get("validity_items", []), note_dict.get("support_packages", []))
    prereqs: List[NotePrerequisite] = []
    for p in note_dict.get("preconditions", []):
        pnum   = str(p.get("NoteNumber", p.get("Number", ""))).strip()
        ptitle = p.get("Title", p.get("ShortText", ""))
        if pnum:
            prereqs.append(NotePrerequisite(note_number=pnum, title=ptitle))
    for ref in note_dict.get("references_to", []):
        rnum   = str(ref.get("Number", ref.get("NoteNumber", ""))).strip()
        rtitle = ref.get("Title", ref.get("ShortText", ""))
        if rnum:
            prereqs.append(NotePrerequisite(note_number=rnum, title=rtitle))

    if not matrix:
        warnings.append("No software component validity data found")

    logger.info("Parsed note %s: severity=%s components=%s kernel=%s db=%s os=%s",
                note_number, severity, components, kernel_min, db_type, os_type)

    return SapSecurityNote(
        note_number=note_number,
        title=title,
        severity=severity,
        cvss_score=cvss,
        symptoms=symptoms,
        solution=solution,
        workaround=workaround,
        long_text_html=long_html,
        components=components,
        applicability_matrix=matrix,
        prerequisites=prereqs,
        published_date=note_dict.get("released_on", ""),
        parser_warnings=warnings,
        kernel_min=kernel_min,
        kernel_max=kernel_max,
        db_type=db_type,
        db_version_min=db_version_min,
        os_type=os_type,
        os_version_min=os_version_min,
    )
