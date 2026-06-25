"""
Encrypted local note cache (AES-256 GCM).
Each run gets its own session directory so multi-user access doesn't conflict.
The cache key is NEVER stored in the project directory — only in user_data/.
"""

from __future__ import annotations
import json
import logging
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from core.domain_models import (
    NoteApplicabilityMatrixEntry,
    NotePrerequisite,
    SapSecurityNote,
)

logger = logging.getLogger(__name__)

_KEY_SIZE = 32   # AES-256


class CacheStorage:
    """Per-run encrypted note cache stored under user_data/cache/<session_id>/."""

    def __init__(self, base_dir: str | Path = "user_data/cache"):
        self._base = Path(base_dir)
        self._session_id = uuid.uuid4().hex[:12]
        self._dir = self._base / self._session_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._key = self._load_or_create_key()

    def _key_path(self) -> Path:
        return self._base / "cache.key"

    def _load_or_create_key(self) -> bytes:
        kp = self._key_path()
        if kp.exists():
            try:
                return kp.read_bytes()
            except OSError:
                pass
        key = get_random_bytes(_KEY_SIZE)
        kp.write_bytes(key)
        kp.chmod(0o600)
        return key

    def _encrypt(self, plaintext: bytes) -> bytes:
        cipher = AES.new(self._key, AES.MODE_GCM)
        ct, tag = cipher.encrypt_and_digest(plaintext)
        return cipher.nonce + tag + ct

    def _decrypt(self, blob: bytes) -> bytes:
        nonce, tag, ct = blob[:16], blob[16:32], blob[32:]
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ct, tag)

    def _note_path(self, note_number: str) -> Path:
        return self._dir / f"{note_number}.note"

    def save_note(self, note: SapSecurityNote) -> None:
        try:
            data = json.dumps(asdict(note)).encode()
            self._note_path(note.note_number).write_bytes(self._encrypt(data))
        except Exception as exc:
            logger.warning("Cache save failed for note %s: %s", note.note_number, exc)

    def load_note(self, note_number: str) -> Optional[SapSecurityNote]:
        path = self._note_path(note_number)
        if not path.exists():
            return None
        try:
            raw = self._decrypt(path.read_bytes())
            d = json.loads(raw)
            return _dict_to_note(d)
        except Exception as exc:
            logger.warning("Cache load failed for note %s: %s", note_number, exc)
            path.unlink(missing_ok=True)
            return None

    def list_cached_notes(self) -> List[str]:
        return [p.stem for p in self._dir.glob("*.note")]

    def delete_note(self, note_number: str) -> None:
        self._note_path(note_number).unlink(missing_ok=True)

    def clear_session(self) -> None:
        for p in self._dir.glob("*.note"):
            p.unlink(missing_ok=True)


def _dict_to_note(d: dict) -> SapSecurityNote:
    d["applicability_matrix"] = [NoteApplicabilityMatrixEntry(**e) for e in d.get("applicability_matrix", [])]
    d["prerequisites"] = [NotePrerequisite(**p) for p in d.get("prerequisites", [])]
    return SapSecurityNote(**d)
