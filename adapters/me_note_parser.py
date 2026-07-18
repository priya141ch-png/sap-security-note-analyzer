"""
adapters/me_note_parser.py

Converts a note_dict from fetch_note_json_me() into a SapSecurityNote.
"""
from __future__ import annotations
import logging
import re
from html import unescape
from typing import List, Optional

from bs4 import BeautifulSoup

from core.domain_models import (
    NoteApplicabilityMatrixEntry,
    NotePrerequisite,
    SapSecurityNote,
)

logger = logging.getLogger(__name__)

_PRIORITY_SEVERITY = {
    "very high priority":     "Critical",
    "hot news":               "Critical",
    "correction with very high priority": "Critical",
    "high priority":          "High",
    "correction with high priority":      "High",
    "medium priority":        "Medium",
    "correction with medium priority":    "Medium",
    "low priority":           "Low",
    "correction with low priority":       "Low",
}


def _html_to_text(html: str) -> str:
    """Strip HTML tags, decode entities, collapse whitespace."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        return re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    except Exception:
        return unescape(re.sub(r"<[^>]+>", " ", html)).strip()


def _extract_section(long_text_html: str, section_ids: List[str]) -> str:
    """
    Extract a named section from the note LongText HTML.
    Sections are marked as <h3 id="Symptom">...</h3> followed by <p> content.
    """
    if not long_text_html:
        return ""
    try:
        soup = BeautifulSoup(long_text_html, "lxml")
        for sid in section_ids:
            heading = soup.find(["h2", "h3", "h4"], id=sid)
            if not heading:
                heading = soup.find(["h2", "h3", "h4"],
                                    string=re.compile(rf"^\s*{re.escape(sid)}\s*$", re.I))
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
    """Try to extract a CVSS score from the note HTML body."""
    if not long_text_html:
        return 0.0
    m = re.search(r"CVSS[^:]*:\s*([\d.]+)", long_text_html, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 0.0


def _build_applicability(validity_items: list, support_packages: list) -> List[NoteApplicabilityMatrixEntry]:
    """
    Build applicability matrix from validity_items and support_packages.

    validity_items: [{SoftwareComponent, From, To}, ...]
    support_packages: [{SoftwareComponent, SupportPackage, PatchLevel, ...}, ...]
    """
    entries: List[NoteApplicabilityMatrixEntry] = []

    # Validity ranges (component + release range)
    for v in (validity_items or []):
        comp = v.get("SoftwareComponent", "")
        frm  = v.get("From", "")
        to   = v.get("To", "")
        if comp:
            entries.append(NoteApplicabilityMatrixEntry(
                component=comp,
                release=frm,
                sp_from="",
                sp_to=to,
            ))

    # Support package patches
    for sp in (support_packages or []):
        comp = sp.get("SoftwareComponent", "")
        rel  = sp.get("Release", "")
        spl  = sp.get("SupportPackage", "")
        patch = sp.get("PatchLevel", "")
        if comp:
            entries.append(NoteApplicabilityMatrixEntry(
                component=comp,
                release=rel,
                sp_from=spl,
                patch_level=patch,
            ))

    return entries


def parse_note_json_me(note_dict: dict) -> Optional[SapSecurityNote]:
    """
    Convert a note_dict from fetch_note_json_me() into a SapSecurityNote.
    Returns None if note_dict is None or clearly invalid.
    """
    if not note_dict:
        return None

    warnings: list = []
    long_html = note_dict.get("long_text_html", "")

    note_number = str(note_dict.get("number", "")).strip()
    if not note_number:
        warnings.append("Note number missing from API response")

    title = note_dict.get("title", "")
    # Title from API is "2424539 - Actual Title" — strip the leading number
    if " - " in title:
        title = title.split(" - ", 1)[1].strip()

    severity = _map_severity(note_dict.get("priority", ""))
    if not severity:
        warnings.append(f"Could not map priority '{note_dict.get('priority', '')}' to severity")

    cvss = _extract_cvss(long_html)

    symptoms = _extract_section(long_html, ["Symptom", "Symptoms", "Problem", "Description"])
    solution = _extract_section(long_html, ["Solution", "Cause and Solution", "Resolution"])
    workaround = _extract_section(long_html, [
        "Workaround", "Interim Solution", "Other Terms", "Work Around"
    ])

    if not symptoms:
        warnings.append("Symptom section not found in LongText")
    if not solution:
        warnings.append("Solution section not found in LongText")

    # Components: primary component + all validity SW components
    components: List[str] = []
    comp_key = note_dict.get("component_key", "")
    if comp_key:
        components.append(comp_key)
    for v in note_dict.get("validity_items", []):
        sc = v.get("SoftwareComponent", "")
        if sc and sc not in components:
            components.append(sc)

    matrix = _build_applicability(
        note_dict.get("validity_items", []),
        note_dict.get("support_packages", []),
    )

    prereqs: List[NotePrerequisite] = []
    for p in note_dict.get("preconditions", []):
        pnum = str(p.get("NoteNumber", p.get("Number", ""))).strip()
        ptitle = p.get("Title", p.get("ShortText", ""))
        if pnum:
            prereqs.append(NotePrerequisite(note_number=pnum, title=ptitle))
    for ref in note_dict.get("references_to", []):
        rnum = str(ref.get("Number", ref.get("NoteNumber", ""))).strip()
        rtitle = ref.get("Title", ref.get("ShortText", ""))
        if rnum:
            prereqs.append(NotePrerequisite(note_number=rnum, title=rtitle))

    published = note_dict.get("released_on", "")

    if not matrix:
        warnings.append("No software component validity data found")

    logger.info("Parsed note %s: severity=%s cvss=%.1f components=%s",
                note_number, severity, cvss, components)

    return SapSecurityNote(
        note_number=note_number,
        title=title,
        severity=severity,
        cvss_score=cvss,
        symptoms=symptoms,
        solution=solution,
        workaround=workaround,
        components=components,
        applicability_matrix=matrix,
        prerequisites=prereqs,
        published_date=published,
        parser_warnings=warnings,
    )
