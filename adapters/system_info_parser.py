"""
Parses SAP system landscape information from XML exports.
Supports multiple XML schemas produced by SAP maintenance tools.
"""

from __future__ import annotations
import logging
import re
import zipfile
import io
from pathlib import Path
from typing import List, Optional

from lxml import etree

from core.domain_models import Landscape, SystemComponent, SystemInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe ZIP extraction (fixes Zip Slip vulnerability)
# ---------------------------------------------------------------------------

def safe_extract_zip(zip_bytes_or_path, target_dir: Path) -> Path:
    """Extract a ZIP, rejecting any entry that would escape target_dir."""
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(zip_bytes_or_path, (str, Path)):
        ctx = zipfile.ZipFile(zip_bytes_or_path, "r")
    else:
        ctx = zipfile.ZipFile(io.BytesIO(zip_bytes_or_path), "r")

    with ctx as zf:
        for member in zf.infolist():
            member_path = (target_dir / member.filename).resolve()
            if not str(member_path).startswith(str(target_dir)):
                raise ValueError(f"Unsafe ZIP path detected and rejected: {member.filename!r}")
        zf.extractall(target_dir)

    return target_dir


# ---------------------------------------------------------------------------
# Helpers — lxml namespace-agnostic element search
# ---------------------------------------------------------------------------

def _localname(element) -> str:
    """Return the local tag name, stripping any namespace."""
    if element is None:
        return ""
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag or ""


def _find_by_localname(parent, *localnames: str):
    """Find the first descendant whose local tag name matches any of localnames."""
    for el in parent.iter():
        if _localname(el) in localnames:
            return el
    return None


def _findall_by_localname(parent, *localnames: str):
    """Return all descendants whose local tag name matches any of localnames."""
    return [el for el in parent.iter() if _localname(el) in localnames]


def _text(el) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


# ---------------------------------------------------------------------------
# XML parsers
# ---------------------------------------------------------------------------

def parse_system_info_xml(xml_bytes: bytes, sid_hint: str = "") -> Optional[SystemInfo]:
    """Parse a single SAP system XML export into a SystemInfo object."""
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        logger.warning("XML parse error for SID=%s: %s", sid_hint, exc)
        return None

    root_local = _localname(root)
    if root_local in ("stack-xml", "sp-stacks", "Stack"):
        return _parse_sp_stacks(root, sid_hint)
    return _parse_generic(root, sid_hint)


def _parse_sp_stacks(root, sid_hint: str) -> Optional[SystemInfo]:
    sid_el = _find_by_localname(root, "system-id", "SystemID")
    sid = _text(sid_el) or sid_hint or "UNKNOWN"

    sys_type_el = _find_by_localname(root, "system-type", "SystemType")
    sys_type = _text(sys_type_el)

    components: List[SystemComponent] = []
    basis_release = aba_release = kernel_release = kernel_patch = ""

    for entry in _findall_by_localname(root, "software-component-entry", "SoftwareComponent", "Component"):
        comp_name = _text(_find_by_localname(entry, "name", "Name", "component-name"))
        comp_rel = _text(_find_by_localname(entry, "release", "Release", "sp-stack-name"))
        comp_sp = _text(_find_by_localname(entry, "sp-level", "SpLevel", "support-package-level"))
        comp_patch = _text(_find_by_localname(entry, "patch-level", "PatchLevel"))

        if not comp_name:
            continue

        upper = comp_name.upper()
        if upper in ("SAP_BASIS", "BASIS"):
            basis_release = comp_rel
        if upper in ("SAP_ABA", "ABA"):
            aba_release = comp_rel
        if "SAPEXE" in upper:
            kernel_release = comp_rel
            kernel_patch = comp_patch

        components.append(SystemComponent(
            name=comp_name, release=comp_rel, sp_level=comp_sp, patch_level=comp_patch,
        ))

    return SystemInfo(
        sid=sid, system_type=sys_type, sap_basis_release=basis_release,
        sap_aba_release=aba_release, kernel_release=kernel_release,
        kernel_patch_level=kernel_patch, components=components,
    )


def _parse_generic(root, sid_hint: str) -> Optional[SystemInfo]:
    sid_el = _find_by_localname(root, "SystemID", "SID", "sid")
    sid = _text(sid_el) or sid_hint or "UNKNOWN"

    sys_type_el = _find_by_localname(root, "SystemType", "Type")
    sys_type = _text(sys_type_el)

    components: List[SystemComponent] = []
    basis_release = aba_release = kernel_release = kernel_patch = ""

    for entry in _findall_by_localname(root, "SoftwareComponent", "Component", "software-component"):
        comp_name = _text(_find_by_localname(entry, "Name", "name", "ComponentName"))
        comp_rel = _text(_find_by_localname(entry, "Release", "release", "Version"))
        comp_sp = _text(_find_by_localname(entry, "SpLevel", "sp-level", "SupportPackage"))
        comp_patch = _text(_find_by_localname(entry, "PatchLevel", "patch-level"))

        if not comp_name:
            continue

        upper = comp_name.upper()
        if upper in ("SAP_BASIS", "BASIS"):
            basis_release = comp_rel
        if upper in ("SAP_ABA", "ABA"):
            aba_release = comp_rel
        if "SAPEXE" in upper or "KERNEL" in upper:
            kernel_release = comp_rel
            kernel_patch = comp_patch

        components.append(SystemComponent(
            name=comp_name, release=comp_rel, sp_level=comp_sp, patch_level=comp_patch,
        ))

    if not components:
        logger.warning("No components found for SID=%s — check XML format", sid)

    return SystemInfo(
        sid=sid, system_type=sys_type, sap_basis_release=basis_release,
        sap_aba_release=aba_release, kernel_release=kernel_release,
        kernel_patch_level=kernel_patch, components=components,
    )


# ---------------------------------------------------------------------------
# Landscape loaders
# ---------------------------------------------------------------------------

def load_landscape_from_files(xml_files: list[tuple[str, bytes]]) -> Landscape:
    """Load landscape from a list of (filename, xml_bytes) tuples."""
    systems: List[SystemInfo] = []
    seen_sids: set[str] = set()

    for filename, xml_bytes in xml_files:
        sid_hint = Path(filename).stem.upper()
        info = parse_system_info_xml(xml_bytes, sid_hint)
        if info is not None and info.sid not in seen_sids:
            systems.append(info)
            seen_sids.add(info.sid)

    return Landscape(systems=systems)


def load_landscape_from_zip(zip_bytes: bytes, tmp_dir: Path) -> Landscape:
    """Extract a ZIP of XML files and load the landscape."""
    extract_path = safe_extract_zip(zip_bytes, tmp_dir)
    xml_files = []
    for xml_path in extract_path.rglob("*.xml"):
        try:
            xml_files.append((xml_path.name, xml_path.read_bytes()))
        except OSError as exc:
            logger.warning("Cannot read %s: %s", xml_path, exc)
    return load_landscape_from_files(xml_files)


def infer_environment(sid: str) -> str:
    """Infer environment from SID naming convention (conservative default: PROD)."""
    sid_upper = sid.upper()
    if sid_upper.endswith(("D", "DE", "DEV")):
        return "DEV"
    if sid_upper.endswith(("Q", "QA", "QAS")):
        return "QAS"
    return "PROD"
