# monitor.ps1 - BrockPC live status monitor
# Usage: powershell -ExecutionPolicy Bypass -File C:\entient-worker\monitor.ps1
# Refreshes every 30s. Ctrl+C to exit.

$COORDINATOR = "http://100.101.178.111:8420"
$BANK = "C:\Users\Brock\.entient\bank"
$SYNTH_LOG = "C:\Users\Brock\.entient\v2\synth_loop.log"
$MINE_LOG = "C:\Users\Brock\.entient\v2\mine_loop.log"
$INTERVAL = 30

function Get-ProcsByScript($keyword) {
    return Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*$keyword*" }
}

function Show-LogTail($path, $lines) {
    if (Test-Path $path) {
        Get-Content $path -Tail $lines | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    } else {
        Write-Host "    (no log yet)" -ForegroundColor DarkGray
    }
}

function Show-Status {
    Clear-Host
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "=== BrockPC Monitor  $ts ===" -ForegroundColor Cyan
    Write-Host ""

    # --- Bank ---
    $bankCount = (Get-ChildItem "$BANK\op_*.py" -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host "BANK: $bankCount operators" -ForegroundColor Yellow
    Write-Host ""

    # --- Worker ---
    Write-Host "WORKER" -ForegroundColor Green
    $wProcs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*worker.py*" }
    if ($wProcs) {
        foreach ($p in $wProcs) { Write-Host "  Running  PID $($p.ProcessId)" -ForegroundColor Green }
    } else {
        Write-Host "  NOT RUNNING" -ForegroundColor Red
    }
    try {
        $status = Invoke-RestMethod -Uri "$COORDINATOR/status" -TimeoutSec 5 -ErrorAction Stop
        $pending = $status.job_counts.pending
        $active = $status.job_counts.active
        $completed = $status.job_counts.completed
        Write-Host "  Coordinator: pending=$pending  active=$active  completed=$completed" -ForegroundColor White
        if ($status.workers) {
            foreach ($w in $status.workers) {
                Write-Host "  Registered: $($w.name) [$($w.state)]" -ForegroundColor White
            }
        } else {
            Write-Host "  Registered: none" -ForegroundColor DarkYellow
        }
    } catch {
        Write-Host "  Coordinator unreachable" -ForegroundColor Red
    }
    Write-Host ""

    # --- Mine Loop ---
    Write-Host "MINE LOOP" -ForegroundColor Green
    $mProcs = Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*mine_loop*" }
    if ($mProcs) {
        foreach ($p in $mProcs) { Write-Host "  Running  PID $($p.ProcessId)" -ForegroundColor Green }
    } else {
        Write-Host "  NOT RUNNING" -ForegroundColor Red
    }
    Write-Host "  Last log:"
    Show-LogTail $MINE_LOG 3
    Write-Host ""

    # --- Synth Loop ---
    Write-Host "SYNTH LOOP (Qwen)" -ForegroundColor Green
    $sProcs = Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*synth_loop*" }
    if ($sProcs) {
        foreach ($p in $sProcs) { Write-Host "  Running  PID $($p.ProcessId)" -ForegroundColor Green }
    } else {
        Write-Host "  NOT RUNNING" -ForegroundColor Red
    }
    Write-Host "  Last log:"
    Show-LogTail $SYNTH_LOG 3
    Write-Host ""

    # --- Synth throughput ---
    if (Test-Path $SYNTH_LOG) {
        $written = (Select-String -Path $SYNTH_LOG -Pattern "Synthesis round \d+ done" -ErrorAction SilentlyContinue | Measure-Object).Count
        Write-Host "  Completed rounds: $written" -ForegroundColor White
    }

    Write-Host ""
    Write-Host "Refreshing every ${INTERVAL}s  (Ctrl+C to exit)" -ForegroundColor DarkGray
}

while ($true) {
    Show-Status
    Start-Sleep -Seconds $INTERVAL
}
