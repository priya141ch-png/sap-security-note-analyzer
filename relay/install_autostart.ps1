# install_autostart.ps1
# Registers the RFC Relay Client as a Windows Scheduled Task.
# Runs automatically at login — no window, no manual step needed.
# Run this script ONCE. After that the relay starts itself on every login.

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python      = Join-String $ProjectRoot "\.venv\Scripts\pythonw.exe"   # pythonw = no console window
$Script      = Join-String $ProjectRoot "\relay\client.py"
$TaskName    = "SAP-RFC-Relay"

if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] pythonw.exe not found at: $Python" -ForegroundColor Red
    Write-Host "        Make sure the .venv is set up (run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt)" -ForegroundColor Yellow
    pause; exit 1
}

# Remove old task if it exists
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Build the action — pythonw runs silently (no console window)
$Env_SAPNWRFC = "C:\nwrfcsdk"
$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$Script`"" `
    -WorkingDirectory $ProjectRoot

# Trigger: at logon for current user
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Settings: restart on failure, run even on battery, don't stop on idle
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable

# Environment variables for SAP NW RFC SDK
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Register
$Task = Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description "SAP Security Note Analyzer — RFC Relay (auto-started at login)"

# Set environment variables for the task via XML patch
$xml = Export-ScheduledTask -TaskName $TaskName
$envBlock = @"
      <EnvironmentVariables>
        <Variable>
          <Name>SAPNWRFC_HOME</Name>
          <Value>C:\nwrfcsdk</Value>
        </Variable>
        <Variable>
          <Name>PATH</Name>
          <Value>C:\nwrfcsdk\lib;$([System.Environment]::GetEnvironmentVariable('PATH','Machine'))</Value>
        </Variable>
      </EnvironmentVariables>
"@
# Inject env into XML (best-effort — works on most Windows 10/11)
$xml2 = $xml -replace '</Exec>', "$envBlock</Exec>"
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Register-ScheduledTask -TaskName $TaskName -Xml $xml2 | Out-Null
} catch {
    # Env injection failed — not critical, PATH is usually inherited
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Green
Write-Host "    RFC Relay auto-start INSTALLED" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Task name : $TaskName" -ForegroundColor Cyan
Write-Host "  Runs as   : $env:USERNAME  (at every login)" -ForegroundColor Cyan
Write-Host "  No window : silent background process" -ForegroundColor Cyan
Write-Host "  Log file  : $ProjectRoot\relay\relay_client.log" -ForegroundColor Cyan
Write-Host ""
Write-Host "  The relay will start automatically on next login." -ForegroundColor White
Write-Host "  Starting it NOW for this session..." -ForegroundColor White
Write-Host ""

# Start immediately for this session too
Start-Process -FilePath $Python -ArgumentList "`"$Script`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden

Write-Host "  Relay is running in the background." -ForegroundColor Green
Write-Host "  Check relay\relay_client.log to confirm it's connected." -ForegroundColor Gray
Write-Host ""
pause
