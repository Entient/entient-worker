#!/usr/bin/env pwsh
# worker_watchdog.ps1 -- runs every 5 min via ENTIENT-WorkerWatchdog scheduled task.
# Ensures worker.py stays connected to the coordinator. Restarts if dead.

$WorkerDir   = "C:\Users\Brock\OneDrive\Desktop\entient-worker"
$CoordUrl    = "http://100.101.178.111:8420"
$LogFile     = "$env:USERPROFILE\.entient\v2\worker_watchdog.log"
$PythonExe   = "$WorkerDir\.venv\Scripts\python.exe"
$WorkerScript = "$WorkerDir\worker.py"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -ErrorAction SilentlyContinue
}

# Ensure log dir exists
$logDir = Split-Path $LogFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Log "Watchdog tick starting..."

# Check if worker.py is running
$workerProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "worker\.py" })

if ($workerProcs.Count -gt 1) {
    # Duplicates -- kill all but oldest
    $sorted = $workerProcs | Sort-Object ProcessId
    $keep = $sorted[0]
    $sorted | Select-Object -Skip 1 | ForEach-Object {
        Log "Duplicate worker.py (PID $($_.ProcessId)) -- killing."
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Log "Kept worker.py (PID $($keep.ProcessId))."
} elseif ($workerProcs.Count -eq 1) {
    Log "worker.py running (PID $($workerProcs[0].ProcessId)). OK."
} else {
    Log "worker.py NOT running -- restarting..."
    if (-not (Test-Path $PythonExe)) {
        Log "ERROR: venv python not found at $PythonExe -- cannot restart."
        exit 1
    }
    Start-Process powershell.exe `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -Command `"Set-Location '$WorkerDir'; & '$PythonExe' '$WorkerScript' --url $CoordUrl`"" `
        -WorkingDirectory $WorkerDir
    Log "worker.py relaunched."
}

Log "Watchdog tick complete."
exit 0
