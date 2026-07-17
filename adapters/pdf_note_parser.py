"""
Parses SAP Security Notes from PDF files.
Uses pdfplumber as primary parser with PyPDF2 as fallback.
"""

from __future__ import annotations
import io
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from core.domain_models import (
    NoteApplicabilityMatrixEntry,
    NotePrerequisite,
    SapSecurityNote,
)

logger = logging.getLogger(__name__)


def _extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        logger.debug("pdfplumber failed: %s", exc)
        return ""


def _extract_text_pypdf2(pdf_bytes: bytes) -> str:
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        logger.debug("PyPDF2 failed: %s", exc)
        return ""


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text with pdfplumber, fall back to PyPDF2."""
    text = _extract_text_pdfplumber(pdf_bytes)
    if len(text.strip()) < 100:
        text = _extract_text_pypdf2(pdf_bytes)
    return text


def parse_note_pdf(pdf_bytes: bytes, filename: str = "") -> Optional[SapSecurityNote]:
    """Parse an SAP Security Note PDF. Returns None if text extraction fails entirely."""
    warnings: List[str] = []
    text = extract_text_from_pdf_bytes(pdf_bytes)

    if len(text.strip()) < 50:
        logger.warning("Could not extract text from PDF: %s", filename)
        return None

    note_number = _extract_note_number(text, filename, warnings)
    title = _extract_title(text, warnings)
    severity = _extract_severity(text, warnings)
    cvss = _extract_cvss(text, warnings)
    symptoms = _find_block(text, ["Symptom", "Symptoms", "Problem"], warnings)
    solution = _find_block(text, ["Solution", "Cause and Solution"], warnings)
    workaround = _find_block(text, ["Workaround"], warnings)
    components = _extract_components(text, warnings)
    matrix = _parse_software_components_table(text, warnings)
    prereqs = _extract_prerequisites(text)
    published = _extract_published_date(text)

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


def _extract_note_number(text: str, filename: str, warnings: list) -> str:
    for pattern in [r"SAP Note\s+(\d+)", r"Note\s+#?\s*(\d+)", r"^\s*(\d{7,10})\s*$"]:
        m = re.search(pattern, text[:500], re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1)
    # filename fallback
    m = re.search(r"\d{4,}", filename or "")
    if m:
        return m.group()
    warnings.append("Note number not found in PDF")
    return "UNKNOWN"


def _extract_title(text: str, warnings: list) -> str:
    # Usually first meaningful line
    for line in text.split("\n")[:20]:
        line = line.strip()
        if len(line) > 20 and not re.match(r"^\d+$", line) and "SAP Note" not in line[:10]:
            return line[:300]
    warnings.append("Title not found in PDF")
    return ""


def _extract_severity(text: str, warnings: list) -> str:
    m = re.search(r"(?:Priority|Severity)\s*[:\-]?\s*(Hot News|Critical|High|Medium|Low)", text[:1000], re.IGNORECASE)
    if m:
        val = m.group(1).lower()
        if "hot" in val or "critical" in val:
            return "Critical"
        return val.capitalize()
    warnings.append("Severity not found in PDF")
    return ""


def _extract_cvss(text: str, warnings: list) -> float:
    m = re.search(r"CVSS\s*(?:Score|Base Score|v\d)?\s*[:\-]?\s*(\d+(?:\.\d+)?)", text[:2000], re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    warnings.append("CVSS score not found in PDF")
    return 0.0


def _find_block(text: str, headings: List[str], warnings: list) -> str:
    pattern = re.compile(
        r"(?:" + "|".join(re.escape(h) for h in headings) + r")\s*\n([\s\S]{20,2000}?)(?=\n[A-Z][^\n]{0,60}\n|\Z)",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if m:
        return m.group(1).strip()
    warnings.append(f"Section '{headings[0]}' not found in PDF")
    return ""


def _extract_components(text: str, warnings: list) -> List[str]:
    components: List[str] = []
    for m in re.finditer(r"\b([A-Z]{2,6}-[A-Z0-9]{2,6}(?:-[A-Z0-9]{2,6})*)\b", text):
        comp = m.group(1)
        if comp not in components:
            components.append(comp)
    if not components:
        warnings.append("No components found in PDF")
    return components


def _parse_software_components_table(text: str, warnings: list) -> List[NoteApplicabilityMatrixEntry]:
    """Extract applicability matrix from Software Components section.

    Handles all common SAP note PDF formats:
      SAP_BASIS  752   0000  0025   (zero-padded SP numbers)
      SAP_BASIS  752   SP00  SP25   (SP-prefixed)
      BC-UPG-NA  752   0     15     (hyphenated component, short SP)
      SAP_BASIS  7.52  SP00  SP25   (dot-separated release)
    """
    entries: List[NoteApplicabilityMatrixEntry] = []

    # Locate the Software Components block; stop at the next major section
    m = re.search(
        r"Software Components?[^\n]{0,80}\n"
        r"([\s\S]{0,4000}?)"
        r"(?=\n(?:Correction Instructions?|Prerequisites?|Support Package|"
        r"Available Language|Manual Activities|Note Assistant)|\Z)",
        text,
        re.IGNORECASE,
    )
    if not m:
        warnings.append("Software Components table not found in PDF")
        return entries

    block = m.group(1)
    logger.debug("SW Components block (first 600):\n%s", block[:600])

    # Component: uppercase letter followed by letters/digits/underscores/hyphens
    # Examples: SAP_BASIS, BC-UPG-NA, S4CORE, SAPSOL
    _comp = r"([A-Z][A-Z0-9_\-]{2,30})"
    # Release: 2-4 digits, optionally dot-separated (752, 7.52, 2023)
    _rel = r"(\d{1,4}(?:\.\d{1,2})?)"
    # SP level: optional "SP" prefix + digits, plain digits, or "latest"/"-"/"all"
    _sp = r"(SP\s*\d{1,4}|\d{1,4}|latest|all|-)"

    row_re = re.compile(
        _comp + r"\s+" + _rel + r"\s+" + _sp + r"\s+" + _sp,
        re.MULTILINE | re.IGNORECASE,
    )
    header_words = {
        "component", "release", "from", "to", "level", "software",
        "support", "package", "version", "type", "note", "sp",
    }

    def _norm_sp(v: str) -> str:
        v = re.sub(r"(?i)^SP\s*", "", v).lstrip("0") or "0"
        return v

    for row_m in row_re.finditer(block):
        comp, release, sp_from, sp_to = (row_m.group(i) for i in range(1, 5))
        # Skip table header rows
        if comp.lower() in header_words or release.lower() in header_words:
            continue
        entries.append(NoteApplicabilityMatrixEntry(
            component=comp,
            release=release.replace(".", ""),   # 7.52 → 752
            sp_from=_norm_sp(sp_from),
            sp_to=_norm_sp(sp_to),
        ))

    if not entries:
        warnings.append("Could not parse rows from Software Components table in PDF")

    return entries


def _extract_prerequisites(text: str) -> List[NotePrerequisite]:
    prereqs: List[NotePrerequisite] = []
    m = re.search(r"(?:Prerequisite|Required Note)[s]?\s*\n([\s\S]{0,500}?)(?=\n[A-Z]|\Z)", text, re.IGNORECASE)
    if not m:
        return prereqs
    for num_m in re.finditer(r"\b(\d{4,10})\b", m.group(1)):
        prereqs.append(NotePrerequisite(note_number=num_m.group(1)))
    return prereqs


def _extract_published_date(text: str) -> str:
    for pattern in [
        r"Published\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"Release\s+Date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{4})",
    ]:
        m = re.search(pattern, text[:2000], re.IGNORECASE)
        if m:
            raw = m.group(1)
            if re.match(r"\d{2}\.\d{2}\.\d{4}", raw):
                parts = raw.split(".")
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            return raw
    return ""
