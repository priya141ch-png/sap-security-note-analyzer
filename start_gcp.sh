#!/usr/bin/env bash
# GCP startup — Streamlit (8080) + Relay server (8081) + two Cloudflare tunnels
BASE="$HOME/sap-analyzer"
LOG="$BASE/logs"
mkdir -p "$LOG"

pkill -f "streamlit run ui/streamlit_app" 2>/dev/null || true
pkill -f "relay/server.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

cd "$BASE"
source .venv/bin/activate

nohup python relay/server.py > "$LOG/relay.log" 2>&1 &
echo "Relay server PID $! on port 8081"

nohup streamlit run ui/streamlit_app.py \
  --server.port 8080 --server.headless true --server.address 0.0.0.0 \
  > "$LOG/streamlit.log" 2>&1 &
echo "Streamlit PID $! on port 8080"

sleep 4

nohup "$HOME/bin/cloudflared" tunnel --url http://localhost:8080 --no-autoupdate > "$LOG/cf_ui.log" 2>&1 &
sleep 3
nohup "$HOME/bin/cloudflared" tunnel --url http://localhost:8081 --no-autoupdate > "$LOG/cf_relay.log" 2>&1 &

echo "Waiting for tunnel URLs..."
UI_URL=""; RELAY_URL=""
for i in $(seq 1 40); do
  sleep 1
  [ -z "$UI_URL" ]    && UI_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/cf_ui.log" 2>/dev/null | head -1)
  [ -z "$RELAY_URL" ] && RELAY_URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG/cf_relay.log" 2>/dev/null | head -1)
  [ -n "$UI_URL" ] && [ -n "$RELAY_URL" ] && break
done

printf "SAP Security Note Analyzer\nUI: %s\nRelay: %s\nStarted: %s\n" "$UI_URL" "$RELAY_URL" "$(date)" > "$BASE/URLS.txt"

echo "========================================"
echo "  UI   : $UI_URL"
echo "  Relay: $RELAY_URL"
echo "  Saved to: $BASE/URLS.txt"
echo "========================================"
