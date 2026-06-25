"""
Per-user workspace management.

Each browser gets a unique 8-character Workspace ID stored in browser localStorage.
All server-side data (RFC profiles, note cache) is namespaced under that ID,
so no two users ever see each other's data even if they share the same URL.

Device migration:  export workspace → download .sap-backup → import on new device.
Local mode:        workspace ID is stored in a local file instead of localStorage.
"""
from __future__ import annotations
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_USER_DATA_ROOT = Path("user_data/workspaces")
_SESSION_KEY    = "_workspace_id"


# ── Session helpers ───────────────────────────────────────────────────────────

def get_workspace_id() -> Optional[str]:
    """Return workspace ID from Streamlit session_state (set by init_workspace)."""
    try:
        import streamlit as st
        return st.session_state.get(_SESSION_KEY)
    except Exception:
        return None


def set_workspace_id(wid: str) -> None:
    """Persist workspace ID into Streamlit session_state."""
    try:
        import streamlit as st
        st.session_state[_SESSION_KEY] = wid
    except Exception:
        pass


def new_workspace_id() -> str:
    """Generate a short, human-readable 8-char workspace ID."""
    return str(uuid.uuid4()).replace("-", "")[:8].upper()


# ── Path helpers ──────────────────────────────────────────────────────────────

def workspace_dir(sub: str = "") -> Path:
    """
    Return the namespaced data directory for the current workspace.
    Falls back to 'default' if no workspace is set (local / CLI mode).
    """
    wid = get_workspace_id() or "default"
    p = _USER_DATA_ROOT / wid / sub if sub else _USER_DATA_ROOT / wid
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Export / Import ───────────────────────────────────────────────────────────

def export_workspace() -> bytes:
    """
    Serialize the current workspace into a portable JSON backup.
    Returns UTF-8 bytes (JSON). The caller may encrypt before sending to browser.
    """
    wid = get_workspace_id()
    if not wid:
        return json.dumps({"workspace_id": "", "files": {}}).encode()

    out: dict = {}
    wdir = _USER_DATA_ROOT / wid
    if wdir.exists():
        for f in sorted(wdir.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                rel = str(f.relative_to(wdir)).replace("\\", "/")
                try:
                    out[rel] = f.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning("Skipping %s during export: %s", f, exc)

    payload = {"workspace_id": wid, "version": 1, "files": out}
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def import_workspace(backup_bytes: bytes) -> str:
    """
    Restore workspace data from backup bytes.
    Writes files into the workspace dir named by the backup's workspace_id.
    Returns the restored workspace ID (caller should update localStorage + session).
    Raises ValueError on invalid backup.
    """
    try:
        payload = json.loads(backup_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid backup file: {exc}") from exc

    wid = payload.get("workspace_id", "").strip()
    if not wid:
        raise ValueError("Backup file has no workspace_id.")

    files: dict = payload.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("Backup file has unexpected format.")

    wdir = _USER_DATA_ROOT / wid
    wdir.mkdir(parents=True, exist_ok=True)

    for rel_path, content in files.items():
        # Safety: don't allow path traversal
        safe = Path(rel_path).name if ".." in rel_path else rel_path
        target = (wdir / safe).resolve()
        if not str(target).startswith(str(wdir.resolve())):
            continue  # skip anything that tries to escape the workspace dir
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(str(content), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not restore %s: %s", rel_path, exc)

    logger.info("Workspace %s restored (%d files)", wid, len(files))
    return wid


def delete_workspace(wid: str) -> None:
    """Permanently delete all data for a workspace ID."""
    import shutil
    wdir = _USER_DATA_ROOT / wid
    if wdir.exists():
        shutil.rmtree(wdir)
        logger.info("Workspace %s deleted", wid)
