"""
RFC Connector — wraps pyrfc with graceful fallback when SDK is not installed.

PYRFC INSTALLATION (required for live SAP connectivity):
  1. Download SAP NetWeaver RFC SDK 7.50 from:
     https://support.sap.com/en/product/connectors/nwrfcsdk.html
     (free download, requires SAP S-user ID)
  2. Extract to a fixed path, e.g. C:/nwrfcsdk  or  /usr/local/sap/nwrfcsdk
  3. Set env var:  SAPNWRFC_HOME=<path>
  4. pip install pyrfc

  Docker: copy the SDK into the image — see Dockerfile for details.

If pyrfc is NOT installed the app still runs but live RFC checks are disabled.
"""

from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Optional pyrfc import ─────────────────────────────────────────────────────

try:
    import pyrfc                        # type: ignore
    from pyrfc import Connection, RFCError, ExternalRuntimeError  # type: ignore
    PYRFC_AVAILABLE = True
    logger.info("pyrfc loaded successfully — live RFC mode enabled")
except ImportError:
    PYRFC_AVAILABLE = False
    logger.warning(
        "pyrfc not found — live RFC calls disabled. "
        "Install SAP NW RFC SDK + pyrfc to enable live connectivity."
    )

PYRFC_INSTALL_INSTRUCTIONS = """
**pyrfc / SAP NW RFC SDK not installed.**

To enable live SAP RFC connectivity:

1. Download SAP NetWeaver RFC SDK 7.50 from:
   https://support.sap.com/en/product/connectors/nwrfcsdk.html
   (Requires SAP S-user ID — free of charge)

2. Extract the SDK:
   - Windows: `C:\\nwrfcsdk`
   - Linux: `/usr/local/sap/nwrfcsdk`

3. Set environment variable:
   - Windows: `set SAPNWRFC_HOME=C:\\nwrfcsdk`
   - Linux: `export SAPNWRFC_HOME=/usr/local/sap/nwrfcsdk`
   - Add to PATH: the `lib` subfolder

4. Install pyrfc:
   ```
   pip install pyrfc
   ```

5. Restart the application.

**Docker / VM:** Copy the SDK into the Docker image before building.
See `Dockerfile` for exact instructions.
"""


# ── RFC Error types ───────────────────────────────────────────────────────────

class RfcConnectError(Exception):
    """Raised when RFC connection cannot be established."""

class RfcCallError(Exception):
    """Raised when an RFC function call fails."""

class RfcNotAvailableError(Exception):
    """Raised when pyrfc / NW RFC SDK is not installed."""


# ── Connection wrapper ────────────────────────────────────────────────────────

class SapRfcConnection:
    """
    Thin wrapper around pyrfc.Connection.
    Handles connection lifecycle, timeout, and structured error reporting.
    """

    def __init__(self, host: str, sysnr: str, client: str, user: str,
                 password: str, lang: str = "EN", timeout: int = 30):
        if not PYRFC_AVAILABLE:
            raise RfcNotAvailableError(PYRFC_INSTALL_INSTRUCTIONS)

        self._params = dict(
            ashost=host,
            sysnr=sysnr,
            client=client,
            user=user,
            passwd=password,
            lang=lang,
        )
        self._timeout = timeout
        self._conn: Optional[Any] = None

    def connect(self) -> None:
        try:
            self._conn = pyrfc.Connection(**self._params)
            logger.info("RFC connected to %s SY%s", self._params["ashost"], self._params["sysnr"])
        except Exception as exc:
            raise RfcConnectError(f"Cannot connect to SAP: {exc}") from exc

    def call(self, fm_name: str, **kwargs) -> Dict[str, Any]:
        if self._conn is None:
            raise RfcConnectError("Not connected. Call connect() first.")
        try:
            return self._conn.call(fm_name, **kwargs)
        except Exception as exc:
            logger.warning("RFC call %s failed: %s", fm_name, exc)
            raise RfcCallError(f"RFC call {fm_name} failed: {exc}") from exc

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "SapRfcConnection":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ── Public helpers ────────────────────────────────────────────────────────────

def build_connection(profile_dict: dict, plain_password: str) -> SapRfcConnection:
    """Build a SapRfcConnection from a profile dict and decrypted password."""
    return SapRfcConnection(
        host=profile_dict["host"],
        sysnr=profile_dict["sysnr"],
        client=profile_dict["client"],
        user=profile_dict["user"],
        password=plain_password,
        lang=profile_dict.get("lang", "EN"),
        timeout=profile_dict.get("timeout", 30),
    )


# ── Relay helpers (used when pyrfc not available on server) ───────────────────

RELAY_SERVER_URL = os.environ.get("RFC_RELAY_URL", "http://localhost:8081")
_RELAY_TIMEOUT = 90  # seconds to wait for relay client to respond


def is_relay_connected() -> bool:
    """Return True if a relay client is currently polling the relay server."""
    try:
        import requests as _req
        r = _req.get(f"{RELAY_SERVER_URL}/relay/status", timeout=2)
        return r.json().get("relay_connected", False)
    except Exception:
        return False


def relay_call(call_type: str, profile_dict: dict, plain_password: str, **extra) -> dict:
    """
    Send an RFC request to the relay server and wait for the relay client to execute it.
    Returns the result dict from the relay client.
    Extra kwargs (e.g. note_number=) are merged into the payload.
    """
    import requests as _req
    import time

    payload = {
        "type": call_type,
        "profile": {
            "host": profile_dict["host"],
            "sysnr": profile_dict["sysnr"],
            "client": profile_dict["client"],
            "user": profile_dict["user"],
            "password": plain_password,
            "lang": profile_dict.get("lang", "EN"),
        },
        **extra,
    }

    # Submit request
    r = _req.post(f"{RELAY_SERVER_URL}/relay/request", json=payload, timeout=10)
    r.raise_for_status()
    request_id = r.json()["request_id"]

    # Poll for result
    deadline = time.time() + _RELAY_TIMEOUT
    while time.time() < deadline:
        r = _req.get(f"{RELAY_SERVER_URL}/relay/result/{request_id}", timeout=5)
        data = r.json()
        if data.get("ready"):
            return data["result"]
        time.sleep(1)

    raise TimeoutError("Relay client did not respond within timeout. Is relay.bat running on a VPN-connected machine?")


def test_connection(profile_dict: dict, plain_password: str) -> tuple[bool, str]:
    """
    Test RFC connection. Returns (success: bool, message: str).
    Calls RFC_PING — available on all SAP systems without special authorization.
    """
    # Try relay first if pyrfc is not available locally
    if not PYRFC_AVAILABLE:
        if is_relay_connected():
            try:
                result = relay_call("ping", profile_dict, plain_password)
                if result.get("ok"):
                    sid = result.get("sid", "")
                    rel = result.get("release", "")
                    return True, f"Connection successful via Relay — SID: {sid}  Release: {rel}"
                return False, f"Relay RFC failed: {result.get('error', 'Unknown error')}"
            except Exception as exc:
                return False, f"Relay error: {exc}"
        return False, (
            "**RFC not available.** \n\n"
            "No direct pyrfc and no relay client connected.\n\n"
            "**To enable RFC:** Connect to office VPN and double-click `relay\\relay.bat` "
            "on your laptop, then try again."
        )

    try:
        with build_connection(profile_dict, plain_password) as conn:
            conn.call("RFC_PING")
        return True, "Connection successful — RFC_PING responded."
    except RfcConnectError as exc:
        return False, f"Connection failed: {exc}"
    except RfcCallError as exc:
        return False, f"Connected but RFC_PING failed: {exc}"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def read_table(
    conn: SapRfcConnection,
    table: str,
    fields: List[str],
    where: Optional[List[str]] = None,
    max_rows: int = 5000,
) -> List[Dict[str, str]]:
    """
    Call RFC_READ_TABLE and return parsed rows as list of dicts.
    Uses '|' delimiter for reliable field splitting.
    """
    delimiter = "|"
    options = [{"TEXT": w} for w in (where or [])]
    field_params = [{"FIELDNAME": f} for f in fields]

    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE=table,
        DELIMITER=delimiter,
        NO_DATA="",
        ROWCOUNT=max_rows,
        FIELDS=field_params,
        OPTIONS=options,
    )

    # Parse DATA rows using FIELDS metadata
    field_meta = result.get("FIELDS", [])
    parsed_fields = [f["FIELDNAME"] for f in field_meta]

    rows: List[Dict[str, str]] = []
    for data_row in result.get("DATA", []):
        raw = data_row.get("WA", "")
        parts = raw.split(delimiter)
        row_dict = {
            parsed_fields[i]: parts[i].strip() if i < len(parts) else ""
            for i in range(len(parsed_fields))
        }
        rows.append(row_dict)

    return rows
