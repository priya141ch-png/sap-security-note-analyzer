"""Unit tests for the HTML note parser."""

import pytest
from adapters.note_parser import parse_note

SAMPLE_HTML = b"""<!DOCTYPE html>
<html>
<head><title>SAP Note 3694242 - Test Vulnerability</title></head>
<body>
<h1>SAP Note 3694242</h1>
<h2>3694242 - Remote Code Execution in SAP NetWeaver</h2>
<p>Priority: Critical</p>
<p>CVSS Score: 9.1</p>
<p>Published: 2024-04-09</p>
<h3>Symptom</h3>
<p>An unauthenticated attacker can exploit a vulnerability in SAP NetWeaver AS ABAP.</p>
<h3>Solution</h3>
<p>Apply the correction instructions provided in this note. Ensure SP level 0005 or higher is applied.</p>
<h3>Workaround</h3>
<p>Restrict access to the affected service via ACL until the note is applied.</p>
<table>
  <tr><th>Software Component</th><th>Release</th><th>From SP</th><th>To SP</th></tr>
  <tr><td>SAP_BASIS</td><td>756</td><td>0000</td><td>0005</td></tr>
  <tr><td>SAP_BASIS</td><td>757</td><td>0000</td><td>0003</td></tr>
</table>
<p>Component: BC-MID-RFC</p>
</body>
</html>
"""


def test_parse_note_number():
    note = parse_note(SAMPLE_HTML, "3694242.html")
    assert note is not None
    assert note.note_number == "3694242"


def test_parse_severity():
    note = parse_note(SAMPLE_HTML)
    assert note.severity == "Critical"


def test_parse_cvss():
    note = parse_note(SAMPLE_HTML)
    assert note.cvss_score == 9.1


def test_parse_symptoms():
    note = parse_note(SAMPLE_HTML)
    assert "unauthenticated attacker" in note.symptoms.lower()


def test_parse_workaround():
    note = parse_note(SAMPLE_HTML)
    assert "acl" in note.workaround.lower()


def test_parse_applicability_matrix():
    note = parse_note(SAMPLE_HTML)
    assert len(note.applicability_matrix) >= 1
    comps = [e.component for e in note.applicability_matrix]
    assert any("SAP_BASIS" in c or "BASIS" in c for c in comps)


def test_parse_published_date():
    note = parse_note(SAMPLE_HTML)
    assert note.published_date == "2024-04-09"


def test_empty_html_returns_note_with_warnings():
    note = parse_note(b"<html><body></body></html>", "empty.html")
    assert note is not None
    assert len(note.parser_warnings) > 0
