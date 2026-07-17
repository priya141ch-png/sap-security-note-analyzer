"""
SAP Support Portal — automated note PDF downloader.

Follows the complete SAML SSO flow:
  Step 1: GET PDF URL → SAML SP metadata form (auto-submit)
  Step 2: POST to authn.hana.ondemand.com → redirect to accounts.sap.com
  Step 3: Submit username to accounts.sap.com IDS
  Step 4: Submit password to accounts.sap.com IDS
  Step 5: POST SAML assertion back to launchpad
  Step 6: GET PDF with authenticated session
"""
from __future__ import annotations
import logging
import time
from typing import Optional, Tuple
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_PDF_URL = "https://launchpad.support.sap.com/services/pdf/notes/{}/E"


def fetch_note_pdf(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note PDF bytes. Returns (pdf_bytes, error_message).
    On success error_message is "".
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        return None, f"Missing library: {e}. Run: pip install requests beautifulsoup4 lxml"

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    pdf_url = _PDF_URL.format(note_number)

    try:
        # ── Step 1: GET PDF URL — returns SAML SP metadata form ───────────────
        r = session.get(pdf_url, allow_redirects=True, timeout=20)
        logger.debug("Step 1: %s → %s", pdf_url, r.url)

        if _is_pdf(r):
            return r.content, ""  # already authenticated (cached session)

        if r.status_code != 200:
            return None, f"SAP portal returned HTTP {r.status_code}"

        # ── Step 2: Follow SAML SP form → authn.hana.ondemand.com ────────────
        r = _submit_form(session, r, "Step 2 (SAML SP)")
        if r is None:
            return None, "Could not follow SAML SP redirect from launchpad."

        if _is_pdf(r):
            return r.content, ""

        # ── Step 3: May need another SAML redirect hop ─────────────────────────
        # authn.hana.ondemand.com itself may redirect to accounts.sap.com
        if "accounts.sap.com" not in r.url and _has_form(r):
            r = _submit_form(session, r, "Step 2b (SAML hop)")
            if r is None:
                return None, "SAML redirect chain broken."

        if _is_pdf(r):
            return r.content, ""

        # ── Step 3: Now at accounts.sap.com — submit username ─────────────────
        if "accounts.sap.com" not in r.url:
            return None, (
                f"Expected SAP ID login page but reached: {r.url}\n"
                f"Content-Type: {r.headers.get('Content-Type', '')}"
            )

        logger.debug("Step 3: Submitting username to %s", r.url)
        r = _submit_field(session, r, s_user,
                          candidates=["logOnId", "username", "identifier", "email",
                                      "j_username", "uid", "logonId"],
                          step="Step 3 (username)")
        if r is None:
            return None, "Failed to submit username to SAP ID Service."

        if _is_pdf(r):
            return r.content, ""

        # ── Step 4: Submit password ────────────────────────────────────────────
        logger.debug("Step 4: Submitting password to %s", r.url)
        r = _submit_field(session, r, s_password,
                          candidates=["password", "j_password", "passwd", "pass",
                                      "logOnPassword"],
                          step="Step 4 (password)")
        if r is None:
            return None, (
                "Failed to submit password. "
                "Check your S-user credentials in the settings."
            )

        if _is_pdf(r):
            return r.content, ""

        # ── Step 5: SAML assertion form → POST back to launchpad ──────────────
        # accounts.sap.com returns a SAML assertion form after successful login.
        # Must submit this BEFORE doing any error checks — otherwise we mistake
        # the SSO redirect page (accounts.sap.com/saml2/idp/sso?redirect=true)
        # for a login failure.
        if "accounts.sap.com" in r.url and _has_form(r):
            from bs4 import BeautifulSoup as _BS
            _soup = _BS(r.content, "lxml")
            _form = _soup.find("form")
            _has_saml = bool(_soup.find("input", {"name": "SAMLResponse"}))
            _has_pw   = bool(_soup.find("input", {"type": "password"}))
            _otp_inp  = (
                _soup.find("input", {"autocomplete": "one-time-code"})
                or _soup.find("input", {"name": lambda n: n and "otp" in n.lower() if n else False})
                or _soup.find("input", {"id":   lambda i: i and "otp" in i.lower() if i else False})
            )
            if _has_pw:
                return None, (
                    "Login failed — incorrect S-user ID or password. "
                    "Update your credentials in the S-user settings."
                )
            if _otp_inp:
                return None, (
                    "SAP Support Portal requires **Two-Factor Authentication (2FA)** "
                    "for your S-user account.\n\n"
                    "Your S-user ID and password were accepted, but a one-time code is required. "
                    "Automated download cannot complete this step.\n\n"
                    "**Workaround:** Use the **Upload note file** option below — open SAP portal "
                    "in your browser, log in manually, download the PDF, then upload it here."
                )
            # SAMLResponse form (or unknown form after login) — submit it
            logger.debug("Step 5: Posting SAML assertion from %s (SAMLResponse=%s)",
                         r.url, _has_saml)
            r = _submit_form(session, r, "Step 5 (SAML assertion)")
            if r is None:
                return None, "SAML assertion POST back to launchpad failed."

        elif _has_form(r):
            # Non-accounts form (e.g. launchpad intermediate redirect)
            logger.debug("Step 5: Posting intermediate form from %s", r.url)
            r = _submit_form(session, r, "Step 5 (SAML assertion)")
            if r is None:
                return None, "SAML assertion POST back to launchpad failed."

        if _is_pdf(r):
            logger.info("SAP Note %s downloaded (%d bytes)", note_number, len(r.content))
            return r.content, ""

        # ── Step 6: Final GET of PDF URL with authenticated session ────────────
        logger.debug("Step 6: Final PDF fetch with authenticated session")
        time.sleep(0.5)
        r = session.get(pdf_url, allow_redirects=True, timeout=20)

        if _is_pdf(r):
            logger.info("SAP Note %s downloaded (%d bytes)", note_number, len(r.content))
            return r.content, ""

        ct = r.headers.get("Content-Type", "")
        return None, (
            f"Authentication completed but PDF not returned (Content-Type: {ct}). "
            f"Final URL: {r.url}. "
            "Your S-user may not have download permissions for this note."
        )

    except Exception as exc:
        logger.exception("SAP fetch error")
        return None, f"Error during download: {exc}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _submit_form(session, response, step: str):
    """Find the first form in the response and submit it (all fields as-is)."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, "lxml")
        form = soup.find("form")
        if not form:
            return response  # no form — already at destination
        action = _form_action(form, response.url)
        fields = {inp["name"]: inp.get("value", "")
                  for inp in form.find_all("input") if inp.get("name")}
        method = form.get("method", "post").lower()
        logger.debug("%s: %s %s  fields=%s", step, method.upper(), action, list(fields))
        if method == "get":
            r = session.get(action, params=fields, allow_redirects=True, timeout=20)
        else:
            r = session.post(action, data=fields, allow_redirects=True, timeout=20)
        return r
    except Exception as exc:
        logger.warning("%s submit_form error: %s", step, exc)
        return None


def _submit_field(session, response, value: str, candidates: list, step: str):
    """
    Find the first form, fill in the first matching field with value,
    keep all other fields as-is, then submit.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, "lxml")
        form = soup.find("form")
        if not form:
            logger.warning("%s: no form found", step)
            return None
        action = _form_action(form, response.url)
        fields: dict = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if name:
                fields[name] = inp.get("value", "")

        # Fill in the target field
        filled = False
        for name in candidates:
            if name in fields:
                fields[name] = value
                filled = True
                break
        if not filled:
            # Field not found by name — try by type
            for inp in form.find_all("input", {"type": ["text", "email", "password"]}):
                name = inp.get("name")
                if name:
                    fields[name] = value
                    filled = True
                    break
        if not filled:
            logger.warning("%s: could not find target field in form (fields: %s)",
                           step, list(fields))

        method = form.get("method", "post").lower()
        logger.debug("%s: %s %s  fields=%s", step, method.upper(), action,
                     [k for k in fields if "pass" not in k.lower()])
        r = session.post(action, data=fields, allow_redirects=True, timeout=20)
        return r
    except Exception as exc:
        logger.warning("%s submit_field error: %s", step, exc)
        return None


def _form_action(form, current_url: str) -> str:
    action = form.get("action", "")
    if not action:
        return current_url
    if action.startswith("http"):
        return action
    return urljoin(current_url, action)


def _has_form(response) -> bool:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, "lxml")
        return bool(soup.find("form"))
    except Exception:
        return False


def _is_pdf(response) -> bool:
    ct = response.headers.get("Content-Type", "")
    return (response.status_code == 200
            and ("pdf" in ct.lower() or response.content[:4] == b"%PDF"))
