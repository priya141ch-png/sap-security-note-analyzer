"""
Applicability engine — evaluates whether a SAP Security Note applies to a given system.

Decision tree:
  1. If note has no components → Needs Manual Review
  2. If no system component matches any note component → Not Applicable
  3. For each matching component, check release/SP ranges
  4. If any range check is UNKNOWN → Needs Manual Review
  5. If all matching ranges say NO → Not Applicable
  6. Otherwise → Applicable
"""

from __future__ import annotations
import re
import logging
from typing import List

from core.domain_models import (
    SapSecurityNote,
    SystemInfo,
    Landscape,
    ApplicabilityResult,
    ApplicabilityReason,
)

logger = logging.getLogger(__name__)

# Component aliases — map common abbreviations to canonical names
_COMPONENT_ALIASES: dict[str, str] = {
    "SAP_BASIS": "SAP BASIS",
    "BASIS": "SAP BASIS",
    "SAP BASIS": "SAP BASIS",
    "SAP_ABA": "SAP ABA",
    "ABA": "SAP ABA",
    "SAP_HR": "SAP HR",
    "HR": "SAP HR",
    "SAP_AP": "SAP AP",
    "SAP_BW": "SAP BW",
    "BW": "SAP BW",
}


def _normalize_component(name: str) -> str:
    name = name.strip().upper()
    return _COMPONENT_ALIASES.get(name, name)


def _normalize_release(release: str) -> int:
    """Convert release string like '754', '7.40' or '74' to a comparable integer."""
    if not release:
        return 0
    cleaned = re.sub(r"[^0-9]", "", release)
    if not cleaned:
        return 0
    val = int(cleaned)
    # Normalise short forms: 74 → 740, 75 → 750
    if val < 100:
        val *= 10
    return val


def _normalize_sp(sp: str) -> int:
    if not sp:
        return -1
    cleaned = re.sub(r"[^0-9]", "", sp)
    return int(cleaned) if cleaned else -1


def _flag_to_score(flag: str) -> float:
    return {"YES": 1.0, "NO": 0.0, "UNKNOWN": 0.5}.get(flag, 0.5)


def _component_match(note_component: str, system: SystemInfo) -> str:
    """Return YES/NO/UNKNOWN based on whether the note component exists on the system."""
    note_norm = _normalize_component(note_component)
    for sc in system.components:
        if _normalize_component(sc.name) == note_norm:
            return "YES"
    # Fuzzy: if note component is a prefix of any system component name
    for sc in system.components:
        sys_norm = _normalize_component(sc.name)
        if note_norm in sys_norm or sys_norm in note_norm:
            return "UNKNOWN"
    return "NO"


def _release_sp_match(entry, system: SystemInfo) -> tuple[str, str]:
    """
    Check if the note's applicability matrix entry covers this system.
    Returns (flag, reason_text).
    """
    entry_comp_norm = _normalize_component(entry.component)

    # Find the matching system component
    sys_comp = None
    for sc in system.components:
        if _normalize_component(sc.name) == entry_comp_norm:
            sys_comp = sc
            break
    if sys_comp is None:
        return "NO", f"Component {entry.component} not in system"

    # Release check
    note_rel = _normalize_release(entry.release)
    sys_rel = _normalize_release(sys_comp.release)

    if note_rel and sys_rel:
        if sys_rel != note_rel:
            return "NO", f"Release mismatch: system {sys_rel} vs note {note_rel}"
    elif note_rel or sys_rel:
        return "UNKNOWN", "Cannot compare releases — one side is missing"

    # SP range check
    sp_from = _normalize_sp(entry.sp_from)
    sp_to = _normalize_sp(entry.sp_to)
    sys_sp = _normalize_sp(sys_comp.sp_level)

    if sys_sp == -1 or (sp_from == -1 and sp_to == -1):
        return "UNKNOWN", "SP level information missing"

    in_range = True
    if sp_from != -1 and sys_sp < sp_from:
        in_range = False
    if sp_to != -1 and sys_sp > sp_to:
        in_range = False

    if in_range:
        return "YES", f"SP {sys_sp} is within [{sp_from}, {sp_to}]"
    return "NO", f"SP {sys_sp} is outside [{sp_from}, {sp_to}]"


def _recommended_action(status: str, note: SapSecurityNote) -> str:
    if status == "Applicable":
        return (
            f"Apply SAP Note {note.note_number}. "
            + (f"Workaround available: {note.workaround[:120]}..." if note.workaround else "No workaround documented.")
        )
    if status == "Not Applicable":
        return "No action required — system is outside the affected release/SP range."
    return "Manual review recommended — insufficient version data to determine applicability automatically."


def evaluate_note_for_system(note: SapSecurityNote, system: SystemInfo) -> ApplicabilityResult:
    reasons: List[ApplicabilityReason] = []

    if not note.components and not note.applicability_matrix:
        return ApplicabilityResult(
            sid=system.sid,
            note_number=note.note_number,
            status="Needs Manual Review",
            confidence=0.3,
            reasons=[ApplicabilityReason("UNKNOWN", "Note has no component or applicability data")],
            recommended_action=_recommended_action("Needs Manual Review", note),
            evidence=note.symptoms[:200] if note.symptoms else "",
        )

    # Step 1: component presence check
    comp_flags: list[str] = []
    for comp in note.components:
        flag = _component_match(comp, system)
        reasons.append(ApplicabilityReason(flag, f"Component '{comp}' → {flag}"))
        comp_flags.append(flag)

    if comp_flags and all(f == "NO" for f in comp_flags):
        return ApplicabilityResult(
            sid=system.sid,
            note_number=note.note_number,
            status="Not Applicable",
            confidence=0.95,
            reasons=reasons,
            recommended_action=_recommended_action("Not Applicable", note),
            evidence="",
        )

    # Step 2: release/SP range check from applicability matrix
    matrix_flags: list[str] = []
    for entry in note.applicability_matrix:
        flag, detail = _release_sp_match(entry, system)
        reasons.append(ApplicabilityReason(flag, detail))
        matrix_flags.append(flag)

    # Matrix flags are the authoritative version-range verdict.
    # Component flags only tell us if the component is present at all.
    if matrix_flags:
        if all(f == "NO" for f in matrix_flags):
            status = "Not Applicable"
            confidence = 0.95
        elif "UNKNOWN" in matrix_flags:
            status = "Needs Manual Review"
            confidence = 0.5
        else:
            status = "Applicable"
            confidence = 0.9
    else:
        # No matrix data — fall back to component presence
        if "UNKNOWN" in comp_flags:
            status = "Needs Manual Review"
            confidence = 0.5
        elif "YES" in comp_flags:
            status = "Applicable"
            confidence = 0.6   # Lower confidence — no version range to confirm
        else:
            status = "Not Applicable"
            confidence = 0.9

    return ApplicabilityResult(
        sid=system.sid,
        note_number=note.note_number,
        status=status,
        confidence=round(confidence, 2),
        reasons=reasons,
        recommended_action=_recommended_action(status, note),
        evidence=note.symptoms[:300] if note.symptoms else "",
    )


def evaluate_note_for_landscape(
    note: SapSecurityNote, landscape: Landscape
) -> List[ApplicabilityResult]:
    results = []
    for system in landscape.systems:
        try:
            results.append(evaluate_note_for_system(note, system))
        except Exception as exc:
            logger.warning("Error evaluating note %s for SID %s: %s", note.note_number, system.sid, exc)
            results.append(
                ApplicabilityResult(
                    sid=system.sid,
                    note_number=note.note_number,
                    status="Needs Manual Review",
                    confidence=0.0,
                    reasons=[ApplicabilityReason("UNKNOWN", f"Evaluation error: {exc}")],
                    recommended_action="Manual review required due to evaluation error.",
                )
            )
    return results
