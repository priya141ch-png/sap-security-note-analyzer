#!/usr/bin/env bash
# GCP startup — Streamlit (8080, permanent ngrok domain) + Relay server (8081, Cloudflare tunnel)
BASE="$HOME/sap-analyzer"
LOG="$BASE/logs"
NGROK_DOMAIN="diffusive-knee-handwork.ngrok-free.dev"
mkdir -p "$LOG"

pkill -f "streamlit run ui/streamlit_app" 2>/dev/null || true
# relay/server.py is managed by systemd — do not pkill it
pkill -f "cloudflared tunnel" 2>/dev/null || true
pkill -f "ngrok http" 2>/dev/null || true
sleep 1

cd "$BASE"
source .venv/bin/activate
# Load VM-only secrets (never committed to git)
[ -f "$HOME/.sap_env" ] && source "$HOME/.sap_env"

# Relay managed by systemd (sap-relay.service) — do not start here


nohup streamlit run ui/streamlit_app.py \
  --server.port 8080 --server.headless true --server.address 0.0.0.0 \
  --server.enableStaticServing true \
  > "$LOG/streamlit.log" 2>&1 &
echo "Streamlit PID $! on port 8080"

sleep 4

# UI: Cloudflare tunnel (VPN-friendly, changes on restart) + ngrok (permanent)
nohup "$HOME/bin/cloudflared" tunnel --url http://localhost:8080 --no-autoupdate > "$LOG/cf_ui.log" 2>&1 &
echo "Cloudflare UI tunnel PID $!"

# Also keep ngrok running (permanent domain, for non-VPN access)
nohup "$HOME/bin/ngrok" http 8080 --url="$NGROK_DOMAIN" > "$LOG/ngrok_ui.log" 2>&1 &
echo "ngrok UI tunnel PID $! -> https://$NGROK_DOMAIN"

# Relay: Cloudflare quick tunnel
sleep 2
nohup "$HOME/bin/cloudflared" tunnel --url http://localhost:8081 --no-autoupdate > "$LOG/cf_relay.log" 2>&1 &

echo "Waiting for tunnel URLs..."
CF_UI_URL=""
RELAY_URL=""
for i in $(seq 1 50); do
  sleep 1
  [ -z "$CF_UI_URL" ]  && CF_UI_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/cf_ui.log"    2>/dev/null | head -1)
  [ -z "$RELAY_URL" ]  && RELAY_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/cf_relay.log" 2>/dev/null | head -1)
  [ -n "$CF_UI_URL" ] && [ -n "$RELAY_URL" ] && break
done

UI_URL="${CF_UI_URL:-https://$NGROK_DOMAIN}"
printf "SAP Security Note Analyzer
UI (Cloudflare): %s
UI (ngrok): https://%s
Relay: %s
Started: %s
" "$CF_UI_URL" "$NGROK_DOMAIN" "$RELAY_URL" "$(date)" > "$BASE/URLS.txt"
printf "SAP Security Note Analyzer\nUI: %s\nRelay: %s\nStarted: %s\n" "$UI_URL" "$RELAY_URL" "$(date)" > "$BASE/URLS.txt"

# Push relay URL to GitHub Gist so relay client can auto-discover it
# Gist ID is permanent — raw URL never changes across GCP restarts
GIST_ID="29120e8c133492f893b2b6a65158532a"
# GITHUB_TOKEN must be set in ~/.bashrc on the VM — never stored in this file
python3 - <<PYEOF
import json, urllib.request, os
# Read token from VM-only env file (not in git)
token = os.environ.get("GITHUB_TOKEN", "")
if not token:
    env_file = os.path.expanduser("~/.sap_env")
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("GITHUB_TOKEN="):
                token = line.strip().split("=", 1)[1]
relay_url = "$RELAY_URL"
payload = json.dumps({
    "files": {
        "relay.json": {
            "content": json.dumps({"relay_url": relay_url, "updated": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"})
        }
    }
}).encode()
req = urllib.request.Request(
    "https://api.github.com/gists/$GIST_ID",
    data=payload,
    method="PATCH",
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
)
with urllib.request.urlopen(req) as resp:
    print("Discovery gist updated OK")
PYEOF

echo "========================================"
echo "  UI   : $UI_URL   (permanent)"
echo "  Relay: $RELAY_URL   (changes on restart)"
echo "  Saved to: $BASE/URLS.txt"
echo "========================================"
