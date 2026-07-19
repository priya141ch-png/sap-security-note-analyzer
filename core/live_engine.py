
"""
Live applicability engine.

Decision ladder:
  1. Already Implemented  — note in CWBNTCUST
  2. Not Applicable       — component absent OR release outside affected range
                            OR system beyond fix SP
  3. Applicable           — component+release in range, not yet fixed
  4. Needs Manual Review  — version data ambiguous / kernel-DB-OS match unclear
  5. Insufficient Data    — no note metadata
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple

from core.domain_models import (
    ApplicabilityEvidence, ComponentEvidence, ImplementationEvidence,
    LiveApplicabilityResult, LiveSystemInfo, NoteMetadata,
    SpEvidence, VersionCheckResult,
)

logger = logging.getLogger(__name__)

APPLICABLE          = "Applicable"
NOT_APPLICABLE      = "Not Applicable"
ALREADY_IMPLEMENTED = "Already Implemented"
NEEDS_REVIEW        = "Needs Manual Review"
INSUFFICIENT_DATA   = "Insufficient Data"


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm_release(r: str) -> int:
    """Normalise a release string to a comparable integer (e.g. '752' -> 752)."""
    if not r:
        return 0
    cleaned = re.sub(r"[^0-9]", "", r)
    if not cleaned:
        return 0
    val = int(cleaned)
    # 3-digit releases (750) stay as-is; 2-digit (75) → *10; 1-digit → *100
    return val


def _parse_sp_seq(sp_str: str) -> int:
    """
    Extract SP sequence number.
    SAPK-75804INSAPBASIS -> 4  (5th+6th digit of the block after SAPK-)
    '0004' -> 4
    """
    if not sp_str:
        return -1
    m = re.match(r"SAPK-\d{3}(\d{2})\w+", sp_str, re.I)
    if m:
        return int(m.group(1))
    cleaned = re.sub(r"[^0-9]", "", sp_str)
    return int(cleaned) if cleaned else -1


def _norm_comp(name: str) -> str:
    n = name.upper().strip()
    return {"BASIS": "SAP_BASIS", "ABA": "SAP_ABA", "HR": "SAP_HR"}.get(n, n)


def _find_component(system: LiveSystemInfo, comp_name: str):
    target = _norm_comp(comp_name)
    for c in system.components:
        if _norm_comp(c.name) == target:
            return c
    for c in system.components:
        cn = _norm_comp(c.name)
        if target in cn or cn in target:
            return c
    return None


def _version_tuple(v: str) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def _check_kernel(note: NoteMetadata, system: LiveSystemInfo) -> Optional[VersionCheckResult]:
    if not note.kernel_min:
        return None
    installed = system.kernel_patch or system.kernel_release or ""
    if not installed:
        return VersionCheckResult(
            dimension="kernel",
            required=f">= {note.kernel_min}",
            installed="unknown",
            status="unknown",
            note="Kernel version not collected — check manually via SM51 / disp+work -V",
        )
    req   = _version_tuple(note.kernel_min)
    inst  = _version_tuple(installed)
    ok    = inst >= req
    return VersionCheckResult(
        dimension="kernel",
        required=f">= {note.kernel_min}",
        installed=installed,
        status="ok" if ok else "affected",
        note="" if ok else f"Kernel {installed} is below required {note.kernel_min}",
    )


def _check_db(note: NoteMetadata, system: LiveSystemInfo) -> Optional[VersionCheckResult]:
    if not note.db_type:
        return None
    installed_type = (system.db_system or "").upper()
    installed_ver  = system.db_version or ""
    if note.db_type.upper() not in installed_type and installed_type not in note.db_type.upper():
        return VersionCheckResult(
            dimension="db",
            required=f"{note.db_type} >= {note.db_version_min}",
            installed=f"{system.db_system} {installed_ver}".strip(),
            status="ok",
            note=f"Note targets {note.db_type}; system uses {system.db_system} — not affected",
        )
    if not installed_ver or not note.db_version_min:
        return VersionCheckResult(
            dimension="db",
            required=f"{note.db_type} >= {note.db_version_min or '?'}",
            installed=f"{system.db_system} {installed_ver}".strip(),
            status="unknown",
            note="DB version not collected — check manually",
        )
    req  = _version_tuple(note.db_version_min)
    inst = _version_tuple(installed_ver)
    ok   = inst >= req
    return VersionCheckResult(
        dimension="db",
        required=f"{note.db_type} >= {note.db_version_min}",
        installed=f"{system.db_system} {installed_ver}".strip(),
        status="ok" if ok else "affected",
        note="" if ok else f"DB version {installed_ver} is below required {note.db_version_min}",
    )


def _check_os(note: NoteMetadata, system: LiveSystemInfo) -> Optional[VersionCheckResult]:
    if not note.os_type:
        return None
    installed = system.os_version or ""
    if not installed:
        return VersionCheckResult(
            dimension="os",
            required=f"{note.os_type} >= {note.os_version_min}",
            installed="unknown",
            status="unknown",
            note="OS version not collected — check manually",
        )
    if note.os_type.lower() not in installed.lower():
        return VersionCheckResult(
            dimension="os",
            required=f"{note.os_type} >= {note.os_version_min}",
            installed=installed,
            status="ok",
            note=f"Note targets {note.os_type}; system OS is {installed} — not affected",
        )
    req  = _version_tuple(note.os_version_min)
    inst = _version_tuple(installed)
    ok   = inst >= req
    return VersionCheckResult(
        dimension="os",
        required=f"{note.os_type} >= {note.os_version_min}",
        installed=installed,
        status="ok" if ok else "affected",
        note="" if ok else f"OS {installed} is below required {note.os_version_min}",
    )


# ── main evaluation ───────────────────────────────────────────────────────────

def evaluate_live(system: LiveSystemInfo, note: NoteMetadata) -> LiveApplicabilityResult:
    ts = datetime.now().isoformat(timespec="seconds")

    # 1. Already Implemented?
    stripped_num = note.note_number.lstrip("0")
    if stripped_num in system.implemented_notes:
        ev = _build_ev(note, system, ts,
                       ComponentEvidence(required_component="—", component_found=True),
                       SpEvidence(),
                       ImplementationEvidence(note_in_cwbntcust=True, prstatus=" ", already_implemented=True),
                       [], ALREADY_IMPLEMENTED, 0.99,
                       "Note found in CWBNTCUST with status implemented.")
        return _result(note, system, ALREADY_IMPLEMENTED, 0.99, ev,
                       "No action required — this note is already implemented.")

    # 2. No metadata
    if not note.applicability_matrix and not note.components:
        ev = _build_ev(note, system, ts,
                       ComponentEvidence(required_component="—", component_found=False),
                       SpEvidence(), ImplementationEvidence(), [],
                       INSUFFICIENT_DATA, 0.0, "No applicability data in note metadata.")
        return _result(note, system, INSUFFICIENT_DATA, 0.0, ev,
                       "Upload note PDF/HTML or download via S-user to complete the check.")

    # 3. Validity-range check (release range matching — the core fix)
    validity_entries = [e for e in note.applicability_matrix if e.entry_type == "validity"]
    sp_entries       = {e.component: e for e in note.applicability_matrix
                        if e.entry_type == "support_package"}

    # Collect version checks (kernel / DB / OS)
    ver_checks: List[VersionCheckResult] = []
    for chk in [_check_kernel(note, system), _check_db(note, system), _check_os(note, system)]:
        if chk:
            ver_checks.append(chk)

    best_comp_ev = ComponentEvidence(required_component="—", component_found=False)
    best_sp_ev   = SpEvidence()
    flags: List[str] = []

    for entry in (validity_entries or []):
        sys_comp = _find_component(system, entry.component)
        comp_ev  = ComponentEvidence(
            required_component=entry.component,
            component_found=sys_comp is not None,
            installed_release=sys_comp.release if sys_comp else "",
            required_release=f"{entry.release}–{entry.release_to}" if entry.release_to else entry.release,
        )
        best_comp_ev = comp_ev

        if not sys_comp:
            flags.append("COMP_NOT_FOUND")
            continue

        rel_from = _norm_release(entry.release)
        rel_to   = _norm_release(entry.release_to or entry.release)
        sys_rel  = _norm_release(sys_comp.release)

        if sys_rel == 0:
            flags.append("RELEASE_UNKNOWN")
            continue

        # Is system release within [rel_from, rel_to]?
        if sys_rel < rel_from:
            comp_ev.release_match = False
            flags.append("BELOW_RANGE")
            continue

        if rel_to and sys_rel > rel_to:
            comp_ev.release_match = False
            flags.append("ABOVE_RANGE")
            continue

        comp_ev.release_match = True

        # Check if there's a fix SP for this specific release
        fix_entry = sp_entries.get(entry.component)
        if fix_entry and _norm_release(fix_entry.release) == sys_rel:
            fix_sp_seq  = _parse_sp_seq(fix_entry.sp_to)
            sys_sp_seq  = _parse_sp_seq(sys_comp.sp_level)
            sp_ev = SpEvidence(
                installed_sp=sys_comp.sp_level,
                required_sp_from="",
                required_sp_to=fix_entry.sp_to,
            )
            best_sp_ev = sp_ev
            if fix_sp_seq != -1 and sys_sp_seq != -1:
                if sys_sp_seq >= fix_sp_seq:
                    sp_ev.in_range = False   # already has the fix SP → not applicable
                    flags.append("FIX_SP_APPLIED")
                else:
                    sp_ev.in_range = True
                    flags.append("IN_RANGE")
            else:
                sp_ev.in_range = None
                flags.append("IN_RANGE")   # release matched, SP unknown → assume applicable
        else:
            # No fix SP listed for this release → whole release is affected
            best_sp_ev = SpEvidence(installed_sp=sys_comp.sp_level)
            flags.append("IN_RANGE")

    impl_ev = ImplementationEvidence()

    # Decision
    if not flags or all(f == "COMP_NOT_FOUND" for f in flags):
        status     = NOT_APPLICABLE
        confidence = 0.95
        reason     = (f"None of the required components are installed on this system "
                      f"({', '.join(e.component for e in validity_entries)}).")
        action     = "No action required — system does not have the affected component."

    elif all(f == "ABOVE_RANGE" for f in flags):
        status     = NOT_APPLICABLE
        confidence = 0.92
        reason     = (f"System release {best_comp_ev.installed_release} is above the "
                      f"affected range ({best_comp_ev.required_release}). Already patched beyond affected versions.")
        action     = "No action required — system is already beyond the affected release range."

    elif all(f == "BELOW_RANGE" for f in flags):
        status     = NOT_APPLICABLE
        confidence = 0.90
        reason     = (f"System release {best_comp_ev.installed_release} is below the "
                      f"affected range ({best_comp_ev.required_release}). Different major version.")
        action     = "No action required — system is on an older release not covered by this note."

    elif "FIX_SP_APPLIED" in flags and "IN_RANGE" not in flags:
        status     = NOT_APPLICABLE
        confidence = 0.93
        reason     = (f"System has the fix SP already applied "
                      f"(installed SP {best_sp_ev.installed_sp} >= fix SP {best_sp_ev.required_sp_to}).")
        action     = "No action required — fix support package already installed."

    elif "IN_RANGE" in flags:
        # Check if any version dimension is affected
        ver_affected = [v for v in ver_checks if v.status == "affected"]
        ver_unknown  = [v for v in ver_checks if v.status == "unknown"]

        if ver_checks and not ver_affected and not ver_unknown:
            status = NOT_APPLICABLE
            confidence = 0.85
            reason = ("Component release is in affected range, but kernel/DB/OS version checks "
                      "show system is not vulnerable.")
            action = "No action required — version checks indicate system is not affected."
        elif ver_unknown:
            status     = NEEDS_REVIEW
            confidence = 0.6
            dims       = ", ".join(v.dimension for v in ver_unknown)
            reason     = (f"Component {best_comp_ev.required_component} release "
                          f"{best_comp_ev.installed_release} is in affected range "
                          f"({best_comp_ev.required_release}). "
                          f"Could not verify: {dims}.")
            action     = ("Manually verify " + dims + " version requirements from the note solution. "
                          + (note.solution[:200] if note.solution else ""))
        else:
            status     = APPLICABLE
            confidence = 0.92
            sp_info    = (f", SP {best_sp_ev.installed_sp}" if best_sp_ev.installed_sp else "")
            fix_sp     = (f"; fix SP: {best_sp_ev.required_sp_to}" if best_sp_ev.required_sp_to else
                          " (no fix SP listed for this release — apply correction instructions)")
            reason     = (f"Component {best_comp_ev.required_component} release "
                          f"{best_comp_ev.installed_release}{sp_info} is within the affected range "
                          f"({best_comp_ev.required_release}){fix_sp}.")
            action     = (f"Apply SAP Note {note.note_number}. "
                          + (note.solution[:300] if note.solution else "See note for instructions."))

    elif "RELEASE_UNKNOWN" in flags:
        status     = NEEDS_REVIEW
        confidence = 0.4
        reason     = "Could not determine system release for this component."
        action     = "Verify component release and SP manually via transaction SPAM or SE38/RSPARAM."

    else:
        status     = NEEDS_REVIEW
        confidence = 0.4
        reason     = "Ambiguous version comparison — manual review recommended."
        action     = "Check component version and SP manually."

    ev = _build_ev(note, system, ts, best_comp_ev, best_sp_ev, impl_ev,
                   ver_checks, status, confidence, reason)
    return _result(note, system, status, confidence, ev, action)


def _build_ev(note, system, ts, comp_ev, sp_ev, impl_ev, ver_checks, decision, confidence, reason):
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
        db_version=getattr(system, "db_version", ""),
        os_version=getattr(system, "os_version", ""),
        version_checks=ver_checks,
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
        note_symptoms=getattr(note, "symptoms", ""),
        note_solution=getattr(note, "solution", ""),
    )
