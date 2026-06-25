"""
Parses SAP Security Notes from HTML print-view pages.
Handles the standard SAP Support Portal print-view format.
"""

from __future__ import annotations
import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from core.domain_models import (
    NoteApplicabilityMatrixEntry,
    NotePrerequisite,
    SapSecurityNote,
)

logger = logging.getLogger(__name__)

_SEVERITY_KEYWORDS = {"hot news": "Critical", "critical": "Critical",
                      "high": "High", "medium": "Medium", "low": "Low"}


def parse_note(html_bytes: bytes, filename: str = "") -> Optional[SapSecurityNote]:
    """Parse an SAP Note from HTML print-view bytes. Returns None on complete failure."""
    warnings: List[str] = []
    try:
        soup = BeautifulSoup(html_bytes, "lxml")
    except Exception as exc:
        logger.error("HTML parse error (%s): %s", filename, exc)
        return None

    note_number = _extract_note_number(soup, filename, warnings)
    if not note_number:
        warnings.append("Could not extract note number")
        note_number = Path_stem_fallback(filename)

    title = _extract_title(soup, warnings)
    severity = _extract_severity(soup, warnings)
    cvss = _extract_cvss(soup, warnings)
    symptoms = _extract_section(soup, ["Symptom", "Symptoms", "Problem"])
    solution = _extract_section(soup, ["Solution", "Cause and Solution"])
    workaround = _extract_section(soup, ["Workaround", "Other Terms"])
    components = _extract_components(soup, warnings)
    matrix = _parse_applicability_tables(soup, warnings)
    prereqs = _extract_prerequisites(soup)
    published = _extract_published_date(soup)

    if not symptoms:
        warnings.append("Symptom section not found")
    if not solution:
        warnings.append("Solution section not found")

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


def Path_stem_fallback(filename: str) -> str:
    import re
    m = re.search(r"\d{4,}", filename or "")
    return m.group() if m else "UNKNOWN"


def _extract_note_number(soup: BeautifulSoup, filename: str, warnings: list) -> str:
    # Try meta or title
    for pattern in [r"SAP Note\s+(\d+)", r"Note\s+#?\s*(\d+)", r"^\s*(\d{4,10})\s*$"]:
        for tag in soup.find_all(["h1", "h2", "title", "p"]):
            m = re.search(pattern, tag.get_text(" ", strip=True), re.IGNORECASE)
            if m:
                return m.group(1)
    # Fallback: filename digits
    return Path_stem_fallback(filename)


def _extract_title(soup: BeautifulSoup, warnings: list) -> str:
    for tag in soup.find_all(["h1", "h2"]):
        text = tag.get_text(" ", strip=True)
        if len(text) > 10 and not re.match(r"^\d+$", text):
            return text[:300]
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(" ", strip=True)[:300]
    warnings.append("Title not found")
    return ""


def _extract_severity(soup: BeautifulSoup, warnings: list) -> str:
    full_text = soup.get_text(" ", strip=True).lower()
    # Look for "Priority: High" style labels
    m = re.search(r"priority\s*[:\-]\s*(\w[\w\s]*)", full_text)
    if m:
        val = m.group(1).strip().split()[0].lower()
        for kw, mapped in _SEVERITY_KEYWORDS.items():
            if val in kw or kw in val:
                return mapped
    # Fallback: scan for bare keywords near "severity"
    m = re.search(r"severity\s*[:\-]?\s*(\w+)", full_text)
    if m:
        val = m.group(1).lower()
        for kw, mapped in _SEVERITY_KEYWORDS.items():
            if val == kw.split()[0]:
                return mapped
    warnings.append("Severity not found")
    return ""


def _extract_cvss(soup: BeautifulSoup, warnings: list) -> float:
    text = soup.get_text(" ")
    m = re.search(r"CVSS\s*(?:Score|Base Score|v\d)?\s*[:\-]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    warnings.append("CVSS score not found")
    return 0.0


def _extract_section(soup: BeautifulSoup, headings: List[str]) -> str:
    """Extract text content that follows a heading matching any of the given labels."""
    heading_pattern = re.compile("|".join(re.escape(h) for h in headings), re.IGNORECASE)

    # Try bold labels or heading tags
    for tag in soup.find_all(["h2", "h3", "h4", "b", "strong", "th", "td"]):
        text = tag.get_text(" ", strip=True)
        if heading_pattern.search(text):
            # Collect siblings until next heading
            parts = []
            for sibling in tag.find_next_siblings():
                sibling_tag = sibling.name if hasattr(sibling, "name") else ""
                if sibling_tag in ("h2", "h3", "h4") or (
                    sibling_tag in ("b", "strong")
                    and len(sibling.get_text(strip=True)) < 60
                ):
                    break
                parts.append(sibling.get_text(" ", strip=True))
                if len(" ".join(parts)) > 2000:
                    break
            result = " ".join(parts).strip()
            if len(result) > 20:
                return result

    # Fallback: find in raw text
    full_text = soup.get_text("\n")
    for heading in headings:
        m = re.search(rf"{re.escape(heading)}\s*\n+([\s\S]{{20,1000}}?)(?:\n{{2,}}|\Z)", full_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return ""


def _extract_components(soup: BeautifulSoup, warnings: list) -> List[str]:
    components: List[str] = []
    full_text = soup.get_text(" ")
    # Pattern: "Component: BC-XXX-YYY" or table cells
    for m in re.finditer(r"\b([A-Z]{2,6}-[A-Z0-9]{2,6}(?:-[A-Z0-9]{2,6})*)\b", full_text):
        comp = m.group(1)
        if comp not in components:
            components.append(comp)
    if not components:
        warnings.append("No components found")
    return components


def _parse_applicability_tables(soup: BeautifulSoup, warnings: list) -> List[NoteApplicabilityMatrixEntry]:
    entries: List[NoteApplicabilityMatrixEntry] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not any(h in headers for h in ("software component", "component", "release", "support package")):
            continue

        # Map column indices
        col = {}
        for i, h in enumerate(headers):
            if "component" in h:
                col["component"] = i
            elif "release" in h:
                col["release"] = i
            elif "from" in h or "sp from" in h:
                col["sp_from"] = i
            elif "to" in h or "sp to" in h:
                col["sp_to"] = i
            elif "patch" in h:
                col["patch"] = i

        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            entry = NoteApplicabilityMatrixEntry(
                component=cells[col.get("component", 0)],
                release=cells[col.get("release", 1)] if len(cells) > col.get("release", 1) else "",
                sp_from=cells[col.get("sp_from", 2)] if len(cells) > col.get("sp_from", 2) else "",
                sp_to=cells[col.get("sp_to", 3)] if len(cells) > col.get("sp_to", 3) else "",
                patch_level=cells[col.get("patch", 4)] if len(cells) > col.get("patch", 4) else "",
            )
            if entry.component:
                entries.append(entry)

    if not entries:
        warnings.append("Applicability matrix table not found")

    return entries


def _extract_prerequisites(soup: BeautifulSoup) -> List[NotePrerequisite]:
    prereqs: List[NotePrerequisite] = []
    section_text = _extract_section(soup, ["Prerequisite", "Prerequisites", "Required Notes"])
    if not section_text:
        return prereqs
    for m in re.finditer(r"\b(\d{4,10})\b", section_text):
        prereqs.append(NotePrerequisite(note_number=m.group(1)))
    return prereqs


def _extract_published_date(soup: BeautifulSoup) -> str:
    text = soup.get_text(" ")
    for pattern in [
        r"Published\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"Release\s+Date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1)
            # normalise DD.MM.YYYY → YYYY-MM-DD
            if re.match(r"\d{2}\.\d{2}\.\d{4}", raw):
                parts = raw.split(".")
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            return raw
    return ""
