"""
SAP Support Portal — online note fetcher.

Authenticates via SAP accounts.sap.com SAML/form login (session-based),
then downloads the note PDF from launchpad.support.sap.com.

No browser / selenium needed — pure requests + BeautifulSoup.
"""
from __future__ import annotations
import logging
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

_PDF_URL   = "https://launchpad.support.sap.com/services/pdf/notes/{}/E"
_PORTAL_URL = "https://launchpad.support.sap.com/"


def fetch_note_pdf(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note as PDF bytes.
    Returns (pdf_bytes, error_message).  On success error_message is "".
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        return None, f"Missing library: {e}. Install requests and beautifulsoup4."

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })

    pdf_url = _PDF_URL.format(note_number)

    # ── Step 1: Access PDF URL → will redirect to SAP login ──────────────────
    try:
        r = session.get(pdf_url, allow_redirects=True, timeout=20)
    except requests.exceptions.SSLError:
        return None, "SSL error connecting to SAP Support Portal. Check your network/proxy settings."
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach SAP Support Portal (launchpad.support.sap.com). Check internet access."
    except Exception as exc:
        return None, f"Network error: {exc}"

    # Already got PDF (e.g. session cookie from previous run)
    if _is_pdf(r):
        return r.content, ""

    # ── Step 2: We're at the SAP login page — parse and submit the form ───────
    login_url = r.url
    if r.status_code != 200:
        return None, f"SAP portal returned HTTP {r.status_code}"

    soup = BeautifulSoup(r.content, "lxml")

    # SAP uses a form with id="logOnForm" or similar
    form = (soup.find("form", id="logOnForm")
            or soup.find("form", {"name": "logOnForm"})
            or soup.find("form"))

    if not form:
        # JS-heavy page — try the known direct login endpoint
        return _try_oauth_login(session, pdf_url, s_user, s_password)

    # ── Step 3: Extract all hidden fields + fill in credentials ──────────────
    action = form.get("action", "")
    if not action:
        action = login_url
    elif not action.startswith("http"):
        action = urljoin(login_url, action)

    fields: dict = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if name:
            fields[name] = inp.get("value", "")

    # Fill credentials (SAP uses j_username / j_password)
    _set_field(fields, ["j_username", "logonId", "username", "uid", "email"], s_user)
    _set_field(fields, ["j_password", "password", "passwd"], s_password)

    # ── Step 4: Submit login ──────────────────────────────────────────────────
    try:
        r2 = session.post(action, data=fields, allow_redirects=True, timeout=20)
    except Exception as exc:
        return None, f"Login POST failed: {exc}"

    # Check for failed login (still on accounts.sap.com with a form)
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

    # ── Step 5: Now download the PDF with the authenticated session ───────────
    try:
        r3 = session.get(pdf_url, allow_redirects=True, timeout=20)
    except Exception as exc:
        return None, f"PDF download failed after login: {exc}"

    if _is_pdf(r3):
        logger.info("SAP Note %s downloaded OK (%d bytes)", note_number, len(r3.content))
        return r3.content, ""

    # Still getting HTML after login
    ct = r3.headers.get("Content-Type", "")
    if "html" in ct:
        soup3 = BeautifulSoup(r3.content, "lxml")
        if soup3.find("input", {"type": "password"}):
            return None, "Login did not succeed — still redirected to login page."
        # Maybe note not found
        page_text = soup3.get_text(" ", strip=True)[:500]
        if "404" in page_text or "not found" in page_text.lower():
            return None, f"Note {note_number} not found on SAP Support Portal."
        return None, f"Unexpected response after login (Content-Type: {ct}). The portal may require 2-factor auth."

    if r3.status_code == 403:
        return None, f"Note {note_number} access denied (403). Your S-user may not have download permissions."
    if r3.status_code == 404:
        return None, f"Note {note_number} not found on SAP Support Portal (404)."

    return None, f"Unexpected HTTP {r3.status_code} when downloading PDF."


def _try_oauth_login(session, pdf_url: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """Fallback: try SAP OAuth2 password grant (works for some S-user configurations)."""
    try:
        import requests
        token_url = "https://accounts.sap.com/oauth2/token"
        resp = session.post(token_url, data={
            "grant_type": "password",
            "username": s_user,
            "password": s_password,
            "client_id": "sap-launchpad",
            "scope": "openid",
        }, timeout=15)

        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            if token:
                session.headers["Authorization"] = f"Bearer {token}"
                r = session.get(pdf_url, allow_redirects=True, timeout=20)
                if _is_pdf(r):
                    return r.content, ""

    except Exception:
        pass

    return None, (
        "SAP Support Portal requires interactive login (SAML/SSO with possible 2-factor auth). "
        "Automatic fetch is not supported for your account configuration. "
        "Please use the **Upload File** tab: download the note PDF manually from "
        "https://me.sap.com/notes/{note} and upload it here."
    )


def _is_pdf(response) -> bool:
    ct = response.headers.get("Content-Type", "")
    return (response.status_code == 200 and
            ("pdf" in ct.lower() or response.content[:4] == b"%PDF"))


def _set_field(fields: dict, candidates: list, value: str) -> None:
    """Set the first matching field name to value, or add the first candidate."""
    for name in candidates:
        if name in fields:
            fields[name] = value
            return
    fields[candidates[0]] = value
