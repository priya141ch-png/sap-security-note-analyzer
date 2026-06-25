from __future__ import annotations
import datetime
import logging
from typing import List

from core.domain_models import SapSecurityNote, ApplicabilityResult, RiskSummary

logger = logging.getLogger(__name__)

_SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.75, "medium": 0.4, "low": 0.15}
_ENV_FACTOR = {"PROD": 1.0, "QAS": 0.6, "DEV": 0.3}


def _days_since(date_str: str) -> float:
    if not date_str:
        return 0.0
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            pub = datetime.datetime.strptime(date_str.strip(), fmt).date()
            return max(0.0, (datetime.date.today() - pub).days)
        except ValueError:
            continue
    return 0.0


def _norm_cvss(cvss: float) -> float:
    return max(0.0, min(cvss, 10.0)) / 10.0


def compute_sid_risk_summaries(
    notes: List[SapSecurityNote],
    results: List[ApplicabilityResult],
    environment_map: dict[str, str] | None = None,
) -> List[RiskSummary]:
    """Compute risk KPIs per SID from applicable notes."""
    environment_map = environment_map or {}

    applicable_per_sid: dict[str, list[SapSecurityNote]] = {}
    note_by_number = {n.note_number: n for n in notes}

    for r in results:
        if r.status == "Applicable":
            applicable_per_sid.setdefault(r.sid, []).append(note_by_number[r.note_number])

    summaries: list[RiskSummary] = []
    for sid, applicable_notes in applicable_per_sid.items():
        env = environment_map.get(sid, "PROD")
        env_factor = _ENV_FACTOR.get(env.upper(), 1.0)

        rs = RiskSummary(sid=sid)
        score_total = 0.0
        age_total = 0.0

        for note in applicable_notes:
            sev = note.severity.lower()
            if sev == "critical":
                rs.critical_count += 1
            elif sev == "high":
                rs.high_count += 1
            elif sev == "medium":
                rs.medium_count += 1
            else:
                rs.low_count += 1

            sev_w = _SEVERITY_WEIGHT.get(sev, 0.2)
            cvss_w = _norm_cvss(note.cvss_score)
            days = _days_since(note.published_date)
            age_factor = min(days / 365.0, 1.0)
            age_total += days

            score_total += (sev_w * 0.4 + cvss_w * 0.4 + age_factor * 0.2) * env_factor

        total = len(applicable_notes) or 1
        rs.risk_score = round(min(score_total / total * 100, 100), 1)
        rs.exposure_score = round(
            (rs.critical_count * 4 + rs.high_count * 3 + rs.medium_count * 2 + rs.low_count) / total * 10, 1
        )
        rs.avg_patch_age_days = round(age_total / total, 0)
        summaries.append(rs)

    # Include SIDs with no applicable notes
    all_sids = {r.sid for r in results}
    covered = {s.sid for s in summaries}
    for sid in all_sids - covered:
        summaries.append(RiskSummary(sid=sid))

    return sorted(summaries, key=lambda s: s.risk_score, reverse=True)
