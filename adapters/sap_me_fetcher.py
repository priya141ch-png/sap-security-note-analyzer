"""
SAP Note fetcher via me.sap.com.
Runs Playwright in a subprocess so Streamlit stays responsive.
"""
from __future__ import annotations
import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# Playwright worker — written to a temp .py file and executed as subprocess
_WORKER = """
import os, sys, json, re, pathlib

def _lib():
    h = pathlib.Path.home()
    d = [str(h/"lib_deps"/"usr"/"lib"/"x86_64-linux-gnu"), str(h/"lib_deps"/"usr"/"lib")]
    e = os.environ.get("LD_LIBRARY_PATH","")
    os.environ["LD_LIBRARY_PATH"] = ":".join(d+([e] if e else []))
_lib()

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

s_user, s_pass, note, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
ARGS = ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"]
BASE = "https://me.sap.com"

api = {}
with sync_playwright() as pw:
    br = pw.chromium.launch(headless=True, args=ARGS)
    ctx = br.new_context()
    pg  = ctx.new_page()

    def grab(r):
        if "/backend/raw/sapnotes/Detail" in r.url:
            try: api["d"] = r.json()
            except: pass
    pg.on("response", grab)

    try: pg.goto(f"{BASE}/notes/{note}", wait_until="domcontentloaded", timeout=30000)
    except PwTimeout: pass

    if "accounts.sap.com" in pg.url:
        pg.wait_for_selector("#j_username", timeout=12000)
        pg.fill("#j_username", s_user)
        pg.click("#logOnFormSubmit", timeout=5000)
        pg.wait_for_selector("#j_password", timeout=15000)
        pg.fill("#j_password", s_pass)
        pg.click("#logOnFormSubmit", timeout=5000)
        try: pg.wait_for_function(
            "window.location.hostname.indexOf('accounts.sap.com')===-1", timeout=25000)
        except PwTimeout: pass

    try: pg.wait_for_load_state("networkidle", timeout=20000)
    except PwTimeout: pass

    if not api:
        try:
            r2 = pg.goto(f"{BASE}/backend/raw/sapnotes/Detail?q={note}",
                         wait_until="domcontentloaded", timeout=30000)
            if r2 and r2.ok:
                try: api["d"] = r2.json()
                except:
                    txt = pg.inner_text("body")
                    m = re.search(r"\\{.+\\}", txt, re.DOTALL)
                    if m: api["d"] = json.loads(m.group(0))
        except PwTimeout: pass

    br.close()

if api:
    pathlib.Path(out).write_text(json.dumps(api["d"]))
    sys.exit(0)
sys.exit(1)
"""


def _run_worker(s_user: str, s_password: str, note_number: str) -> Tuple[Optional[dict], str]:
    tmp = pathlib.Path(tempfile.mktemp(suffix=".json"))
    wf  = pathlib.Path(tempfile.mktemp(suffix=".py"))
    try:
        wf.write_text(_WORKER)
        result = subprocess.run(
            [sys.executable, str(wf), s_user, s_password, note_number, str(tmp)],
            timeout=150,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "")[-400:].strip()
            return None, f"Worker failed: {msg}"
        if not tmp.exists():
            return None, "Worker produced no output."
        return json.loads(tmp.read_text()), ""
    except subprocess.TimeoutExpired:
        return None, "Note fetch timed out (150s)."
    except Exception as exc:
        return None, str(exc)
    finally:
        tmp.unlink(missing_ok=True)
        wf.unlink(missing_ok=True)


def fetch_note_json_me(
    note_number: str, s_user: str, s_password: str
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Fetch SAP Note JSON from me.sap.com via subprocess Playwright."""
    logger.info("fetch_note_json_me start: note=%s", note_number)
    try:
        data, err = _run_worker(s_user, s_password, note_number)
        if err:
            logger.warning("fetch_note_json_me failed: %s", err)
            return None, err

        resp    = data.get("Response", {})
        api_err = resp.get("Error", {})
        if api_err and api_err.get("message"):
            return None, f"SAP API error: {api_err['message']}"

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
            "number":                  val(raw, "Header", "Number") or note_number,
            "title":                   val(raw, "Title"),
            "type":                    val(raw, "Header", "Type"),
            "version":                 val(raw, "Header", "Version"),
            "priority":                val(raw, "Header", "Priority"),
            "category":                val(raw, "Header", "Category"),
            "status":                  val(raw, "Header", "Status"),
            "released_on":             val(raw, "Header", "ReleasedOn"),
            "component_key":           val(raw, "Header", "SAPComponentKey"),
            "component_text":          val(raw, "Header", "SAPComponentKeyText"),
            "language":                val(raw, "Header", "Language"),
            "long_text_html":          val(raw, "LongText"),
            "validity_items":          items(raw, "Validity"),
            "support_packages":        items(raw, "SupportPackage"),
            "support_package_patches": items(raw, "SupportPackagePatch"),
            "correction_instructions": items(raw, "CorrectionInstructions"),
            "manual_actions_html":     val(raw, "ManualActions"),
            "references_to":           raw.get("References", {}).get("RefTo", {}).get("Items", []),
            "references_by":           raw.get("References", {}).get("RefBy", {}).get("Items", []),
            "preconditions":           items(raw, "Preconditions"),
            "attachments":             items(raw, "Attachments"),
            "pdf_print_url":           actions.get("Print", {}).get("url", ""),
            "snote_download_url":      actions.get("Download", {}).get("url", ""),
        }
        logger.info("fetch_note_json_me OK: %s %s", note_number, note_dict["title"][:50])
        return note_dict, ""

    except Exception as exc:
        logger.exception("fetch_note_json_me error")
        return None, f"me.sap.com fetch failed: {exc}"


def fetch_note_pdf_me(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[bytes], str]:
    return None, "PDF not available via me.sap.com; use fetch_note_json_me instead."


def fetch_note_html_me(note_number: str, s_user: str, s_password: str) -> Tuple[Optional[str], str]:
    note_dict, err = fetch_note_json_me(note_number, s_user, s_password)
    if err:
        return None, err
    html = note_dict.get("long_text_html", "")
    return (html, "") if html else (None, "No HTML content.")
