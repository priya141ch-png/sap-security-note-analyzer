"""
SAP 'me.sap.com' PDF downloader using Playwright (headless Chromium).

me.sap.com uses OAuth2/OIDC (not SAML), so form-following with requests
does not work. Playwright drives the real browser login and intercepts
the PDF download triggered by the PDF button on the note page.
"""
from __future__ import annotations
import logging
import pathlib
import tempfile
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def fetch_note_pdf_me(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    """
    Download SAP Note PDF from me.sap.com using Playwright headless browser.
    Returns (pdf_bytes, error_message). On success error_message is empty string.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        return None, (
            "Playwright not installed. Run: \n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            note_url = f"https://me.sap.com/notes/{note_number}"
            logger.debug("Navigating to %s", note_url)
            try:
                page.goto(note_url, wait_until="networkidle", timeout=30000)
            except PwTimeout:
                page.goto(note_url, wait_until="domcontentloaded", timeout=30000)

            # Follow through login if redirected
            for _ in range(3):
                url = page.url
                if "me.sap.com/notes" in url:
                    break
                if "accounts.sap.com" in url or "login" in url or "authenticate" in url:
                    logger.debug("At login: %s", url)
                    # Fill username
                    try:
                        page.wait_for_selector("input[type='text'],input[type='email'],#logOnId", timeout=10000)
                        for sel in ["#logOnId", "input[name='logOnId']", "input[type='email']", "input[type='text']"]:
                            try:
                                page.fill(sel, s_user, timeout=3000)
                                logger.debug("Filled username via %s", sel)
                                break
                            except Exception:
                                pass
                        # Click continue
                        for btn in ["button[type='submit']", "#continue", "button:has-text('Continue')", "button:has-text('Next')"]:
                            try:
                                page.click(btn, timeout=3000)
                                break
                            except Exception:
                                pass
                        time.sleep(2)
                        # Fill password
                        page.wait_for_selector("input[type='password']", timeout=10000)
                        page.fill("input[type='password']", s_password)
                        for btn in ["button[type='submit']", "#submit", "button:has-text('Sign In')", "button:has-text('Log On')"]:
                            try:
                                page.click(btn, timeout=3000)
                                break
                            except Exception:
                                pass
                        try:
                            page.wait_for_url("*me.sap.com*", timeout=20000)
                        except PwTimeout:
                            pass
                    except Exception as e:
                        logger.debug("Login step error: %s", e)
                        break
                else:
                    # Some intermediate OAuth redirect — wait
                    try:
                        page.wait_for_url("*me.sap.com*", timeout=15000)
                    except PwTimeout:
                        break

            # Check for login failure
            if "accounts.sap.com" in page.url:
                return None, "Login failed — incorrect S-user ID or password. Check credentials in settings."

            # Wait for note page content
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PwTimeout:
                pass

            logger.debug("On note page: %s", page.url)

            # Intercept the PDF download
            pdf_bytes = None
            with context.expect_download(timeout=25000) as dl_info:
                clicked = False
                # Try common PDF button selectors
                for sel in [
                    "button:has-text('PDF')",
                    "a:has-text('PDF')",
                    "[title*='PDF']",
                    "[aria-label*='PDF']",
                    "[data-testid*='pdf']",
                    ".pdf",
                    "button[title='Download PDF']",
                    "[title='PDF']",
                ]:
                    try:
                        page.click(sel, timeout=4000)
                        logger.debug("Clicked PDF button via: %s", sel)
                        clicked = True
                        break
                    except Exception:
                        pass

                if not clicked:
                    # Scan all buttons/links for PDF text
                    for el in page.query_selector_all("button, a, [role='button']"):
                        try:
                            txt = (el.inner_text() or "").strip()
                            if txt.upper() == "PDF" or "download pdf" in txt.lower():
                                el.click()
                                logger.debug("Clicked by text: %r", txt)
                                clicked = True
                                break
                        except Exception:
                            pass

                if not clicked:
                    browser.close()
                    return None, (
                        f"PDF button not found on me.sap.com/notes/{note_number}. "
                        "The page may not have loaded fully, or the note may not have a PDF download."
                    )

            download = dl_info.value
            tmp = pathlib.Path(tempfile.mktemp(suffix=".pdf"))
            download.save_as(str(tmp))
            pdf_bytes = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            browser.close()

            if not pdf_bytes or len(pdf_bytes) < 500:
                return None, "Downloaded file is too small — may be empty or an error page."
            if pdf_bytes[:4] != b"%PDF":
                return None, f"Downloaded file is not a PDF (starts with {pdf_bytes[:20]!r})."

            logger.info("me.sap.com: Note %s downloaded (%d bytes)", note_number, len(pdf_bytes))
            return pdf_bytes, ""

    except Exception as exc:
        logger.exception("me.sap.com fetch error")
        return None, f"Browser-based download failed: {exc}"
