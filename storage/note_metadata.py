"""
Local note metadata cache — workspace-namespaced.
Stores parsed note info (from uploaded HTML/PDF or manual entry) in
user_data/workspaces/{workspace_id}/notes/<note_number>.json

Each user's note cache is isolated to their own workspace.
"""

from __future__ import annotations
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.domain_models import NoteApplicabilityMatrixEntry, NoteMetadata, NotePrerequisite

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    try:
        from storage.user_store import workspace_dir
        return workspace_dir("notes")
    except Exception:
        p = Path("user_data/note_cache")
        p.mkdir(parents=True, exist_ok=True)
        return p


def _cache_path(note_number: str) -> Path:
    return _cache_dir() / f"{note_number.lstrip('0')}.json"


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get_note(note_number: str) -> Optional[NoteMetadata]:
    path = _cache_path(note_number)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return _dict_to_meta(d)
    except Exception as exc:
        logger.warning("Cannot load note cache %s: %s", path, exc)
        return None


def save_note(meta: NoteMetadata) -> None:
    meta.cached_at = datetime.now().isoformat(timespec="seconds")
    _cache_path(meta.note_number).write_text(
        json.dumps(asdict(meta), indent=2), encoding="utf-8"
    )
    logger.info("Note %s cached (source=%s)", meta.note_number, meta.source)


def list_cached_notes() -> List[NoteMetadata]:
    cd = _cache_dir()
    if not cd.exists():
        return []
    notes = []
    for p in sorted(cd.glob("*.json")):
        try:
            notes.append(_dict_to_meta(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return notes


def delete_note(note_number: str) -> None:
    _cache_path(note_number).unlink(missing_ok=True)


def note_from_sap_note(sap_note, source: str = "uploaded") -> NoteMetadata:
    """Convert a SapSecurityNote (from parser) into NoteMetadata for caching."""
    return NoteMetadata(
        note_number=sap_note.note_number,
        title=sap_note.title,
        severity=sap_note.severity,
        cvss_score=sap_note.cvss_score,
        symptoms=sap_note.symptoms,
        solution=sap_note.solution,
        workaround=sap_note.workaround,
        components=sap_note.components,
        applicability_matrix=sap_note.applicability_matrix,
        prerequisites=sap_note.prerequisites,
        published_date=sap_note.published_date,
        source=source,
        parser_warnings=sap_note.parser_warnings,
    )


def build_manual_metadata(
    note_number: str,
    title: str,
    severity: str,
    cvss: float,
    component: str,
    release: str,
    sp_from: str,
    sp_to: str,
) -> NoteMetadata:
    """Build a NoteMetadata from manually entered values."""
    return NoteMetadata(
        note_number=note_number,
        title=title,
        severity=severity,
        cvss_score=cvss,
        components=[component] if component else [],
        applicability_matrix=[
            NoteApplicabilityMatrixEntry(
                component=component,
                release=release,
                sp_from=sp_from,
                sp_to=sp_to,
            )
        ] if component else [],
        source="manual",
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _dict_to_meta(d: dict) -> NoteMetadata:
    d["applicability_matrix"] = [
        NoteApplicabilityMatrixEntry(**e) for e in d.get("applicability_matrix", [])
    ]
    d["prerequisites"] = [NotePrerequisite(**p) for p in d.get("prerequisites", [])]
    return NoteMetadata(**{k: v for k, v in d.items() if k in NoteMetadata.__dataclass_fields__})
