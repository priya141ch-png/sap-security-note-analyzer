"""
Live applicability engine.
Combines live RFC system data + note metadata → structured decision with evidence.

Decision ladder:
  1. Already Implemented  — note found in CWBNTCUST with PRSTATUS=' '
  2. Not Applicable       — required component not installed, OR release/SP outside range
  3. Applicable           — component installed, release matches, SP in range
  4. Needs Manual Review  — component found but version data is ambiguous/missing
  5. Insufficient Data    — no note metadata to compare against
"""

from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import Optional

from core.domain_models import (
    ApplicabilityEvidence,
    ComponentEvidence,
    ImplementationEvidence,
    LiveApplicabilityResult,
    LiveSystemInfo,
    NoteMetadata,
    SpEvidence,
)

logger = logging.getLogger(__name__)

# Statuses
APPLICABLE         = "Applicable"
NOT_APPLICABLE     = "Not Applicable"
ALREADY_IMPLEMENTED = "Already Implemented"
NEEDS_REVIEW       = "Needs Manual Review"
INSUFFICIENT_DATA  = "Insufficient Data"


def _norm_release(r: str) -> int:
    if not r:
        return 0
    cleaned = re.sub(r"[^0-9]", "", r)
    if not cleaned:
        return 0
    val = int(cleaned)
    return val * 10 if val < 100 else val


def _norm_sp(sp: str) -> int:
    if not sp:
        return -1
    cleaned = re.sub(r"[^0-9]", "", sp)
    return int(cleaned) if cleaned else -1


def _normalize_comp(name: str) -> str:
    n = name.upper().strip()
    aliases = {"BASIS": "SAP_BASIS", "ABA": "SAP_ABA", "HR": "SAP_HR"}
    return aliases.get(n, n)


def _find_component(system: LiveSystemInfo, comp_name: str):
    target = _normalize_comp(comp_name)
    for c in system.components:
        if _normalize_comp(c.name) == target:
            return c
    # Fuzzy: prefix match
    for c in system.components:
        cn = _normalize_comp(c.name)
        if target in cn or cn in target:
            return c
    return None


def evaluate_live(
    system: LiveSystemInfo,
    note: NoteMetadata,
) -> LiveApplicabilityResult:
    """Main evaluation function — returns a fully populated LiveApplicabilityResult."""

    ts = datetime.now().isoformat(timespec="seconds")

    # ── 1. Already Implemented? ───────────────────────────────────────────────
    stripped_num = note.note_number.lstrip("0")
    if stripped_num in system.implemented_notes:
        evidence = _build_evidence(
            note, system, ts,
            comp_ev=ComponentEvidence(required_component="—", component_found=True),
            sp_ev=SpEvidence(),
            impl_ev=ImplementationEvidence(note_in_cwbntcust=True, prstatus=" ", already_implemented=True),
            decision=ALREADY_IMPLEMENTED,
            confidence=0.99,
            reason="Note found in CWBNTCUST with status 'implemented' (PRSTATUS=' ').",
        )
        return _result(note, system, ALREADY_IMPLEMENTED, 0.99, evidence,
                       "No action required — this note is already implemented in the system.")

    # ── 2. No note metadata → Insufficient Data ───────────────────────────────
    if not note.applicability_matrix and not note.components:
        evidence = _build_evidence(
            note, system, ts,
            comp_ev=ComponentEvidence(required_component="—", component_found=False),
            sp_ev=SpEvidence(),
            impl_ev=ImplementationEvidence(),
            decision=INSUFFICIENT_DATA,
            confidence=0.0,
            reason="No applicability matrix or component data found in note metadata.",
        )
        return _result(note, system, INSUFFICIENT_DATA, 0.0, evidence,
                       "Add note metadata (upload HTML/PDF or enter manually) to complete the check.")

    # ── 3. Check each matrix entry until we find a match ─────────────────────
    # Use applicability_matrix entries for detailed component + SP check
    entries = note.applicability_matrix or [
        type("E", (), {"component": c, "release": "", "sp_from": "", "sp_to": "", "patch_level": ""})()
        for c in note.components
    ]

    best_comp_ev = ComponentEvidence(required_component="—", component_found=False)
    best_sp_ev   = SpEvidence()
    flags: list[str] = []

    for entry in entries:
        sys_comp = _find_component(system, entry.component)
        comp_ev = ComponentEvidence(
            required_component=entry.component,
            component_found=sys_comp is not None,
            installed_release=sys_comp.release if sys_comp else "",
            required_release=entry.release,
        )
        best_comp_ev = comp_ev

        if not sys_comp:
            flags.append("COMP_NOT_FOUND")
            continue

        # Release match
        note_rel = _norm_release(entry.release)
        sys_rel  = _norm_release(sys_comp.release)
        if note_rel and sys_rel and sys_rel != note_rel:
            comp_ev.release_match = False
            flags.append("RELEASE_MISMATCH")
            continue
        comp_ev.release_match = True if (note_rel and sys_rel) else None

        # SP range
        sp_from = _norm_sp(entry.sp_from)
        sp_to   = _norm_sp(entry.sp_to)
        sys_sp  = _norm_sp(sys_comp.sp_level)

        sp_ev = SpEvidence(
            installed_sp=sys_comp.sp_level,
            required_sp_from=entry.sp_from,
            required_sp_to=entry.sp_to,
        )

        if sys_sp == -1 or (sp_from == -1 and sp_to == -1):
            sp_ev.in_range = None
            flags.append("SP_UNKNOWN")
            best_sp_ev = sp_ev
            continue

        in_range = True
        if sp_from != -1 and sys_sp < sp_from:
            in_range = False
        if sp_to != -1 and sys_sp > sp_to:
            in_range = False

        sp_ev.in_range = in_range
        best_sp_ev = sp_ev

        if in_range:
            flags.append("IN_RANGE")
        else:
            flags.append("OUT_OF_RANGE")

    impl_ev = ImplementationEvidence(
        note_in_cwbntcust=False,
        prstatus="",
        already_implemented=False,
    )

    # ── Decision ──────────────────────────────────────────────────────────────
    if all(f == "COMP_NOT_FOUND" for f in flags):
        status = NOT_APPLICABLE
        confidence = 0.95
        reason = (
            f"None of the required components ({', '.join(e.component for e in entries)}) "
            f"are installed on this system."
        )
        action = "No action required — system does not have the affected component."

    elif "IN_RANGE" in flags:
        status = APPLICABLE
        confidence = 0.92
        reason = (
            f"Component {best_comp_ev.required_component} is installed at release "
            f"{best_comp_ev.installed_release}, SP {best_sp_ev.installed_sp}, "
            f"which is within the affected range "
            f"[SP{best_sp_ev.required_sp_from}–SP{best_sp_ev.required_sp_to}]. "
            f"Note is NOT yet implemented."
        )
        action = (
            f"Apply SAP Note {note.note_number}. "
            + (f"Workaround: {note.workaround[:120]}" if note.workaround else "No workaround documented.")
        )

    elif all(f in ("OUT_OF_RANGE", "RELEASE_MISMATCH") for f in flags):
        status = NOT_APPLICABLE
        confidence = 0.90
        reason = (
            f"Installed version is outside the affected range. "
            f"System: {best_comp_ev.required_component} {best_comp_ev.installed_release} "
            f"SP{best_sp_ev.installed_sp}; "
            f"Note affects SP{best_sp_ev.required_sp_from}–SP{best_sp_ev.required_sp_to}."
        )
        action = "No action required — system is already patched beyond the affected range."

    elif "SP_UNKNOWN" in flags or "COMP_NOT_FOUND" in flags:
        status = NEEDS_REVIEW
        confidence = 0.5
        reason = "Incomplete version data — could not determine SP range match. Manual review required."
        action = "Manually verify component version and SP level using SAP transaction SM51 / SPAM."

    else:
        status = NEEDS_REVIEW
        confidence = 0.4
        reason = "Ambiguous result from component/SP comparison. Manual review recommended."
        action = "Review the component and support package level manually."

    evidence = _build_evidence(
        note, system, ts,
        comp_ev=best_comp_ev,
        sp_ev=best_sp_ev,
        impl_ev=impl_ev,
        decision=status,
        confidence=confidence,
        reason=reason,
    )
    return _result(note, system, status, confidence, evidence, action)


def _build_evidence(note, system, ts, comp_ev, sp_ev, impl_ev, decision, confidence, reason):
    return ApplicabilityEvidence(
        note_number=note.note_number,
        system_sid=system.sid,
        client=system.client,
        check_timestamp=ts,
        component=comp_ev,
        sp=sp_ev,
        implementation=impl_ev,
        kernel_release=system.kernel_release,
        kernel_patch=system.kernel_patch,
        decision=decision,
        confidence=confidence,
        reason=reason,
    )


def _result(note, system, status, confidence, evidence, action):
    return LiveApplicabilityResult(
        note_number=note.note_number,
        note_title=note.title,
        note_severity=note.severity,
        note_cvss=note.cvss_score,
        sid=system.sid,
        client=system.client,
        host=system.host,
        status=status,
        confidence=confidence,
        evidence=evidence,
        recommended_action=action,
        checked_at=evidence.check_timestamp,
    )
