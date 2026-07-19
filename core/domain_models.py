
"""
Domain models for SAP Security Note Analyzer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RfcProfile:
    name: str
    host: str
    sysnr: str
    client: str
    user: str
    password_enc: str
    lang: str = "EN"
    timeout: int = 30
    description: str = ""
    client_group: str = ""
    environment: str = ""
    created_at: str = ""
    last_tested: str = ""
    last_test_ok: bool = False


@dataclass
class NoteApplicabilityMatrixEntry:
    component: str
    release: str = ""        # affected release FROM (e.g. "750")
    release_to: str = ""     # affected release TO   (e.g. "758")
    sp_from: str = ""        # SP from (usually empty)
    sp_to: str = ""          # fix SP (e.g. "SAPK-75804INSAPBASIS")
    patch_level: str = ""
    entry_type: str = "validity"   # "validity" | "support_package"


@dataclass
class NotePrerequisite:
    note_number: str
    title: str = ""


@dataclass
class NoteMetadata:
    note_number: str
    title: str = ""
    severity: str = ""
    cvss_score: float = 0.0
    symptoms: str = ""
    solution: str = ""
    workaround: str = ""
    long_text_html: str = ""
    components: List[str] = field(default_factory=list)
    applicability_matrix: List[NoteApplicabilityMatrixEntry] = field(default_factory=list)
    prerequisites: List[NotePrerequisite] = field(default_factory=list)
    published_date: str = ""
    source: str = ""
    cached_at: str = ""
    parser_warnings: List[str] = field(default_factory=list)
    kernel_min: str = ""
    kernel_max: str = ""
    db_type: str = ""
    db_version_min: str = ""
    os_type: str = ""
    os_version_min: str = ""


@dataclass
class SapSecurityNote:
    note_number: str
    title: str = ""
    severity: str = ""
    cvss_score: float = 0.0
    symptoms: str = ""
    solution: str = ""
    workaround: str = ""
    long_text_html: str = ""
    components: List[str] = field(default_factory=list)
    applicability_matrix: List[NoteApplicabilityMatrixEntry] = field(default_factory=list)
    prerequisites: List[NotePrerequisite] = field(default_factory=list)
    published_date: str = ""
    parser_warnings: List[str] = field(default_factory=list)
    kernel_min: str = ""
    kernel_max: str = ""
    db_type: str = ""
    db_version_min: str = ""
    os_type: str = ""
    os_version_min: str = ""


@dataclass
class SystemComponent:
    name: str
    release: str = ""
    sp_level: str = ""
    patch_level: str = ""
    description: str = ""


@dataclass
class LiveSystemInfo:
    sid: str
    client: str
    host: str
    sap_release: str
    kernel_release: str = ""
    kernel_patch: str = ""
    db_system: str = ""
    db_version: str = ""
    os_version: str = ""
    components: List[SystemComponent] = field(default_factory=list)
    implemented_notes: List[str] = field(default_factory=list)
    collected_at: str = ""
    collection_warnings: List[str] = field(default_factory=list)


@dataclass
class ComponentEvidence:
    required_component: str
    component_found: bool
    installed_release: str = ""
    required_release: str = ""
    release_match: Optional[bool] = None


@dataclass
class SpEvidence:
    installed_sp: str = ""
    required_sp_from: str = ""
    required_sp_to: str = ""
    in_range: Optional[bool] = None


@dataclass
class ImplementationEvidence:
    note_in_cwbntcust: bool = False
    prstatus: str = ""
    already_implemented: bool = False


@dataclass
class VersionCheckResult:
    dimension: str
    required: str = ""
    installed: str = ""
    status: str = ""
    note: str = ""


@dataclass
class ApplicabilityEvidence:
    note_number: str
    system_sid: str
    client: str
    check_timestamp: str
    component: ComponentEvidence
    sp: SpEvidence
    implementation: ImplementationEvidence
    kernel_release: str = ""
    kernel_patch: str = ""
    db_version: str = ""
    os_version: str = ""
    version_checks: List[VersionCheckResult] = field(default_factory=list)
    decision: str = ""
    confidence: float = 0.0
    reason: str = ""
    recommended_action: str = ""


@dataclass
class LiveApplicabilityResult:
    note_number: str
    note_title: str
    note_severity: str
    note_cvss: float
    sid: str
    client: str
    host: str
    status: str
    confidence: float
    evidence: ApplicabilityEvidence
    recommended_action: str
    checked_at: str
    note_symptoms: str = ""
    note_solution: str = ""


@dataclass
class RiskSummary:
    sid: str
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    already_implemented: int = 0
    not_applicable: int = 0
    insufficient_data: int = 0
    risk_score: float = 0.0
    exposure_score: float = 0.0
    avg_patch_age_days: float = 0.0


@dataclass
class Landscape:
    systems: List["SystemInfo"] = field(default_factory=list)


@dataclass
class SystemInfo:
    sid: str
    system_type: str = ""
    sap_basis_release: str = ""
    sap_aba_release: str = ""
    kernel_release: str = ""
    kernel_patch_level: str = ""
    components: List[SystemComponent] = field(default_factory=list)
    environment: str = ""


@dataclass
class ApplicabilityReason:
    flag: str
    reason: str


@dataclass
class ApplicabilityResult:
    sid: str
    note_number: str
    status: str
    confidence: float
    reasons: List[ApplicabilityReason] = field(default_factory=list)
    recommended_action: str = ""
    evidence: str = ""


@dataclass
class EffortEstimate:
    note_number: str
    effort_score: int = 1
    rationale: str = ""
