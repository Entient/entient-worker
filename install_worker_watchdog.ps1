#!/usr/bin/env pwsh
# install_worker_watchdog.ps1
# Run this ONCE on BrockPC (as the Brock user, not admin required).
# Registers ENTIENT-WorkerWatchdog scheduled task: fires at login + every 5 min.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install_worker_watchdog.ps1
#   powershell -ExecutionPolicy Bypass -File install_worker_watchdog.ps1 -StartNow

param([switch]$StartNow)

$TaskName    = "ENTIENT-WorkerWatchdog"
$WatchdogScript = "$PSScriptRoot\worker_watchdog.ps1"

Write-Host ""
Write-Host " ============================================"
Write-Host "  ENTIENT Worker Watchdog Installer"
Write-Host " ============================================"
Write-Host ""
Write-Host "  Script : $WatchdogScript"
Write-Host "  Task   : $TaskName"
Write-Host ""

if (-not (Test-Path $WatchdogScript)) {
    Write-Host "[X] worker_watchdog.ps1 not found at $WatchdogScript" -ForegroundColor Red
    exit 1
}

# Build action
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WatchdogScript`"" `
    -WorkingDirectory $PSScriptRoot

# Triggers: at logon + every 5 minutes indefinitely
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn
$triggerRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

# Register (replaces existing)
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerLogon, $triggerRepeat) `
    -Settings $settings `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "[OK] $TaskName registered (fires at login + every 5 min)." -ForegroundColor Green

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] Task started now." -ForegroundColor Green
}

Write-Host ""
Write-Host "  Done. Worker will auto-restart within 5 min if it dies."
Write-Host " ============================================"
Write-Host ""
