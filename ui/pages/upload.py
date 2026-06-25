"""Upload & Analyze — the fully automated single-page workflow."""

from __future__ import annotations
import logging
import tempfile
import time
from pathlib import Path

import streamlit as st

from adapters.note_parser import parse_note
from adapters.pdf_note_parser import parse_note_pdf
from adapters.system_info_parser import (
    infer_environment,
    load_landscape_from_files,
    load_landscape_from_zip,
)
from core.applicability_engine import evaluate_note_for_landscape
from core.future_risk import compute_sid_risk_summaries
from storage.cache_storage import CacheStorage
from ui.components import section, show_validation
from ui.run_history import save_run

logger = logging.getLogger(__name__)


def _session_tmp() -> Path:
    key = "session_tmp_dir"
    if key not in st.session_state:
        tmp = Path(tempfile.mkdtemp(prefix="sap_analyzer_"))
        st.session_state[key] = str(tmp)
    return Path(st.session_state[key])


def _parse_env_overrides(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip().upper()] = v.strip().upper()
    return result


def render() -> None:
    st.title("Upload & Analyze")
    st.caption("Upload your landscape and notes — the pipeline runs automatically.")

    # ── Step 1: Landscape ────────────────────────────────────────────────────
    section("Step 1 — SAP Landscape")

    col_xml, col_zip = st.columns(2)
    with col_xml:
        xml_uploads = st.file_uploader(
            "Upload XML files (one per system / SID)",
            type=["xml"], accept_multiple_files=True, key="xml_uploads",
        )
    with col_zip:
        zip_upload = st.file_uploader(
            "Or upload a ZIP of XML files",
            type=["zip"], key="zip_upload",
        )

    with st.expander("Environment overrides (optional)"):
        st.caption("Override the auto-detected DEV / QAS / PROD per SID.")
        env_raw = st.text_area("One SID=ENV per line  e.g.  S4P=PROD", height=70,
                               key="env_overrides")

    # ── Step 2: Notes ────────────────────────────────────────────────────────
    section("Step 2 — SAP Security Notes")
    note_uploads = st.file_uploader(
        "Upload SAP Note files (PDF or HTML print-view)",
        type=["pdf", "html", "htm"], accept_multiple_files=True, key="note_uploads",
    )

    # ── Run button ───────────────────────────────────────────────────────────
    st.divider()
    if not (xml_uploads or zip_upload) or not note_uploads:
        st.info("Upload at least one landscape XML/ZIP **and** one or more note files to continue.")

    run_btn = st.button(
        "▶  Run Full Analysis",
        type="primary",
        disabled=not ((xml_uploads or zip_upload) and note_uploads),
        use_container_width=True,
    )

    if run_btn:
        _run_pipeline(xml_uploads, zip_upload, note_uploads, env_raw)


def _run_pipeline(xml_uploads, zip_upload, note_uploads, env_raw: str) -> None:
    env_overrides = _parse_env_overrides(env_raw)
    status_box = st.empty()
    prog = st.progress(0.0)

    # ── 1. Parse landscape ───────────────────────────────────────────────────
    status_box.info("⏳ Parsing landscape…")
    try:
        if xml_uploads:
            xml_files = [(f.name, f.read()) for f in xml_uploads]
            landscape = load_landscape_from_files(xml_files)
        else:
            tmp = _session_tmp() / "landscape"
            tmp.mkdir(parents=True, exist_ok=True)
            landscape = load_landscape_from_zip(zip_upload.read(), tmp)

        for s in landscape.systems:
            if s.sid in env_overrides:
                s.environment = env_overrides[s.sid]
            elif not s.environment:
                s.environment = infer_environment(s.sid)

    except Exception as exc:
        st.error(f"Landscape parse failed: {exc}")
        logger.exception("Landscape parse error")
        return

    if not landscape.systems:
        st.error("No systems found in the uploaded files. Check the XML format.")
        return

    prog.progress(0.20, text=f"Parsed {len(landscape.systems)} system(s)")

    # ── 2. Parse notes ───────────────────────────────────────────────────────
    status_box.info("⏳ Parsing security notes…")
    cache = CacheStorage(base_dir=_session_tmp() / "cache")
    notes = []
    parse_errors = []

    for i, f in enumerate(note_uploads):
        data = f.read()
        try:
            note = parse_note_pdf(data, f.name) if f.name.lower().endswith(".pdf") \
                else parse_note(data, f.name)
            if note:
                cache.save_note(note)
                notes.append(note)
            else:
                parse_errors.append(f.name)
        except Exception as exc:
            parse_errors.append(f"{f.name} ({exc})")
            logger.exception("Note parse error: %s", f.name)

        prog.progress(0.20 + 0.30 * (i + 1) / len(note_uploads),
                      text=f"Parsed note {i+1}/{len(note_uploads)}")

    if parse_errors:
        st.warning(f"Could not parse {len(parse_errors)} file(s): {', '.join(parse_errors)}")

    if not notes:
        st.error("No notes were successfully parsed.")
        return

    prog.progress(0.50, text=f"Parsed {len(notes)} note(s)")

    # ── 3. Run applicability analysis ────────────────────────────────────────
    status_box.info("⏳ Running applicability analysis…")
    results = []
    for i, note in enumerate(notes):
        results.extend(evaluate_note_for_landscape(note, landscape))
        prog.progress(0.50 + 0.35 * (i + 1) / len(notes),
                      text=f"Analysed note {note.note_number}  ({i+1}/{len(notes)})")

    # ── 4. Compute risk ──────────────────────────────────────────────────────
    status_box.info("⏳ Computing risk scores…")
    env_map = {s.sid: s.environment for s in landscape.systems}
    risk = compute_sid_risk_summaries(notes, results, env_map)
    prog.progress(0.95, text="Saving run history…")

    # ── 5. Save & store ──────────────────────────────────────────────────────
    run_id = save_run(landscape, notes, results, risk)
    st.session_state.update({
        "landscape": landscape,
        "notes": notes,
        "results": results,
        "risk": risk,
        "last_run_id": run_id,
    })

    prog.progress(1.0, text="Done")
    status_box.empty()

    # ── Summary banner ───────────────────────────────────────────────────────
    applicable = sum(1 for r in results if r.status == "Applicable")
    not_app    = sum(1 for r in results if r.status == "Not Applicable")
    manual     = sum(1 for r in results if r.status == "Needs Manual Review")

    st.success(
        f"✅  Analysis complete (Run ID: `{run_id}`)  —  "
        f"**{applicable}** applicable · **{not_app}** not applicable · **{manual}** need review"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Systems", len(landscape.systems))
    c2.metric("Notes", len(notes))
    c3.metric("Evaluations", len(results))

    show_validation(landscape, notes)

    st.info("Navigate to **Dashboard**, **Results**, or **Reports** using the sidebar.")
