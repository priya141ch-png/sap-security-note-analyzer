"""
SAP Note fetcher via me.sap.com API.

Flow:
  1. Playwright headless login -> accounts.sap.com SAML -> me.sap.com session
  2. Intercept /backend/raw/sapnotes/Detail?q={note} response in same Playwright context
  3. Parse JSON -> structured note_dict

Uses Playwright throughout (avoids requests SSL TLS compat issues with me.sap.com).
"""
from __future__ import annotations
import logging
import os
import pathlib

def _set_lib_path():
    home = pathlib.Path.home()
    dirs = [
        str(home / "lib_deps" / "usr" / "lib" / "x86_64-linux-gnu"),
        str(home / "lib_deps" / "usr" / "lib"),
    ]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(dirs + ([existing] if existing else []))

_set_lib_path()

from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
_ME_SAP_BASE = "https://me.sap.com"


def _login_and_fetch_api(s_user: str, s_password: str, note_number: str) -> Tuple[Optional[dict], str]:
    """
    Login to me.sap.com via Playwright and fetch the note detail API JSON.
    Stays within the same browser context to avoid Python requests SSL issues.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    import json, re

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        context = browser.new_context()
        page = context.new_page()

        api_data = {}
        api_error = []

        def handle_response(response):
            if "/backend/raw/sapnotes/Detail" in response.url:
                try:
                    api_data["body"] = response.json()
                    logger.debug("Intercepted API response for note %s", note_number)
                except Exception as e:
                    api_error.append(str(e))

        page.on("response", handle_response)

        note_url = f"{_ME_SAP_BASE}/notes/{note_number}"
        try:
            page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
        except PwTimeout:
            pass

        if "accounts.sap.com" in page.url:
            logger.debug("Redirected to login: %s", page.url)
            page.wait_for_selector("#j_username", timeout=12000)
            page.fill("#j_username", s_user)
            page.click("#logOnFormSubmit", timeout=5000)
            page.wait_for_selector("#j_password", timeout=15000)
            page.fill("#j_password", s_password)
            page.click("#logOnFormSubmit", timeout=5000)
            not_on_accounts = "window.location.hostname.indexOf('accounts.sap.com') === -1"
            try:
                page.wait_for_function(not_on_accounts, timeout=25000)
            except PwTimeout:
                pass
            logger.debug("After login: %s", page.url)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PwTimeout:
            pass

        # If SPA didn't fire the API call yet, navigate directly to the API URL
        if not api_data:
            api_url = f"{_ME_SAP_BASE}/backend/raw/sapnotes/Detail?q={note_number}"
            logger.debug("Navigating directly to API URL: %s", api_url)
            try:
                resp = page.goto(api_url, wait_until="domcontentloaded", timeout=30000)
                if resp and resp.ok:
                    try:
                        api_data["body"] = resp.json()
                    except Exception:
                        raw_text = page.inner_text("body")
                        m = re.search(r"\{.+\}", raw_text, re.DOTALL)
                        if m:
                            api_data["body"] = json.loads(m.group(0))
            except PwTimeout:
                pass

        browser.close()

    if not api_data:
        errmsg = api_error[0] if api_error else "No API response captured — login may have failed."
        return None, errmsg

    return api_data["body"], ""


def fetch_note_json_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Fetch SAP Note structured data from me.sap.com.

    Returns (note_dict, error_message).
    note_dict keys: number, title, type, version, priority, category, status,
      released_on, component_key, component_text, language, long_text_html,
      validity_items, support_packages, support_package_patches,
      correction_instructions, manual_actions_html, references_to, references_by,
      preconditions, attachments, pdf_print_url, snote_download_url
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa — verify installed
    except ImportError:
        return None, "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"

    try:
        logger.info("Fetching note %s from me.sap.com", note_number)
        data, err = _login_and_fetch_api(s_user, s_password, note_number)
        if err:
            return None, err
        if not data:
            return None, "Empty response from me.sap.com API."

        resp = data.get("Response", {})
        error = resp.get("Error", {})
        if error and error.get("message"):
            return None, f"SAP API error: {error['message']}"

        raw = resp.get("SAPNote", {})
        if not raw:
            return None, "No SAPNote data in response."

        def val(d, *keys):
            for k in keys:
                d = d.get(k, {}) if isinstance(d, dict) else {}
            return d.get("value", "") if isinstance(d, dict) else ""

        def items(d, *keys):
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


def fetch_note_html_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[str], str]:
    """Fetch SAP Note HTML content. Returns (html_string, error_message)."""
    note_dict, err = fetch_note_json_me(note_number, s_user, s_password)
    if err:
        return None, err
    html = note_dict.get("long_text_html", "")
    if not html:
        return None, "Note has no long text / HTML content."
    return html, ""
