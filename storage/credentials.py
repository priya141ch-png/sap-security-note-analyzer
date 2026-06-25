"""
Secure RFC credential storage — per-user workspace namespaced.

Passwords are encrypted with Fernet (AES-128-CBC + HMAC-SHA256).
Profiles are stored under user_data/workspaces/{workspace_id}/profiles/
so no two users share data even on the same server.

Master key sources (in priority order):
  1. SAP_RFC_MASTER_KEY environment variable (base64-encoded 32-byte key)
  2. Docker secret /run/secrets/sap_master_key
  3. Auto-generated and stored per workspace in profiles/.master.key
"""

from __future__ import annotations
import base64
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from cryptography.fernet import Fernet, InvalidToken

from core.domain_models import RfcProfile

logger = logging.getLogger(__name__)

_DOCKER_SECRET = Path("/run/secrets/sap_master_key")


def _profiles_dir() -> Path:
    """Return workspace-namespaced profiles directory."""
    try:
        from storage.user_store import workspace_dir
        return workspace_dir("profiles")
    except Exception:
        p = Path("user_data/profiles")
        p.mkdir(parents=True, exist_ok=True)
        return p


def _profiles_file() -> Path:
    return _profiles_dir() / "profiles.json"


def _key_file() -> Path:
    return _profiles_dir() / ".master.key"


def _suser_file() -> Path:
    return _profiles_dir() / "suser.json"


# ── Master key management ─────────────────────────────────────────────────────

def _load_master_key() -> bytes:
    # 1. Environment variable
    env_key = os.environ.get("SAP_RFC_MASTER_KEY", "")
    if env_key:
        try:
            return base64.urlsafe_b64decode(env_key.encode())
        except Exception:
            logger.warning("SAP_RFC_MASTER_KEY env var is not valid base64 — ignoring")

    # 2. Docker secret
    if _DOCKER_SECRET.exists():
        try:
            return base64.urlsafe_b64decode(_DOCKER_SECRET.read_bytes().strip())
        except Exception:
            logger.warning("Docker secret /run/secrets/sap_master_key is invalid — ignoring")

    # 3. Local key file (workspace-namespaced)
    kf = _key_file()
    if kf.exists():
        key = kf.read_bytes()
        if len(key) == 44:   # Fernet key is 32 bytes → 44 base64 chars
            return key
    # Generate and save
    key = Fernet.generate_key()
    kf.write_bytes(key)
    try:
        kf.chmod(0o600)
    except Exception:
        pass
    logger.info("Generated new master key at %s", kf)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_master_key())


# ── Encrypt / decrypt ─────────────────────────────────────────────────────────

def encrypt_password(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Cannot decrypt RFC password — the master key may have changed. "
            "Re-enter the password for this profile."
        ) from exc


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def _load_raw() -> List[dict]:
    pf = _profiles_file()
    if not pf.exists():
        return []
    try:
        return json.loads(pf.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_raw(profiles: List[dict]) -> None:
    _profiles_file().write_text(json.dumps(profiles, indent=2), encoding="utf-8")


def list_profiles() -> List[RfcProfile]:
    return [_dict_to_profile(p) for p in _load_raw()]


def get_profile(name: str) -> Optional[RfcProfile]:
    for p in _load_raw():
        if p.get("name") == name:
            return _dict_to_profile(p)
    return None


def save_profile(profile: RfcProfile) -> None:
    profiles = _load_raw()
    existing = [p for p in profiles if p.get("name") != profile.name]
    existing.append(asdict(profile))
    _save_raw(existing)
    logger.info("Profile saved: %s", profile.name)


def delete_profile(name: str) -> None:
    profiles = [p for p in _load_raw() if p.get("name") != name]
    _save_raw(profiles)
    logger.info("Profile deleted: %s", name)


def update_test_result(name: str, ok: bool) -> None:
    profiles = _load_raw()
    for p in profiles:
        if p.get("name") == name:
            p["last_tested"] = datetime.now().isoformat(timespec="seconds")
            p["last_test_ok"] = ok
    _save_raw(profiles)


# ── S-user credentials (for SAP Support Portal online note fetch) ─────────────

def save_suser(s_user: str, s_password: str) -> None:
    """Save SAP S-user credentials encrypted (workspace-namespaced)."""
    data = {"s_user": s_user, "s_password_enc": encrypt_password(s_password)}
    _suser_file().write_text(json.dumps(data), encoding="utf-8")
    logger.info("S-user credentials saved (encrypted)")


def load_suser() -> tuple[str, str]:
    """Return (s_user, plain_password) or ('', '') if not configured."""
    sf = _suser_file()
    if not sf.exists():
        return "", ""
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
        return data.get("s_user", ""), decrypt_password(data.get("s_password_enc", ""))
    except Exception as exc:
        logger.warning("Could not load S-user credentials: %s", exc)
        return "", ""


def delete_suser() -> None:
    sf = _suser_file()
    if sf.exists():
        sf.unlink()


# ── Helper ────────────────────────────────────────────────────────────────────

def _dict_to_profile(d: dict) -> RfcProfile:
    return RfcProfile(
        name=d.get("name", ""),
        host=d.get("host", ""),
        sysnr=d.get("sysnr", "00"),
        client=d.get("client", "000"),
        user=d.get("user", ""),
        password_enc=d.get("password_enc", ""),
        lang=d.get("lang", "EN"),
        timeout=d.get("timeout", 30),
        description=d.get("description", ""),
        created_at=d.get("created_at", ""),
        last_tested=d.get("last_tested", ""),
        last_test_ok=d.get("last_test_ok", False),
    )
