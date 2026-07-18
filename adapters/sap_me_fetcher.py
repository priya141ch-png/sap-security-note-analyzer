"""
SAP Note fetcher via me.sap.com API.

Flow:
  1. Playwright headless login -> accounts.sap.com SAML -> me.sap.com session cookies
  2. GET /backend/raw/sapnotes/Detail?q={note} -> full structured JSON
  3. (Optional) follow Print URL for PDF via another SAML hop to userapps.support.sap.com

The sapnotes/Detail JSON is the primary data source and contains all fields needed
for security analysis: title, priority, category, component, validity (SW components),
LongText (symptom/solution/prerequisites in HTML), CorrectionInstructions, References.
"""
from __future__ import annotations
import logging
import os
import pathlib

def _set_lib_path():
    """Set LD_LIBRARY_PATH so headless Chromium finds GTK/X11 libs extracted to ~/lib_deps."""
    home = pathlib.Path.home()
    dirs = [
        str(home / "lib_deps" / "usr" / "lib" / "x86_64-linux-gnu"),
        str(home / "lib_deps" / "usr" / "lib"),
    ]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(dirs + ([existing] if existing else []))

_set_lib_path()

from typing import Optional, Tuple, Dict, Any
import requests

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
_ME_SAP_BASE = "https://me.sap.com"


def _playwright_login(s_user: str, s_password: str, note_number: str) -> list:
    """
    Login to me.sap.com via Playwright and return the session cookies.
    Navigates to the note page which triggers accounts.sap.com SAML login.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

    cookies = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        context = browser.new_context()
        page = context.new_page()

        note_url = f"{_ME_SAP_BASE}/notes/{note_number}"
        try:
            page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
        except PwTimeout:
            pass

        if "accounts.sap.com" in page.url:
            logger.debug("Login page: %s", page.url)
            # Step 1: fill username
            page.wait_for_selector("#j_username", timeout=12000)
            page.fill("#j_username", s_user)
            page.click("#logOnFormSubmit", timeout=5000)
            # Step 2: password revealed after Continue click
            page.wait_for_selector("#j_password", timeout=15000)
            page.fill("#j_password", s_password)
            page.click("#logOnFormSubmit", timeout=5000)
            try:
                page.wait_for_function(
                    "!window.location.hostname.includes('accounts.sap.com')",
                    timeout=25000
                )
            except PwTimeout:
                pass
            logger.debug("After login: %s", page.url)

        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PwTimeout:
            pass

        cookies = context.cookies()
        browser.close()

    return cookies


def _build_session(cookies: list) -> requests.Session:
    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"])
    return session


def fetch_note_json_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Fetch SAP Note structured data from me.sap.com.

    Returns (note_dict, error_message).
    On success: error_message is "" and note_dict contains parsed note fields.
    On failure: note_dict is None and error_message describes the problem.

    note_dict keys:
      number, title, type, version, priority, category, status, released_on,
      component_key, component_text, language,
      long_text_html,          # full HTML body (Symptom/Solution sections)
      validity_items,          # list of {SoftwareComponent, From, To}
      support_packages,        # list of {SoftwareComponent, SupportPackage, ...}
      correction_instructions, # list of correction instruction items
      manual_actions_html,     # HTML manual implementation steps
      references_to,           # list of related notes
      references_by,           # list of notes referencing this
      preconditions,           # list of prerequisite items
      attachments,             # list of attachment items
      pdf_print_url,           # token-based PDF URL (may require auth)
      snote_download_url,      # SNOTE transport download URL
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"

    try:
        logger.info("Logging in to me.sap.com for note %s", note_number)
        cookies = _playwright_login(s_user, s_password, note_number)
        if not cookies:
            return None, "Login failed — no cookies returned. Check S-user credentials."

        session = _build_session(cookies)
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": f"{_ME_SAP_BASE}/notes/{note_number}",
            "X-Requested-With": "XMLHttpRequest",
        }

        url = f"{_ME_SAP_BASE}/backend/raw/sapnotes/Detail?q={note_number}"
        logger.debug("Fetching note detail: %s", url)
        r = session.get(url, headers=hdrs, timeout=30, allow_redirects=True)

        if r.status_code != 200:
            return None, f"Note API returned {r.status_code}: {r.text[:200]}"

        data = r.json()
        resp = data.get("Response", {})
        error = resp.get("Error", {})
        if error and error.get("message"):
            return None, f"SAP API error: {error['message']}"

        raw = resp.get("SAPNote", {})
        if not raw:
            return None, "No SAPNote data in response."

        def val(d, *keys):
            """Safely get nested .value from API response."""
            for k in keys:
                d = d.get(k, {}) if isinstance(d, dict) else {}
            return d.get("value", "") if isinstance(d, dict) else ""

        def items(d, *keys):
            """Safely get nested Items list."""
            for k in keys:
                d = d.get(k, {}) if isinstance(d, dict) else {}
            return d.get("Items", []) if isinstance(d, dict) else []

        actions = raw.get("Actions", {})
        note_dict = {
            "number":              val(raw, "Header", "Number") or note_number,
            "title":               val(raw, "Title"),
            "type":                val(raw, "Header", "Type"),
            "version":             val(raw, "Header", "Version"),
            "priority":            val(raw, "Header", "Priority"),
            "category":            val(raw, "Header", "Category"),
            "status":              val(raw, "Header", "Status"),
            "released_on":         val(raw, "Header", "ReleasedOn"),
            "component_key":       val(raw, "Header", "SAPComponentKey"),
            "component_text":      val(raw, "Header", "SAPComponentKeyText"),
            "language":            val(raw, "Header", "Language"),
            "long_text_html":      val(raw, "LongText"),
            "validity_items":      items(raw, "Validity"),
            "support_packages":    items(raw, "SupportPackage"),
            "support_package_patches": items(raw, "SupportPackagePatch"),
            "correction_instructions": items(raw, "CorrectionInstructions"),
            "manual_actions_html": val(raw, "ManualActions"),
            "references_to":       raw.get("References", {}).get("RefTo", {}).get("Items", []),
            "references_by":       raw.get("References", {}).get("RefBy", {}).get("Items", []),
            "preconditions":       items(raw, "Preconditions"),
            "attachments":         items(raw, "Attachments"),
            "pdf_print_url":       actions.get("Print", {}).get("url", ""),
            "snote_download_url":  actions.get("Download", {}).get("url", ""),
        }

        logger.info("Note %s fetched: %s", note_number, note_dict["title"][:60])
        return note_dict, ""

    except Exception as exc:
        logger.exception("fetch_note_json_me failed")
        return None, f"me.sap.com fetch failed: {exc}"


def fetch_note_pdf_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note PDF from me.sap.com.

    Fetches the structured note JSON first to get the token-based PDF print URL,
    then attempts to download it. Falls back gracefully if PDF is unavailable.

    Returns (pdf_bytes, error_message).
    """
    note_dict, err = fetch_note_json_me(note_number, s_user, s_password)
    if err:
        return None, err

    pdf_url = note_dict.get("pdf_print_url", "")
    if not pdf_url:
        return None, f"No PDF URL in note {note_number} response."

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
        import tempfile
    except ImportError:
        return None, "Playwright not installed."

    try:
        logger.info("Fetching PDF for note %s via: %s", note_number, pdf_url[:60])
        cookies = _playwright_login(s_user, s_password, note_number)
        session = _build_session(cookies)

        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/pdf,*/*",
            "Referer": f"{_ME_SAP_BASE}/notes/{note_number}",
        }
        r = session.get(pdf_url, headers=hdrs, timeout=30, allow_redirects=True)

        if r.content[:4] == b"%PDF":
            logger.info("PDF download success: %d bytes", len(r.content))
            return r.content, ""

        # PDF URL may need its own SAML auth to userapps.support.sap.com
        # Try following any redirect chain via Playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            context = browser.new_context(accept_downloads=True)
            for c in cookies:
                try:
                    context.add_cookies([c])
                except Exception:
                    pass
            page = context.new_page()
            try:
                with page.expect_download(timeout=30000) as dl_info:
                    page.goto(pdf_url, wait_until="domcontentloaded", timeout=20000)
                download = dl_info.value
                tmp = pathlib.Path(tempfile.mktemp(suffix=".pdf"))
                download.save_as(str(tmp))
                pdf_bytes = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                browser.close()
                if pdf_bytes[:4] == b"%PDF":
                    return pdf_bytes, ""
                return None, "Downloaded file is not a valid PDF."
            except Exception as e:
                browser.close()
                return None, f"PDF download failed: {e}"

    except Exception as exc:
        logger.exception("fetch_note_pdf_me failed")
        return None, f"PDF download failed: {exc}"


def fetch_note_html_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[str], str]:
    """
    Fetch SAP Note content as HTML string from the note JSON long_text_html field.
    Returns (html_string, error_message).
    """
    note_dict, err = fetch_note_json_me(note_number, s_user, s_password)
    if err:
        return None, err
    html = note_dict.get("long_text_html", "")
    if not html:
        return None, "Note has no long text / HTML content."
    return html, ""
