"""
SAP Note PDF downloader using Playwright (headless Chromium).

Flow: me.sap.com/notes/{id} -> accounts.sap.com SAML login -> back to note page -> PDF download
"""
from __future__ import annotations
import logging
import os
import pathlib

# Auto-set LD_LIBRARY_PATH so headless Chromium finds GTK/X11 libs
# extracted to user-space under ~/lib_deps (no sudo needed)
def _set_lib_path():
    home = pathlib.Path.home()
    dirs = [
        str(home / "lib_deps" / "usr" / "lib" / "x86_64-linux-gnu"),
        str(home / "lib_deps" / "usr" / "lib"),
    ]
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(dirs + ([existing] if existing else []))
_set_lib_path()

import tempfile
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


def _do_sap_login(page, s_user: str, s_password: str, pw_timeout_cls) -> bool:
    """Handle accounts.sap.com login page. Returns True on success."""
    try:
        page.wait_for_selector("#logOnId,input[name='logOnId'],input[type='email']", timeout=12000)
        for sel in ["#logOnId", "input[name='logOnId']", "input[type='email']", "input[type='text']"]:
            try:
                page.fill(sel, s_user, timeout=2000)
                logger.debug("Filled S-user via: %s", sel)
                break
            except Exception:
                pass
        for btn in ["#continue", "button[type='submit']", "button:has-text('Continue')", "button:has-text('Next')"]:
            try:
                page.click(btn, timeout=3000)
                break
            except Exception:
                pass
        page.wait_for_selector("input[type='password']", timeout=12000)
        page.fill("input[type='password']", s_password)
        for btn in ["#submit", "button[type='submit']", "button:has-text('Sign In')", "button:has-text('Log On')", "button:has-text('Continue')"]:
            try:
                page.click(btn, timeout=3000)
                break
            except Exception:
                pass
        try:
            page.wait_for_function("!window.location.hostname.includes('accounts.sap.com')", timeout=20000)
        except pw_timeout_cls:
            pass
        return "accounts.sap.com" not in page.url
    except Exception as e:
        logger.debug("Login error: %s", e)
        return False


def fetch_note_pdf_me(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note PDF using Playwright headless browser.
    Returns (pdf_bytes, error_message). On success error_message is "".
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        return None, "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            note_url = "https://me.sap.com/notes/" + note_number
            logger.debug("Navigating to: %s", note_url)
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
            except PwTimeout:
                pass

            # Handle login redirect loop
            for hop in range(5):
                current = page.url
                logger.debug("Hop %d: %s", hop, current)
                if "me.sap.com/notes" in current:
                    break
                if "accounts.sap.com" in current:
                    ok = _do_sap_login(page, s_user, s_password, PwTimeout)
                    if not ok:
                        browser.close()
                        return None, "SAP login failed — check S-user credentials in workspace settings."
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except PwTimeout:
                    pass

            if "me.sap.com/notes" not in page.url:
                browser.close()
                return None, "Could not reach note page. Ended up at: " + page.url

            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PwTimeout:
                pass

            logger.debug("Note page loaded: %s", page.url)

            pdf_selectors = [
                "button:has-text('PDF')",
                "a:has-text('PDF')",
                "[title='PDF']",
                "[aria-label='PDF']",
                "[title*='Download PDF']",
                "[aria-label*='Download PDF']",
                "button.pdf-download",
            ]

            clicked = False
            try:
                # page.expect_download — correct Playwright API (not context.expect_download)
                with page.expect_download(timeout=30000) as dl_info:
                    for sel in pdf_selectors:
                        try:
                            page.click(sel, timeout=4000)
                            logger.debug("Clicked PDF via: %s", sel)
                            clicked = True
                            break
                        except Exception:
                            pass

                    if not clicked:
                        for el in page.query_selector_all("button, a, [role='button'], [role='link']"):
                            try:
                                txt = (el.inner_text() or "").strip().upper()
                                if txt == "PDF" or "DOWNLOAD PDF" in txt:
                                    el.click(timeout=3000)
                                    logger.debug("Clicked PDF element by text: %r", txt)
                                    clicked = True
                                    break
                            except Exception:
                                pass

                    if not clicked:
                        browser.close()
                        return None, (
                            "PDF download button not found on me.sap.com/notes/" + note_number +
                            ". The note may not have a PDF or the page did not fully render."
                        )

                download = dl_info.value
                tmp = pathlib.Path(tempfile.mktemp(suffix=".pdf"))
                download.save_as(str(tmp))
                pdf_bytes = tmp.read_bytes()
                tmp.unlink(missing_ok=True)

            except PwTimeout:
                browser.close()
                return None, "Timed out waiting for PDF download. The PDF button may open a new tab instead."

            browser.close()

            if not pdf_bytes or len(pdf_bytes) < 500:
                return None, "Downloaded file is too small — may be empty or an error page."
            if pdf_bytes[:4] != b"%PDF":
                return None, "Downloaded file is not a valid PDF (starts with: " + repr(pdf_bytes[:20]) + ")."

            logger.info("Note %s downloaded via me.sap.com (%d bytes)", note_number, len(pdf_bytes))
            return pdf_bytes, ""

    except Exception as exc:
        logger.exception("Playwright fetch failed")
        return None, "Browser-based download failed: " + str(exc)


def fetch_note_html_me(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[str], str]:
    """
    Fetch SAP Note page HTML from me.sap.com (returns rendered HTML, no PDF download).
    Useful for structured data extraction when PDF is unavailable.
    Returns (html_content, error_message).
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        return None, "Playwright not installed."

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            context = browser.new_context()
            page = context.new_page()

            note_url = "https://me.sap.com/notes/" + note_number
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
            except PwTimeout:
                pass

            for hop in range(5):
                current = page.url
                if "me.sap.com/notes" in current:
                    break
                if "accounts.sap.com" in current:
                    ok = _do_sap_login(page, s_user, s_password, PwTimeout)
                    if not ok:
                        browser.close()
                        return None, "SAP login failed — check S-user credentials."
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except PwTimeout:
                    pass

            if "me.sap.com/notes" not in page.url:
                browser.close()
                return None, "Could not reach note page. Ended at: " + page.url

            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PwTimeout:
                pass

            html = page.content()
            browser.close()
            return html, ""

    except Exception as exc:
        logger.exception("HTML fetch failed")
        return None, "Browser HTML fetch failed: " + str(exc)
