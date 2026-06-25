@echo off
title SAP RFC Relay Client
color 0A
echo.
echo  =====================================================
echo    SAP Security Note Analyzer -- RFC Relay Client
echo  =====================================================
echo.
echo  IMPORTANT: Make sure you are connected to OFFICE VPN
echo  Keep this window OPEN while using the tool.
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."

set "SAPNWRFC_HOME=C:\nwrfcsdk"
set "PATH=C:\nwrfcsdk\lib;%PATH%"

REM Relay URL — update this with the URL shown in the app's Settings page
REM after each GCP restart (rare). Get it from: cat ~/sap-analyzer/URLS.txt on the VM
set "SAP_RELAY_URL=https://create-none-wma-var.trycloudflare.com"

echo  Connecting to relay: %SAP_RELAY_URL%
echo.

.venv\Scripts\python.exe relay\client.py "%SAP_RELAY_URL%"

echo.
echo  Relay stopped.
pause
