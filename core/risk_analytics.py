from __future__ import annotations
from typing import List

from core.domain_models import SapSecurityNote, ApplicabilityResult, EffortEstimate


def summarize_risk_per_sid(
    notes: List[SapSecurityNote], results: List[ApplicabilityResult]
) -> dict[str, dict]:
    note_map = {n.note_number: n for n in notes}
    summary: dict[str, dict] = {}
    for r in results:
        if r.status != "Applicable":
            continue
        note = note_map.get(r.note_number)
        if not note:
            continue
        sev = note.severity.lower()
        entry = summary.setdefault(r.sid, {"critical": 0, "high": 0, "medium": 0, "low": 0})
        if sev in entry:
            entry[sev] += 1
        else:
            entry["low"] += 1
    return summary


def estimate_effort_for_note(note: SapSecurityNote) -> EffortEstimate:
    score = 1
    rationale_parts = []
    sev = note.severity.lower()
    if sev == "critical":
        score += 2
        rationale_parts.append("critical severity (+2)")
    elif sev == "high":
        score += 1
        rationale_parts.append("high severity (+1)")

    if len(note.applicability_matrix) > 5:
        score += 1
        rationale_parts.append("complex applicability matrix (+1)")

    if note.prerequisites:
        score += 1
        rationale_parts.append(f"{len(note.prerequisites)} prerequisites (+1)")

    if len(note.solution) > 500:
        score += 1
        rationale_parts.append("detailed solution text (+1)")

    score = min(score, 5)
    return EffortEstimate(
        note_number=note.note_number,
        effort_score=score,
        rationale="; ".join(rationale_parts) or "standard",
    )


def build_patch_planner(
    notes: List[SapSecurityNote], results: List[ApplicabilityResult]
) -> List[dict]:
    _SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    note_map = {n.note_number: n for n in notes}
    effort_map = {n.note_number: estimate_effort_for_note(n) for n in notes}

    rows = []
    for r in results:
        if r.status != "Applicable":
            continue
        note = note_map.get(r.note_number)
        if not note:
            continue
        effort = effort_map[r.note_number]
        rows.append(
            {
                "sid": r.sid,
                "note_number": r.note_number,
                "title": note.title,
                "severity": note.severity,
                "effort_score": effort.effort_score,
                "effort_rationale": effort.rationale,
                "sev_order": _SEV_ORDER.get(note.severity.lower(), 9),
            }
        )

    rows.sort(key=lambda x: (x["sev_order"], x["effort_score"], x["sid"]))
    return rows
