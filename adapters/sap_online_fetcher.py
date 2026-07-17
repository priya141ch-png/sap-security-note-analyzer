"""
SAP Support Portal — online note fetcher.

Tries three approaches in order:
  1. Basic-Auth on the OData JSON API (fast, works for many S-users)
  2. Basic-Auth on the PDF download URL
  3. Session/form-based login (fallback, fails if 2FA is enabled)

Returns (pdf_bytes_or_None, json_meta_or_None, error_message).
"""
from __future__ import annotations
import base64
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PDF_URL   = "https://launchpad.support.sap.com/services/pdf/notes/{}/E"
_ODATA_URL = "https://launchpad.support.sap.com/services/odata/svt/snogwas/Notes('{}')?$format=json"
_NEW_PDF_URL = "https://me.sap.com/notes/{}/E/PDF"


def fetch_note_pdf(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note as PDF bytes.
    Returns (pdf_bytes, error_message).  On success error_message is "".
    """
    try:
        import requests
    except ImportError as e:
        return None, f"Missing library: {e}. Install requests."

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    # ── Approach 1: Basic Auth on PDF URL ────────────────────────────────────
    try:
        creds = base64.b64encode(f"{s_user}:{s_password}".encode()).decode()
        r = session.get(
            _PDF_URL.format(note_number),
            headers={"Authorization": f"Basic {creds}"},
            allow_redirects=True, timeout=25,
        )
        if _is_pdf(r):
            logger.info("SAP Note %s fetched via Basic Auth (%d bytes)", note_number, len(r.content))
            return r.content, ""
        if r.status_code == 401:
            logger.debug("Basic auth rejected for PDF URL")
        elif r.status_code == 403:
            return None, (
                f"Note {note_number} access denied (403). "
                "Your S-user may not have PDF download permissions."
            )
        elif r.status_code == 404:
            return None, f"Note {note_number} not found on SAP Support Portal (404)."
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach SAP Support Portal. Check your internet connection."
    except requests.exceptions.SSLError:
        return None, "SSL error connecting to SAP Support Portal. Check proxy/firewall settings."
    except Exception as exc:
        logger.debug("Basic-auth PDF attempt failed: %s", exc)

    # ── Approach 2: Basic Auth on new me.sap.com PDF URL ─────────────────────
    try:
        creds = base64.b64encode(f"{s_user}:{s_password}".encode()).decode()
        r2 = session.get(
            _NEW_PDF_URL.format(note_number),
            headers={"Authorization": f"Basic {creds}"},
            allow_redirects=True, timeout=25,
        )
        if _is_pdf(r2):
            logger.info("SAP Note %s fetched via me.sap.com Basic Auth (%d bytes)", note_number, len(r2.content))
            return r2.content, ""
    except Exception as exc:
        logger.debug("me.sap.com Basic-auth attempt failed: %s", exc)

    # ── Approach 3: Form-based login (works only without 2FA) ────────────────
    pdf_bytes, err = _form_login_and_fetch(session, note_number, s_user, s_password)
    if pdf_bytes:
        return pdf_bytes, ""

    # All approaches failed — return a meaningful error
    if err and ("2-factor" in err or "2FA" in err or "unexpected response" in err.lower()):
        return None, (
            "SAP Support Portal requires **interactive (2FA) login** for your S-user account — "
            "automated download is not possible.\n\n"
            "**To get the note data:**\n"
            "1. Click **View Note** above to open the note in a new browser tab\n"
            "2. Log in to SAP portal manually\n"
            "3. Download the note PDF (print to PDF or use the download button)\n"
            "4. Use **Manual options → Upload PDF** below to import it"
        )
    return None, err or "Could not download note — check your S-user credentials and permissions."


def _form_login_and_fetch(session, note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """Fall back to session/form-based login."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None, "beautifulsoup4 not installed."

    pdf_url = _PDF_URL.format(note_number)
    try:
        r = session.get(pdf_url, allow_redirects=True, timeout=20)
    except Exception as exc:
        return None, f"Network error: {exc}"

    if _is_pdf(r):
        return r.content, ""

    login_url = r.url
    if r.status_code != 200:
        return None, f"SAP portal returned HTTP {r.status_code}"

    soup = BeautifulSoup(r.content, "lxml")
    form = (soup.find("form", id="logOnForm")
            or soup.find("form", {"name": "logOnForm"})
            or soup.find("form"))

    if not form:
        return None, (
            "Unexpected response after login (Content-Type: "
            f"{r.headers.get('Content-Type', '')}). "
            "The portal may require 2-factor auth."
        )

    from urllib.parse import urljoin
    action = form.get("action", "") or login_url
    if not action.startswith("http"):
        action = urljoin(login_url, action)

    fields: dict = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name:
            fields[name] = inp.get("value", "")

    _set_field(fields, ["j_username", "logonId", "username", "uid", "email"], s_user)
    _set_field(fields, ["j_password", "password", "passwd"], s_password)

    try:
        r2 = session.post(action, data=fields, allow_redirects=True, timeout=20)
    except Exception as exc:
        return None, f"Login POST failed: {exc}"

    if "accounts.sap.com" in r2.url:
        soup2 = BeautifulSoup(r2.content, "lxml")
        err_tag = soup2.find(class_=lambda c: c and "error" in c.lower() if c else False)
        if err_tag:
            return None, f"Login failed: {err_tag.get_text(strip=True)[:200]}"
        if soup2.find("input", {"type": "password"}):
            return None, (
                "Login failed — invalid S-user ID or password. "
                "Check your credentials at https://accounts.sap.com"
            )

    try:
        r3 = session.get(pdf_url, allow_redirects=True, timeout=20)
    except Exception as exc:
        return None, f"PDF download failed after login: {exc}"

    if _is_pdf(r3):
        logger.info("SAP Note %s downloaded via form login (%d bytes)", note_number, len(r3.content))
        return r3.content, ""

    ct = r3.headers.get("Content-Type", "")
    if "html" in ct:
        soup3 = BeautifulSoup(r3.content, "lxml")
        if soup3.find("input", {"type": "password"}):
            return None, "Login did not succeed — still redirected to login page."
        page_text = soup3.get_text(" ", strip=True)[:500]
        if "404" in page_text or "not found" in page_text.lower():
            return None, f"Note {note_number} not found on SAP Support Portal."
        return None, (
            f"Unexpected response after login (Content-Type: {ct}). "
            "The portal may require 2-factor auth."
        )

    if r3.status_code == 403:
        return None, f"Note {note_number} access denied (403)."
    if r3.status_code == 404:
        return None, f"Note {note_number} not found (404)."
    return None, f"Unexpected HTTP {r3.status_code} when downloading PDF."


def _is_pdf(response) -> bool:
    ct = response.headers.get("Content-Type", "")
    return (response.status_code == 200
            and ("pdf" in ct.lower() or response.content[:4] == b"%PDF"))


def _set_field(fields: dict, candidates: list, value: str) -> None:
    for name in candidates:
        if name in fields:
            fields[name] = value
            return
    fields[candidates[0]] = value
