"""
RFC Relay Client — runs silently on the user's laptop (auto-started at login).
Polls GCP relay server for RFC requests and executes them locally via pyrfc.

Auto-start: registered in Windows Task Scheduler by install_autostart.ps1
Manual run: python relay/client.py [relay_url]
"""
import sys
import time
import json
import dataclasses
import os as _os
import logging

# ── Logging — writes to relay/relay_client.log so there's no visible window ──
_log_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "relay_client.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(_log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── Config ────────────────────────────────────────────────────────────────────
# Permanent URL that never changes — used to discover the (possibly changing) relay URL
DISCOVERY_URL  = "https://gist.githubusercontent.com/priya141ch-png/29120e8c133492f893b2b6a65158532a/raw/relay.json"
POLL_INTERVAL  = 2        # seconds between polls
RETRY_BACKOFF  = 30       # seconds to wait after repeated connection failures
MAX_ERRORS_BEFORE_BACKOFF = 5
REDISCOVER_INTERVAL = 60  # seconds between re-checking the relay URL for changes


def _discover_relay_url(fallback: str) -> str:
    """Fetch the current relay URL from the permanent discovery endpoint."""
    try:
        r = requests.get(DISCOVERY_URL, timeout=10)
        r.raise_for_status()
        url = r.json().get("relay_url", "").strip()
        if url and url.startswith("http"):
            return url
    except Exception as exc:
        log.debug(f"Discovery endpoint unreachable: {exc}")
    return fallback


# Priority: command-line arg → env var → auto-discover
_cli_url  = sys.argv[1] if len(sys.argv) > 1 else ""
_env_url  = _os.environ.get("SAP_RELAY_URL", "")
_default  = _cli_url or _env_url or ""   # empty = will auto-discover on startup
RELAY_URL = _default  # resolved in run()


def _to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


def _execute(request: dict) -> dict:
    """Execute one RFC request locally using pyrfc."""
    try:
        project_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from rfc.connector import SapRfcConnection, PYRFC_AVAILABLE
        if not PYRFC_AVAILABLE:
            return {"ok": False, "error": "pyrfc not installed on this machine."}

        profile = request.get("profile", {})
        conn = SapRfcConnection(
            host=profile["host"],
            sysnr=profile["sysnr"],
            client=profile["client"],
            user=profile["user"],
            password=profile["password"],
            lang=profile.get("lang", "EN"),
        )
        conn.connect()
        call_type = request.get("type")

        if call_type == "ping":
            conn.call("RFC_PING")
            sysinfo = conn.call("RFC_SYSTEM_INFO")
            rfcsi = sysinfo.get("RFCSI_EXPORT", {})
            conn.close()
            return {"ok": True,
                    "sid": rfcsi.get("RFCSYSID", "").strip(),
                    "release": rfcsi.get("RFCSAPRL", "").strip()}

        elif call_type == "system_info":
            from rfc.system_collector import collect_system_info
            info = collect_system_info(conn)
            conn.close()
            return {"ok": True, "data": _to_dict(info)}

        elif call_type == "implemented_notes":
            from rfc.notes_checker import fetch_implemented_notes
            notes, err = fetch_implemented_notes(conn)
            conn.close()
            return {"ok": True, "data": notes, "error": err}

        elif call_type == "fetch_note":
            from rfc.note_fetcher import fetch_note_from_system
            note_number = request.get("note_number", "")
            note_dict, err = fetch_note_from_system(conn, note_number)
            conn.close()
            return {"ok": bool(note_dict), "data": note_dict, "error": err}

        else:
            conn.close()
            return {"ok": False, "error": f"Unknown request type: {call_type}"}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run():
    log.info("=" * 55)
    log.info("  SAP Security Note Analyzer — RFC Relay Client")
    log.info("=" * 55)
    log.info(f"  Discovery : {DISCOVERY_URL}")
    log.info(f"  Log file  : {_log_path}")
    log.info("  Running silently. Auto-discovers relay URL on every GCP restart.")

    # Resolve starting relay URL
    relay_url = _default or _discover_relay_url("")
    if not relay_url:
        log.warning("Could not discover relay URL at startup — will retry every 30s.")
    else:
        log.info(f"  Relay URL : {relay_url}")

    consecutive_errors = 0
    last_rediscover    = time.time()

    while True:
        # ── Periodically re-discover relay URL (handles GCP restarts) ─────────
        now = time.time()
        if now - last_rediscover >= REDISCOVER_INTERVAL:
            new_url = _discover_relay_url(relay_url)
            last_rediscover = now
            if new_url and new_url != relay_url:
                log.info(f"Relay URL updated: {relay_url} → {new_url}")
                relay_url = new_url
                consecutive_errors = 0  # reset errors on URL change

        if not relay_url:
            time.sleep(RETRY_BACKOFF)
            relay_url = _discover_relay_url("")
            continue

        try:
            r = requests.get(f"{relay_url}/relay/poll", timeout=8)
            r.raise_for_status()
            items = r.json().get("requests", [])
            consecutive_errors = 0

            for item in items:
                rid   = item["request_id"]
                req   = item["request"]
                rtype = req.get("type", "?")
                host  = req.get("profile", {}).get("host", "?")
                log.info(f"RFC {rtype.upper()} → {host} ...")
                result = _execute(req)
                requests.post(f"{relay_url}/relay/result/{rid}", json=result, timeout=10)
                if result.get("ok"):
                    log.info(f"  ✓ done — {result.get('sid', '')}")
                else:
                    log.warning(f"  ✗ failed — {result.get('error', '')[:120]}")

            # Heartbeat every 5 minutes
            if int(time.time()) % 300 < POLL_INTERVAL:
                log.info("Relay heartbeat — waiting for RFC requests...")

        except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError):
            consecutive_errors += 1
            if consecutive_errors <= MAX_ERRORS_BEFORE_BACKOFF:
                log.warning(f"Cannot reach relay ({relay_url}). Retrying in {POLL_INTERVAL}s...")
            elif consecutive_errors == MAX_ERRORS_BEFORE_BACKOFF + 1:
                log.warning(f"Relay unreachable after {consecutive_errors} attempts — "
                            f"backing off to {RETRY_BACKOFF}s intervals. "
                            f"(Normal if not on VPN — will reconnect automatically when VPN is active.)")
                time.sleep(RETRY_BACKOFF)
                # Force immediate rediscover on next iteration
                last_rediscover = 0
                continue

        except KeyboardInterrupt:
            log.info("Relay stopped manually.")
            break
        except Exception as exc:
            consecutive_errors += 1
            log.warning(f"Unexpected error: {exc}")

        time.sleep(RETRY_BACKOFF if consecutive_errors > MAX_ERRORS_BEFORE_BACKOFF else POLL_INTERVAL)


if __name__ == "__main__":
    run()
