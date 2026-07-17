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

echo  Auto-discovering relay URL from permanent endpoint...
echo  (No manual URL update needed - updates automatically on GCP restart)
echo.

.venv\Scripts\python.exe relay\client.py

echo.
echo  Relay stopped.
pause
