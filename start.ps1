# SAP Security Note Analyzer — launcher
# Sets SDK environment then starts Streamlit

$env:SAPNWRFC_HOME = "C:\nwrfcsdk"
$env:PATH = "C:\nwrfcsdk\lib;" + $env:PATH

Write-Host "Starting SAP Security Note Analyzer..." -ForegroundColor Cyan
Write-Host "SDK: $env:SAPNWRFC_HOME" -ForegroundColor Gray

Set-Location $PSScriptRoot
& ".venv\Scripts\streamlit.exe" run ui\streamlit_app.py --server.port 8501 --server.headless true
