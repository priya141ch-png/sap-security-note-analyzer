"""Unit tests for the SAP landscape XML parser."""

import pytest
from adapters.system_info_parser import parse_system_info_xml, load_landscape_from_files, safe_extract_zip
import zipfile, io, tempfile
from pathlib import Path


SAMPLE_XML_GENERIC = b"""<?xml version="1.0" encoding="UTF-8"?>
<SystemData>
  <SystemID>S4P</SystemID>
  <SystemType>ABAP</SystemType>
  <SoftwareComponent>
    <Name>SAP_BASIS</Name>
    <Release>756</Release>
    <SpLevel>0005</SpLevel>
    <PatchLevel>3</PatchLevel>
  </SoftwareComponent>
  <SoftwareComponent>
    <Name>SAP_ABA</Name>
    <Release>756</Release>
    <SpLevel>0005</SpLevel>
  </SoftwareComponent>
</SystemData>
"""

SAMPLE_XML_SPSTACKS = b"""<?xml version="1.0" encoding="UTF-8"?>
<stack-xml>
  <system-identity-update>
    <system-id>DEV</system-id>
    <system-type>ABAP</system-type>
  </system-identity-update>
  <software-component-entry>
    <name>SAP_BASIS</name>
    <release>755</release>
    <sp-level>0009</sp-level>
  </software-component-entry>
</stack-xml>
"""


def test_parse_generic_xml():
    info = parse_system_info_xml(SAMPLE_XML_GENERIC)
    assert info is not None
    assert info.sid == "S4P"
    assert info.sap_basis_release == "756"
    assert any(c.name == "SAP_BASIS" for c in info.components)


def test_parse_spstacks_xml():
    info = parse_system_info_xml(SAMPLE_XML_SPSTACKS, sid_hint="DEV")
    assert info is not None
    assert info.sap_basis_release == "755"


def test_load_landscape_from_files():
    files = [("s4p.xml", SAMPLE_XML_GENERIC), ("dev.xml", SAMPLE_XML_SPSTACKS)]
    land = load_landscape_from_files(files)
    assert len(land.systems) == 2
    sids = {s.sid for s in land.systems}
    assert "S4P" in sids


def test_safe_extract_rejects_zip_slip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "bad content")
    buf.seek(0)

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="Unsafe ZIP path"):
            safe_extract_zip(buf.read(), Path(tmp) / "extract")


def test_safe_extract_ok():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("system/s4p.xml", SAMPLE_XML_GENERIC.decode())
    buf.seek(0)

    with tempfile.TemporaryDirectory() as tmp:
        out = safe_extract_zip(buf.read(), Path(tmp) / "extract")
        assert (out / "system" / "s4p.xml").exists()
