@echo off
title SAP RFC Relay Client

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."

set "SAPNWRFC_HOME=C:\nwrfcsdk"
set "PATH=C:\nwrfcsdk\lib;%PATH%"

:loop
.venv\Scripts\python.exe relay\client.py
echo Relay client exited, restarting in 10s...
timeout /t 10 /nobreak >nul
goto loop
