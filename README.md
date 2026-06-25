# 🔐 SAP Security Note Analyzer

> **Enterprise-grade SAP Security Note applicability checker — browser-based, no SAP GUI needed, multi-client support.**

Designed & Developed by **Panchamukesh Chandaka**

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Prerequisites](#prerequisites)
5. [Setup — Option A: Cloud (GCP) Mode](#setup--option-a-cloud-gcp-mode)
6. [Setup — Option B: Local Mode (your laptop)](#setup--option-b-local-mode-your-laptop)
7. [RFC Relay Setup (required for live checks)](#rfc-relay-setup)
8. [First-Time Usage Walkthrough](#first-time-usage-walkthrough)
9. [Multi-Client Workflow](#multi-client-workflow)
10. [Workspace & Data Privacy](#workspace--data-privacy)
11. [Troubleshooting](#troubleshooting)
12. [Project Structure](#project-structure)

---

## Overview

The **SAP Security Note Analyzer** checks whether SAP Security Notes are applicable to your SAP systems — directly via live RFC connections, without installing anything on end-user laptops.

**Key capability:** You work for multiple clients (Daimler Trucks, Novus, Dolby, etc.), each with multiple SAP systems (Dev/QA/Prod). This tool lets you:

- Check one note against **all systems across all clients in one click**
- Or select specific systems from specific clients
- Get an aggregated results table showing applicability per system
- Download Excel / PDF / JSON reports

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Your Browser (any device, any OS)                              │
│  https://your-url.trycloudflare.com                             │
└──────────────────────┬──────────────────────────────────────────┘
                       │  HTTPS (Cloudflare tunnel)
┌──────────────────────▼──────────────────────────────────────────┐
│  GCP VM  (35.184.92.9)          Ubuntu 22.04                    │
│  ┌────────────────┐  ┌────────────────────────────────────┐     │
│  │ Streamlit UI   │  │ RFC Relay Server                   │     │
│  │ port 8080      │  │ port 8081                          │     │
│  └────────────────┘  └───────────────┬────────────────────┘     │
└──────────────────────────────────────┼─────────────────────────-┘
                                       │  HTTP poll (relay client)
┌──────────────────────────────────────▼──────────────────────────┐
│  Your Laptop (on office VPN)                                    │
│  relay/relay_client.py  — polls relay server every 2s           │
│  Executes RFC calls locally via pyrfc                           │
└──────────────────────┬──────────────────────────────────────────┘
                       │  RFC (port 33xx)
┌──────────────────────▼──────────────────────────────────────────┐
│  SAP Systems (behind corporate VPN)                             │
│  NPL / S4H / ECC / BW — any system with RFC access             │
└─────────────────────────────────────────────────────────────────┘
```

**Why RFC Relay?**
The GCP server cannot reach your SAP systems (they are behind VPN). Instead, a lightweight relay client runs silently on your VPN-connected laptop. The GCP server sends RFC requests to the relay; the relay executes them via pyrfc and returns results.

---

## Features

| Feature | Description |
|---|---|
| 🏢 **Multi-client grouping** | Organise RFC profiles by client (Daimler, Novus, etc.) |
| 🖥️ **Multi-system selection** | Check one note against any combination of systems |
| 📊 **Aggregated results** | Results table grouped by client/system with status + confidence |
| 🔒 **Private workspaces** | Each user gets an isolated workspace — no data sharing |
| 📦 **Export/Import** | Backup your workspace and restore on any new device |
| 📄 **Reports** | Excel, PDF, JSON export per run |
| 🔌 **Relay auto-start** | Relay client starts silently at Windows login (Task Scheduler) |
| 🌐 **Zero install** | Colleagues open the URL — nothing to install |

---

## Prerequisites

### On GCP VM
- Ubuntu 22.04
- Python 3.10+
- pip packages (see `requirements.txt`)

### On your VPN laptop (relay machine)
- Windows 10/11
- Python 3.8+ (real interpreter — not Windows Store stub)
- SAP NW RFC SDK 7.50 ([download here](https://support.sap.com/en/product/connectors/nwrfcsdk.html) — free, requires S-user)
- `pyrfc` installed: `pip install pyrfc`

### SAP System
- RFC user with these minimum authorisations:

| Object | Field | Value |
|---|---|---|
| `S_RFC` | RFC_TYPE | FUGR |
| `S_RFC` | RFC_NAME | RFC_PING, RFC_SYSTEM_INFO, RFC_READ_TABLE |
| `S_RFC` | ACTVT | 16 |
| `S_TABU_DIS` | DICBERCLS | SS |
| `S_TABU_DIS` | ACTVT | 03 |

---

## Setup — Option A: Cloud (GCP) Mode

### Step 1 — Connect to GCP VM

```bash
ssh -i ~/.ssh/banknifty_vm priya141ch@35.184.92.9
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/panchamukesh/sap-security-note-analyzer.git ~/sap-analyzer
cd ~/sap-analyzer
```

### Step 3 — Create Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 4 — Start the application

```bash
bash start_gcp.sh
```

This script:
- Kills any existing Streamlit / relay server processes
- Starts the RFC Relay Server on port 8081
- Starts Streamlit UI on port 8080
- Starts two Cloudflare Quick Tunnels (UI + Relay)
- Writes public URLs to `URLS.txt`

### Step 5 — Get the public URLs

```bash
cat URLS.txt
```

Output example:
```
SAP Security Note Analyzer
UI:    https://macro-disclaimer-sender-collect.trycloudflare.com
Relay: https://create-none-wma-var.trycloudflare.com
Started: Thu Jun 25 16:00:00 UTC 2026
```

Share the **UI URL** with colleagues. Keep the **Relay URL** for your `relay.bat`.

> ⚠️ **Cloudflare Quick Tunnel URLs change on every restart.** After restarting `start_gcp.sh`, share the new UI URL. For a permanent URL, set up an ngrok static domain (see Troubleshooting).

---

## Setup — Option B: Local Mode (your laptop)

Run the entire stack on your own Windows machine — no cloud needed.

### Step 1 — Clone the repository

```powershell
git clone https://github.com/panchamukesh/sap-security-note-analyzer.git
cd sap-security-note-analyzer
```

### Step 2 — Create virtual environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3 — Install SAP NW RFC SDK

1. Download SDK 7.50 from [SAP Support Portal](https://support.sap.com/en/product/connectors/nwrfcsdk.html)
2. Extract to `C:\nwrfcsdk`
3. Add to environment:
   ```powershell
   [System.Environment]::SetEnvironmentVariable("SAPNWRFC_HOME","C:\nwrfcsdk","Machine")
   $env:Path += ";C:\nwrfcsdk\lib"
   ```
4. Install pyrfc:
   ```powershell
   pip install pyrfc
   ```

### Step 4 — Start locally

```powershell
streamlit run ui/streamlit_app.py --server.port 8080
```

Open [http://localhost:8080](http://localhost:8080)

No relay needed — pyrfc connects directly to SAP.

---

## RFC Relay Setup

The relay bridges RFC calls from the GCP server through your VPN laptop to SAP.

### Step 1 — Update relay URL

Edit `relay/relay.bat` and set your relay server URL (from `URLS.txt`):

```batch
@echo off
python relay\client.py https://create-none-wma-var.trycloudflare.com
```

### Step 2 — Auto-start at login (recommended)

Run **once** in PowerShell as Administrator:

```powershell
cd C:\path\to\sap-security-note-analyzer
powershell -ExecutionPolicy Bypass -File relay\install_autostart.ps1
```

This registers a Windows Task Scheduler task called `SAP-RFC-Relay` that starts the relay silently at every login — no manual steps needed.

### Step 3 — Verify relay is connected

In the app, open **🛡️ Note Applicability Check**. You should see:

> 🔗 **Relay connected** — live RFC checks will run through your VPN laptop.

### Manual run (if needed)

```batch
relay\relay.bat
```

Or with a custom relay URL:

```powershell
python relay\client.py https://your-relay-url.trycloudflare.com
```

---

## First-Time Usage Walkthrough

### 1. Open the URL

Navigate to the public URL (or `http://localhost:8080` for local mode).

### 2. Accept the Privacy Notice

Read and click **✅ I Understand — Continue**.

### 3. Create or Restore Workspace

- **New user:** Click **✨ Create New Workspace**. Save your Workspace ID (shown in sidebar).
- **Returning user on new device:** Enter your previous Workspace ID → click **🔄 Restore Workspace**.

### 4. Add RFC Connection Profiles

Go to **🔗 RFC Connection Profiles** → **Add New Profile**:

| Field | Example |
|---|---|
| Client (organisation) | `Daimler Trucks` |
| Profile Name | `DAIMLER-PRD` |
| App Server Host | `sap-prd.daimler.com` |
| System Number | `00` |
| SAP Client | `100` |
| RFC User | `RFC_READ` |
| Environment | `Production` |

Repeat for each SAP system across all clients.

### 5. Upload SAP Note Metadata

Go to **🛡️ Note Applicability Check** → enter a note number → click **⬇️ Download from SAP Portal**:

1. Click the link to open the note in SAP portal (login with S-user)
2. Click **Print Version** or **PDF**
3. Upload the downloaded PDF in the app

### 6. Select Systems and Run

- Use checkboxes to select target systems (by client or individually)
- Click **Select all in [Client]** to check all systems for one client
- Enter RFC password → click **▶ Run Check**

### 7. Review Results

The aggregated table shows:

| Client | System | SID | Status | Confidence |
|---|---|---|---|---|
| Daimler Trucks | DAIMLER-PRD | D01 | 🔴 Applicable | 90% |
| Daimler Trucks | DAIMLER-QAS | D02 | 🔵 Already Implemented | 95% |
| Novus | NOV-PRD | NV1 | 🟢 Not Applicable | 85% |

### 8. Download Reports

Click **⬇️ Excel Report (all systems)**, **⬇️ PDF Report**, or **⬇️ JSON** at the bottom of results.

---

## Multi-Client Workflow

### Scenario: Check note 3194159 across all clients

1. Go to **🛡️ Note Applicability Check**
2. Enter note number `3194159`
3. Upload note PDF if not already cached
4. Click **☑️ Select All Systems**
5. Enter RFC password
6. Click **▶ Run Check on N Systems**
7. Review aggregated results grouped by client

### Scenario: Check only Production systems

1. For each client section, manually tick only the `[Production]` systems
2. Run check

### Scenario: Check all systems for Daimler Trucks only

1. Click **Select all in Daimler Trucks**
2. Ensure other clients are deselected
3. Run check

---

## Workspace & Data Privacy

### What is a Workspace?

Each user/browser gets a unique 8-character Workspace ID (e.g. `A3F7B2C1`). All your data on the server is stored under this ID — completely isolated from other users.

### What is stored where?

| Data | Where stored | Notes |
|---|---|---|
| RFC profiles (without passwords) | Server — your workspace only | AES-128 encrypted |
| RFC passwords | Nowhere — entered per session | Never stored |
| Note metadata cache | Server — your workspace only | Public SAP data |
| Run history & results | Your browser tab only | Cleared on tab close |
| Workspace ID | Your browser (session) | Enter it to restore |

### Backup & Restore

**Export (before switching device):**
Go to **⚙️ Settings → My Data → Export My Data** → download `.sap-backup` file.

**Restore (on new device):**
Go to **⚙️ Settings → My Data → Restore/Import** → upload `.sap-backup` file.

Or simply enter your **Workspace ID** on the workspace setup screen to restore your server-side data (profiles, notes).

---

## Troubleshooting

### App shows blank page / stuck loading

```bash
# On GCP VM:
ssh -i ~/.ssh/banknifty_vm priya141ch@35.184.92.9
pkill -f 'streamlit run'
fuser -k 8080/tcp
bash ~/sap-analyzer/start_gcp.sh
```

### Relay not connecting

1. Ensure you are on office VPN
2. Check `relay\relay_client.log` for errors
3. Verify the relay URL in `relay\relay.bat` matches the current URL in `URLS.txt`
4. Re-run: `relay\relay.bat`

### "RFC connection failed"

1. Test the profile manually: **🔗 RFC Connection Profiles** → enter password → **🔗 Test Connection**
2. Verify SAP user has required authorisations (see Prerequisites)
3. Confirm the relay is showing 🔗 connected

### Cloudflare URL changed after restart

After every `start_gcp.sh`, new URLs are generated. Check:

```bash
cat ~/sap-analyzer/URLS.txt
```

For a **permanent URL**, sign up at [ngrok.com](https://ngrok.com), claim a free static domain, then update `start_gcp.sh` to use ngrok instead of cloudflared.

### Ports 5000 / 5002 conflict

These ports are used by other applications on the VM and are **never touched** by this tool. The SAP Analyzer uses ports **8080** (UI) and **8081** (relay server) only.

---

## Project Structure

```
sap-security-note-analyzer/
│
├── ui/                          # Streamlit web application
│   ├── streamlit_app.py         # Main entry point, workspace init, navigation
│   ├── components.py            # Reusable UI components (KPI cards, tables)
│   ├── charts.py                # Plotly chart functions
│   ├── run_history.py           # Session-based run history (not persisted to disk)
│   └── pages/
│       ├── dashboard.py         # Home dashboard + relay status
│       ├── rfc_profiles.py      # RFC profiles grouped by client organisation
│       ├── note_check.py        # Multi-system note applicability check
│       ├── inventory.py         # Live system inventory
│       ├── results.py           # Results & Evidence viewer
│       ├── reports.py           # Report generation
│       ├── history.py           # Run history viewer
│       ├── logs_page.py         # Application log viewer
│       └── settings.py          # Workspace export/import, cache, environment
│
├── core/
│   ├── domain_models.py         # Dataclasses: RfcProfile, NoteMetadata, LiveSystemInfo
│   └── live_engine.py           # Applicability evaluation logic
│
├── rfc/
│   ├── connector.py             # SAP RFC connection wrapper + relay helpers
│   ├── system_collector.py      # Collects system metadata via RFC_SYSTEM_INFO + CVERS
│   └── notes_checker.py         # Reads implemented notes from CWBNTCUST
│
├── storage/
│   ├── user_store.py            # Workspace ID management, namespaced file paths
│   ├── credentials.py           # RFC profile storage (AES-128 encrypted)
│   ├── note_metadata.py         # Note metadata cache (per workspace)
│   └── report_generator.py      # Excel / PDF / JSON report generation
│
├── adapters/
│   ├── note_parser.py           # HTML SAP note parser
│   └── pdf_note_parser.py       # PDF SAP note parser
│
├── relay/
│   ├── server.py                # FastAPI relay server (runs on GCP port 8081)
│   ├── client.py                # Relay client (runs on VPN laptop, polls server)
│   ├── relay.bat                # Windows batch file to start relay client
│   └── install_autostart.ps1    # Registers relay as Windows Task Scheduler task
│
├── start_gcp.sh                 # Full GCP startup script (Streamlit + relay + tunnels)
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Docker build (optional)
└── .gitignore                   # Excludes user_data/, credentials, logs
```

---

## Security Notes

- **RFC passwords** are entered per-session and never stored anywhere
- **Profile data** (host, user, client) is stored encrypted with AES-128 Fernet
- **Master encryption key** is auto-generated per workspace and stored in `user_data/workspaces/{id}/profiles/.master.key` (excluded from git)
- **Run history** is stored in browser session state only — cleared when the tab closes
- **No telemetry** — the application does not send any data outside your organisation's network

---

## License

Private — for internal use.
© 2025 Panchamukesh Chandaka. All rights reserved.
