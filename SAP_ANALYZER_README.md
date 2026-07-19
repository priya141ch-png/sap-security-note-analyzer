# SAP Security Note Analyzer

**Version:** 1.0 (Save Point — July 2026)  
**Author:** Panchamukesh Chandaka  
**Live URL:** https://diffusive-knee-handwork.ngrok-free.dev  
**Repository:** https://github.com/priya141ch-png/sap-security-note-analyzer

---

## Table of Contents

1. [What This Application Does](#1-what-this-application-does)
2. [Architecture Overview](#2-architecture-overview)
3. [Pre-Requirements](#3-pre-requirements)
4. [Project Structure](#4-project-structure)
5. [Design & Key Components](#5-design--key-components)
6. [Development Journey](#6-development-journey)
7. [Deployment — GCP VM](#7-deployment--gcp-vm)
8. [Deployment — Local (Windows)](#8-deployment--local-windows)
9. [Relay Client Setup (VPN Laptop)](#9-relay-client-setup-vpn-laptop)
10. [Git Workflow](#10-git-workflow)
11. [Running & Operating](#11-running--operating)
12. [Security Notes](#12-security-notes)
13. [Known Limitations & Parking Notes](#13-known-limitations--parking-notes)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. What This Application Does

A **web-based SAP Security Note applicability analyzer** that:

- **Downloads SAP Security Notes** from me.sap.com using your SAP S-user credentials (Playwright headless browser — bypasses TLS issues with Python requests on Linux VMs)
- **Parses note content** — title, severity, CVSS score, affected software component release ranges, symptoms, solution text, kernel/DB/OS version requirements
- **Connects to live SAP systems via RFC** — reads installed components (CVERS table), SP levels, kernel patch level, implemented notes (CWBNTCUST)
- **Determines applicability** — `Applicable / Not Applicable / Already Implemented / Needs Manual Review / Insufficient Data` with confidence score and full evidence
- **Checks version dimensions** — SAP release range, kernel patch level, DB version, OS version
- **Works without pyrfc on the server** — via a relay architecture: RFC calls are proxied through a client running on your VPN-connected Windows laptop
- **Exports results** — Excel, JSON, PDF reports

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Browser (anywhere)                                         │
│  https://diffusive-knee-handwork.ngrok-free.dev                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS (ngrok tunnel)
┌──────────────────────────────▼──────────────────────────────────┐
│  GCP VM  (35.184.92.9)  — mukesh-market                         │
│  ┌─────────────────────┐   ┌──────────────────────────────────┐ │
│  │  Streamlit UI       │   │  Relay Server (FastAPI, :8081)   │ │
│  │  :8080              │   │  Cloudflare tunnel → VPN laptop  │ │
│  │  sap-streamlit      │   │  sap-relay.service               │ │
│  │  .service           │   └──────────────────────────────────┘ │
│  └─────────────────────┘                                         │
│  ┌─────────────────────┐                                         │
│  │  Playwright          │  (spawned per note download,          │
│  │  subprocess          │   headless Chromium → me.sap.com)     │
│  └─────────────────────┘                                         │
└─────────────────────────────────────────────────────────────────┘
                               │ RFC relay (Cloudflare tunnel)
┌──────────────────────────────▼──────────────────────────────────┐
│  Your Windows Laptop (on office VPN)                             │
│  relay\relay.bat  — relay/client.py                             │
│  Has pyrfc + SAP NW RFC SDK installed                            │
│  Polls relay server → executes RFC → returns results            │
└──────────────────────────────┬──────────────────────────────────┘
                               │ SAP RFC (port 33xx)
┌──────────────────────────────▼──────────────────────────────────┐
│  SAP Systems (internal network / VPN)                            │
│  DT-Dev, Prod, QA …                                             │
└─────────────────────────────────────────────────────────────────┘
```

**Why relay?** The GCP VM cannot directly reach internal SAP systems over RFC. The relay client runs on a VPN-connected laptop that can. The relay server on GCP acts as a message queue — Streamlit posts RFC requests, the laptop client polls, executes locally, and posts results back.

---

## 3. Pre-Requirements

### GCP VM
| Requirement | Details |
|---|---|
| OS | Ubuntu 20.04 LTS |
| RAM | Minimum 1 GB (2 GB recommended — Playwright uses ~150 MB per download) |
| Disk | 20 GB |
| Python | 3.10 (system) |
| Ports open | 8080 (Streamlit, via ngrok), 8081 (relay, via Cloudflare) |
| ngrok account | Free static domain at ngrok.com |
| Cloudflare | `cloudflared` binary — free quick tunnels |
| Playwright deps | GTK libs in `~/lib_deps` (see §7) |

### Your Windows Laptop (relay client)
| Requirement | Details |
|---|---|
| Python | 3.10+ with pip |
| SAP NW RFC SDK | 7.50 — download from support.sap.com (free, requires S-user) |
| pyrfc | `pip install pyrfc` (after SDK installed) |
| VPN | Must be connected to reach SAP systems |
| Office network | RFC ports (33xx) open to SAP application servers |

### SAP System Authorization
| Object | Fields | Value |
|---|---|---|
| S_RFC | RFC_NAME | RFC_PING, RFC_SYSTEM_INFO, RFC_READ_TABLE, TH_GET_VMODE |
| S_TABU_DIS | ACTVT=03 | CVERS, CWBNTCUST, SVERS |

### SAP S-user (for me.sap.com)
- Valid SAP S-user with access to me.sap.com
- Single-factor authentication (app uses Playwright login — MFA/2FA not supported)
- Access to SAP Security Notes

---

## 4. Project Structure

```
sap-analyzer/
├── adapters/
│   ├── me_note_parser.py       # Parse me.sap.com JSON → SapSecurityNote
│   ├── sap_me_fetcher.py       # Download notes via Playwright (headless Chrome)
│   ├── pdf_note_parser.py      # Parse uploaded PDF notes
│   ├── note_parser.py          # Parse HTML note files
│   └── sap_online_fetcher.py   # Orchestrator (PDF vs JSON path)
├── core/
│   ├── domain_models.py        # All dataclasses (NoteMetadata, LiveSystemInfo, etc.)
│   ├── live_engine.py          # Applicability decision engine (release range + version checks)
│   ├── applicability_engine.py # Offline engine (landscape-based)
│   ├── risk_analytics.py       # CVSS-based risk scoring
│   └── sapk_utils.py           # SAPK SP sequence parsing utilities
├── rfc/
│   ├── connector.py            # pyrfc wrapper + relay helpers (build_connection, relay_call)
│   ├── system_collector.py     # Collect LiveSystemInfo from SAP via RFC
│   ├── notes_checker.py        # Read CWBNTCUST (implemented notes)
│   └── note_fetcher.py         # Fetch note data from SAP system
├── relay/
│   ├── server.py               # FastAPI relay server (runs on GCP :8081)
│   ├── client.py               # Windows relay client (runs on VPN laptop)
│   ├── relay.bat               # Windows launcher for relay client
│   ├── relay_silent.vbs        # Silent VBS wrapper (no console window)
│   └── install_autostart.ps1   # Register relay in Windows Task Scheduler
├── storage/
│   ├── note_metadata.py        # Cache notes to disk (user_data/notes/)
│   ├── credentials.py          # Encrypted RFC profile storage (AES via PyCryptodome)
│   ├── report_generator.py     # Excel / PDF / JSON export
│   └── user_store.py           # Workspace management
├── ui/
│   ├── streamlit_app.py        # Main Streamlit router
│   ├── components.py           # Reusable UI components
│   ├── charts.py               # Plotly charts (gauge, radar, bar)
│   └── pages/
│       ├── dashboard.py        # Overview + relay status
│       ├── note_check.py       # Main analysis page (Step 1→2→3→Results)
│       ├── inventory.py        # Live System Inventory (CVERS + notes)
│       ├── results.py          # Full evidence drilldown
│       ├── rfc_profiles.py     # Manage RFC connection profiles
│       ├── reports.py          # Download reports
│       ├── settings.py         # Workspace + system info
│       └── logs_page.py        # View application logs
├── tests/                      # pytest test suite
├── start_gcp.sh                # VM startup script (Streamlit + ngrok + Cloudflare)
├── start.ps1                   # Windows local startup script
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker build (optional)
└── user_data/                  # Runtime data — NEVER committed to git
    ├── profiles/               # Encrypted RFC profiles + S-user
    └── workspaces/             # Per-workspace note cache
```

---

## 5. Design & Key Components

### 5.1 Note Download Flow

```
User clicks "Download Note XXXXXXX"
    │
    ▼
_start_dl() — spawns daemon thread, writes "running" to session state
    │
    ▼  (background thread)
fetch_note_json_me(note, s_user, s_pass)
    │
    ├── Writes _WORKER script to /tmp/*.py
    ├── Sets _SAP_U / _SAP_P env vars (credentials never in argv/ps output)
    └── subprocess.run(python _WORKER.py note_number /tmp/output.json, timeout=150s)
            │
            ▼  (Playwright subprocess — isolated from Streamlit event loop)
        Login: accounts.sap.com → #j_username → #logOnFormSubmit → #j_password
        Navigate: me.sap.com/notes/{note}
        Intercept: /backend/raw/sapnotes/Detail?q={note} JSON response
        Write: JSON → /tmp/output.json
    │
    ▼  (Streamlit polls every 10s via time.sleep(10) + st.rerun())
_poll_dl() — reads result file → parse_note_json_me() → save_note() → st.rerun()
```

**Why Playwright subprocess?** Python's `requests` library has TLS incompatibility with me.sap.com on the GCP VM (SSL EOF). Playwright uses Chromium's own TLS stack. Running Playwright in a subprocess (not inline) prevents blocking Streamlit's async event loop.

**Chromium memory flags used** (to reduce RAM on 1GB VM):
`--no-zygote --no-sandbox --disable-dev-shm-usage --disable-gpu --disable-extensions --disable-background-networking --disable-sync --mute-audio --js-flags=--max-old-space-size=64`

### 5.2 Applicability Engine (live_engine.py)

**Decision ladder:**

```
1. ALREADY_IMPLEMENTED  → note in CWBNTCUST with implemented status
2. NOT_APPLICABLE       → component not installed
                         OR system release below affected range
                         OR system release above affected range
                         OR fix SP already applied
                         OR version checks (kernel/DB/OS) clear it
3. APPLICABLE           → component+release in range, fix SP not yet applied
4. NEEDS_MANUAL_REVIEW  → version data ambiguous / partial unknowns
5. INSUFFICIENT_DATA    → no applicability matrix in note
```

**Critical bug fixed:** SAP note Validity table `From`/`To` fields are RELEASE numbers (e.g. 750–758), not SP levels. Previous code did exact release match (`sys_rel == note_rel`). Fixed to range check: `release_from <= sys_rel <= release_to`.

**Version dimensions checked:**
- `kernel`: note text regex → `kernel_min` → compare vs `kernel_patch` from system
- `db`: note text regex for HANA/Oracle/MSSQL/DB2/Sybase → `db_type`, `db_version_min`
- `os`: note text regex for RHEL/SLES/Windows/AIX → `os_type`, `os_version_min`

### 5.3 RFC Relay Architecture

**Why relay instead of direct pyrfc on VM?**
- SAP NW RFC SDK cannot be auto-downloaded (SAP S-user gate, no pip package)
- Installing it on a Linux VM requires manual steps + root
- The relay client on the VPN laptop already has pyrfc working

**How it works:**
1. Streamlit (VM) calls `relay_call("system_info", profile_dict, password)`
2. `relay_call` POSTs to `http://localhost:8081/relay/request` → gets `request_id`
3. Relay client on laptop GETs `/relay/poll` every 2 seconds
4. Client executes RFC locally → POSTs result to `/relay/result/{id}`
5. `relay_call` polls for result (90s timeout)

**Relay URL auto-discovery:** Cloudflare tunnel URL changes on every GCP restart. The startup script (`start_gcp.sh`) pushes the new URL to a GitHub Gist. The relay client fetches the Gist every 60 seconds to auto-discover the current URL — no manual reconfiguration needed after restarts.

### 5.4 Credential Security
- RFC passwords: entered per session, held in `st.session_state` only, never written to disk
- S-user password: stored encrypted in `user_data/profiles/suser.json` (AES-256 via PyCryptodome)
- SAP creds passed to Playwright worker via environment variables (`_SAP_U`, `_SAP_P`) — not in `sys.argv` (which would appear in `ps aux` output)
- GitHub token: stored in `~/.sap_env` on VM only, never committed to git
- RFC profiles: encrypted at rest, master key in `user_data/profiles/.master.key`

---

## 6. Development Journey

### Phase 1 — Note Download
- Initial approach: `requests.get()` to me.sap.com → **SSL EOF error** on GCP VM (TLS incompatibility)
- Fix: Playwright headless Chromium to intercept API response
- Second issue: Playwright blocked Streamlit's main thread → UI froze
- Fix: Run Playwright in a **subprocess** + background thread + file-based polling

### Phase 2 — RFC Connectivity
- pyrfc not installable on GCP VM (no SAP NW RFC SDK)
- Built relay architecture: FastAPI server on VM + Python client on Windows laptop
- Cloudflare tunnel for relay, ngrok for UI
- GitHub Gist for relay URL auto-discovery

### Phase 3 — Applicability Engine Bug
- Note 2424539 showing "Not Applicable" for SAP_BASIS 752 — wrong
- Root cause: `From`/`To` in Validity table are release numbers (750–758), engine was doing exact match
- Fix: range check `release_from <= sys_rel <= release_to`

### Phase 4 — Option D Enhancement
- Added note summary panel (symptoms + solution text from LongText HTML)
- Added kernel/DB/OS version check dimensions
- Fixed `_build_applicability` to correctly map From→`release`, To→`release_to`
- Added `VersionCheckResult` dataclass + evidence display

### Phase 5 — Stability & Performance
- Nested `st.expander` error → removed nested expanders, render inline
- Live System Inventory not using relay → fixed to call `relay_call("system_info")`
- VM load avg 10+ → increased poll from 3s→10s, added Chromium memory flags
- Credential security → moved from argv to env vars

---

## 7. Deployment — GCP VM

### 7.1 First-Time Setup

```bash
# SSH to VM
ssh -i ~/.ssh/banknifty_vm priya141ch@35.184.92.9

# Clone repo
cd ~
git clone https://github.com/priya141ch-png/sap-security-note-analyzer.git sap-analyzer
cd sap-analyzer

# Python venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Playwright — install Chromium with GTK libs to user space (no root)
pip install playwright
mkdir -p ~/lib_deps
PLAYWRIGHT_BROWSERS_PATH=~/.local/share/ms-playwright \
  python -m playwright install chromium

# Extract GTK/system libs that Chromium needs (copy from system)
# The sap_me_fetcher.py worker sets LD_LIBRARY_PATH=~/lib_deps/usr/lib/... at runtime

# Create logs directory
mkdir -p logs

# Create secrets file (never commit this)
cat > ~/.sap_env << 'EOF'
export GITHUB_TOKEN=ghp_your_token_here
EOF
chmod 600 ~/.sap_env
```

### 7.2 Install systemd Services

```bash
# Streamlit UI service
sudo tee /etc/systemd/system/sap-streamlit.service << 'EOF'
[Unit]
Description=SAP Analyzer (Streamlit UI)
After=network.target

[Service]
Type=simple
User=priya141ch
WorkingDirectory=/home/priya141ch/sap-analyzer
Environment="PATH=/home/priya141ch/sap-analyzer/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/priya141ch/sap-analyzer/.venv/bin/streamlit run ui/streamlit_app.py --server.port 8080 --server.headless true --server.address 0.0.0.0
Restart=always
RestartSec=10
StandardOutput=append:/home/priya141ch/sap-analyzer/logs/streamlit.log
StandardError=append:/home/priya141ch/sap-analyzer/logs/streamlit.log

[Install]
WantedBy=multi-user.target
EOF

# Relay server service
sudo tee /etc/systemd/system/sap-relay.service << 'EOF'
[Unit]
Description=SAP Relay Server
After=network.target

[Service]
Type=simple
User=priya141ch
WorkingDirectory=/home/priya141ch/sap-analyzer
Environment="PATH=/home/priya141ch/sap-analyzer/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/priya141ch/sap-analyzer/.venv/bin/python relay/server.py
Restart=always
RestartSec=10
StandardOutput=append:/home/priya141ch/sap-analyzer/logs/relay.log
StandardError=append:/home/priya141ch/sap-analyzer/logs/relay.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sap-streamlit sap-relay
sudo systemctl start sap-streamlit sap-relay
```

### 7.3 ngrok Setup (permanent domain)

```bash
# Download ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xzf ngrok-v3-stable-linux-amd64.tgz -C ~/bin/
chmod +x ~/bin/ngrok

# Authenticate (one-time, token from ngrok dashboard)
~/bin/ngrok config add-authtoken YOUR_NGROK_TOKEN

# Start with permanent static domain
~/bin/ngrok http 8080 --url=diffusive-knee-handwork.ngrok-free.dev &
```

### 7.4 Cloudflare Tunnel (relay URL)

```bash
# Download cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O ~/bin/cloudflared
chmod +x ~/bin/cloudflared

# Start quick tunnel (URL changes each restart — auto-published to GitHub Gist by start_gcp.sh)
~/bin/cloudflared tunnel --url http://localhost:8081 --no-autoupdate &
```

### 7.5 After Every VM Restart

```bash
cd ~/sap-analyzer
bash start_gcp.sh
# This starts: Streamlit (via systemd), ngrok, cloudflared, publishes relay URL to Gist
```

### 7.6 Day-to-Day Operations

```bash
# Restart app (NEVER use pkill — triggers Telegram DOWN alerts)
sudo systemctl restart sap-streamlit.service

# View logs
tail -f ~/sap-analyzer/logs/streamlit.log

# Check relay
curl http://localhost:8081/relay/status

# Git pull latest changes
cd ~/sap-analyzer && git pull origin master
sudo systemctl restart sap-streamlit.service
```

---

## 8. Deployment — Local (Windows)

### 8.1 Setup

```powershell
# Clone
git clone https://github.com/priya141ch-png/sap-security-note-analyzer.git
cd sap-security-note-analyzer

# Python venv
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Playwright
pip install playwright
playwright install chromium

# SAP NW RFC SDK (required for direct RFC, skip if using relay only)
# 1. Download from: https://support.sap.com/en/product/connectors/nwrfcsdk.html
# 2. Extract to C:\nwrfcsdk
# 3. Add C:\nwrfcsdk\lib to PATH
# 4. Set env var: SAPNWRFC_HOME=C:\nwrfcsdk
# 5. pip install pyrfc

# Run locally
streamlit run ui/streamlit_app.py --server.port 8080
# Access: http://localhost:8080
```

### 8.2 Windows Quick-Start

```powershell
# Start everything (Streamlit on localhost only — no ngrok/relay needed for local use)
.\start.ps1
```

---

## 9. Relay Client Setup (VPN Laptop)

The relay client must run on a Windows machine that:
- Is connected to office VPN
- Can reach SAP systems on RFC ports (33xx)
- Has pyrfc installed

### 9.1 One-Time Setup

```powershell
# In the project root (already cloned or copied)
cd relay

# Option A: Register as Windows Task Scheduler task (starts at login silently)
powershell -ExecutionPolicy Bypass -File install_autostart.ps1

# Option B: Run manually
relay.bat
```

### 9.2 How the Client Auto-Discovers the Relay Server

1. On startup, client fetches: `https://gist.githubusercontent.com/priya141ch-png/29120e8c133492f893b2b6a65158532a/raw/relay.json`
2. This Gist is updated by `start_gcp.sh` on every VM restart
3. No manual URL configuration needed — client reconnects automatically

### 9.3 Verify Connection

In the app, go to **Dashboard** or **Note Applicability Check** — you should see:
> 🔗 Relay connected — live RFC checks will run through your VPN laptop.

---

## 10. Git Workflow

**Rule: Always make changes ON the VM first, then commit and push from VM, then pull locally. Never edit local files first.**

```bash
# On VM — after making changes
cd ~/sap-analyzer
git add <changed files>
git commit -m "Description of change"
git push origin master

# Locally — pull changes
git pull origin master
```

### What is NOT committed to git

| Item | Reason |
|---|---|
| `user_data/` | Contains encrypted credentials, note cache (user-specific) |
| `logs/` | Runtime logs |
| `runs/` | Analysis run history |
| `.env`, `~/.sap_env` | Secrets — GitHub token |
| `user_data/profiles/.master.key` | Encryption key |
| `URLS.txt` | Dynamic URLs that change on restart |
| `.venv/` | Large, platform-specific |

---

## 11. Running & Operating

### Application Pages

| Page | What it does |
|---|---|
| **Dashboard** | Relay status, recent activity overview |
| **RFC Connection Profiles** | Add/test SAP system connections (host, sysnr, client, user) |
| **Note Applicability Check** | Main page — enter note number, download, run analysis against all systems |
| **Live System Inventory** | Collect CVERS + implemented notes from one system |
| **Results & Evidence** | Full drilldown — component check, SP check, version checks, charts |
| **Reports** | Download Excel/JSON/PDF reports |
| **Run History** | Past analysis runs |
| **Logs** | Streamlit application logs |
| **Settings** | Workspace, cached notes management |

### Note Analysis Workflow

1. Go to **Note Applicability Check**
2. Enter SAP Note number (e.g. `3754659`)
3. Click **Download Note** — wait ~60s (Playwright login + fetch)
4. Verify metadata loaded (title, severity, affected releases shown)
5. Select RFC profiles + enter passwords for systems to check
6. Click **Run Analysis**
7. View results — Applicable / Not Applicable / etc.
8. Download Excel report from **Reports** page

### Service Management

```bash
# DO use systemctl — NOT pkill (pkill triggers Telegram DOWN alerts via Restart=always)
sudo systemctl start|stop|restart|status sap-streamlit.service
sudo systemctl start|stop|restart|status sap-relay.service
```

---

## 12. Security Notes

| Area | Implementation |
|---|---|
| RFC passwords | Session-only (st.session_state), never written to disk |
| S-user password | AES-256 encrypted at rest (PyCryptodome) |
| Playwright credentials | Passed via env vars `_SAP_U`/`_SAP_P` — not in process list/ps output |
| RFC profiles | Encrypted at rest, master key local only |
| GitHub token | `~/.sap_env` on VM only, never in git |
| Relay communication | HTTPS via Cloudflare tunnel |
| SAP access | Read-only RFC functions only — no ABAP execution, no data writes |

---

## 13. Known Limitations & Parking Notes

| Item | Status | Notes |
|---|---|---|
| PDF download/view | Parked | `fetch_note_pdf_me` is a stub — SAP PDF URL needs separate auth flow. Workaround: download manually from me.sap.com + upload via upload expander. |
| 2FA / MFA S-user | Not supported | Playwright uses username+password login only |
| pyrfc on VM | Not installed | Relay architecture handles this — no action needed unless VM gets NW RFC SDK |
| VM RAM (1 GB) | Constraint | Playwright uses ~150MB per download, pushes into swap. Upgrade VM to 2GB for better performance. |
| DB version collection | Partially implemented | `DB_VERSION_GET_SCMON` attempted; falls back to SVERS. Accuracy depends on SAP authorization. |
| OS version collection | Partially implemented | `SINFO_GET_OSVER` attempted; falls back to `RFCOPSYS` field. |
| Note PDF parsing | Works for uploaded PDFs | `pdf_note_parser.py` handles manual uploads |
| Multiple simultaneous downloads | Sequential only | Starting two note downloads simultaneously will compete for memory |

---

## 14. Troubleshooting

### App not loading / 502 error
```bash
sudo systemctl status sap-streamlit.service
tail -50 ~/sap-analyzer/logs/streamlit.log
sudo systemctl restart sap-streamlit.service
```

### Note download stuck / no progress after 3 minutes
```bash
# Kill stuck Playwright processes (safe — systemd will restart Streamlit if needed)
pkill -f "playwright/driver/node"
pkill -f "tmp.*\.py"   # worker scripts
# Then retry download in the app
```

### "Relay not connected" in app
1. Check relay.bat is running on your VPN laptop
2. Check VPN is connected
3. Check: `curl http://localhost:8081/relay/status` on VM should return `{"relay_connected": true}`

### "Collection failed" in Live System Inventory
1. Verify relay is connected (green banner)
2. Check RFC profile host/sysnr/client are correct
3. Verify SAP user has RFC_READ_TABLE access on CVERS

### High VM load / slow response
```bash
top    # check load average
ps aux --sort=-%mem | head -10   # find memory hogs
# If Playwright node process stuck:
pkill -f "playwright/driver/node"
```

### Telegram "SAP Analyzer is down" alerts
- Caused by systemd `Restart=always` when Streamlit crashes
- **Never use `pkill -9 streamlit`** — use `sudo systemctl restart sap-streamlit.service`
- If alert storms occur, check logs for crash reason

### Wrong "Not Applicable" result
- Verify note has been downloaded (not just uploaded as PDF)
- Check that the system's SAP_BASIS release is within note's affected range
- Check Results & Evidence page for detailed component/SP evidence

---

## Appendix: Key File Locations on GCP VM

| Purpose | Path |
|---|---|
| App root | `/home/priya141ch/sap-analyzer/` |
| Python venv | `/home/priya141ch/sap-analyzer/.venv/` |
| Streamlit logs | `/home/priya141ch/sap-analyzer/logs/streamlit.log` |
| Relay logs | `/home/priya141ch/sap-analyzer/logs/relay.log` |
| Note cache | `/home/priya141ch/sap-analyzer/user_data/workspaces/*/notes/` |
| RFC profiles | `/home/priya141ch/sap-analyzer/user_data/profiles/profiles.json` |
| VM secrets | `~/.sap_env` |
| Streamlit service | `/etc/systemd/system/sap-streamlit.service` |
| Relay service | `/etc/systemd/system/sap-relay.service` |
| Startup script | `/home/priya141ch/sap-analyzer/start_gcp.sh` |
| Playwright libs | `~/lib_deps/` |
| ngrok binary | `~/bin/ngrok` |
| cloudflared binary | `~/bin/cloudflared` |
