"""Unit tests for the applicability engine."""

import pytest
from core.domain_models import (
    NoteApplicabilityMatrixEntry,
    SapSecurityNote,
    SystemComponent,
    SystemInfo,
    Landscape,
)
from core.applicability_engine import evaluate_note_for_system, evaluate_note_for_landscape


def _make_system(sid="S4P", basis_release="756", sp="0003") -> SystemInfo:
    return SystemInfo(
        sid=sid,
        system_type="ABAP",
        sap_basis_release=basis_release,
        components=[
            SystemComponent(name="SAP_BASIS", release=basis_release, sp_level=sp),
            SystemComponent(name="SAP_ABA", release=basis_release, sp_level=sp),
        ],
    )


def _make_note(release="756", sp_from="0000", sp_to="0005") -> SapSecurityNote:
    return SapSecurityNote(
        note_number="3694242",
        title="Test",
        severity="Critical",
        cvss_score=9.1,
        components=["SAP_BASIS"],
        applicability_matrix=[
            NoteApplicabilityMatrixEntry(
                component="SAP_BASIS",
                release=release,
                sp_from=sp_from,
                sp_to=sp_to,
            )
        ],
    )


def test_applicable_within_range():
    system = _make_system(basis_release="756", sp="0003")
    note = _make_note(release="756", sp_from="0000", sp_to="0005")
    result = evaluate_note_for_system(note, system)
    assert result.status == "Applicable"
    assert result.confidence >= 0.8


def test_not_applicable_different_release():
    system = _make_system(basis_release="757", sp="0003")
    note = _make_note(release="756", sp_from="0000", sp_to="0005")
    result = evaluate_note_for_system(note, system)
    assert result.status == "Not Applicable"


def test_not_applicable_sp_above_range():
    system = _make_system(basis_release="756", sp="0010")
    note = _make_note(release="756", sp_from="0000", sp_to="0005")
    result = evaluate_note_for_system(note, system)
    assert result.status == "Not Applicable"


def test_component_not_in_system():
    system = SystemInfo(
        sid="S4P",
        system_type="ABAP",
        components=[SystemComponent(name="SAP_HR", release="756", sp_level="0003")],
    )
    note = _make_note()
    result = evaluate_note_for_system(note, system)
    assert result.status == "Not Applicable"


def test_no_matrix_triggers_manual_review():
    note = SapSecurityNote(
        note_number="9999999",
        title="No matrix",
        components=[],
        applicability_matrix=[],
    )
    system = _make_system()
    result = evaluate_note_for_system(note, system)
    assert result.status == "Needs Manual Review"


def test_landscape_evaluation():
    landscape = Landscape(systems=[_make_system("S4P"), _make_system("S4D", sp="0010")])
    note = _make_note()
    results = evaluate_note_for_landscape(note, landscape)
    assert len(results) == 2
    sids = {r.sid for r in results}
    assert "S4P" in sids
    assert "S4D" in sids
