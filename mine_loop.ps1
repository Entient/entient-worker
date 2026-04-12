# mine_loop.ps1 - Continuous repo mining loop for BrockPC
# Self-healing: restarts on any crash. Lock is PID-based so stale locks auto-clear.

$INTERCEPTOR = "C:\entient-worker\repos\entient-interceptor"
$PYTHON = "C:\entient-worker\.venv\Scripts\python.exe"
$LOG = "C:\Users\Brock\.entient\v2\mine_loop.log"
$LOCKFILE = "C:\Users\Brock\.entient\v2\mine.lock"
$env:ENTIENT_AGENT_REPO = "C:\entient-worker\repos\entient-agents"
$HARVEST_DB = "E:\entient\repos\pretrain_harvest.db"
$round = 0

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

function Is-LockStale($lockPath) {
    if (-not (Test-Path $lockPath)) { return $false }
    $pid = Get-Content $lockPath -ErrorAction SilentlyContinue
    if (-not $pid) { return $true }
    $proc = Get-Process -Id ([int]$pid) -ErrorAction SilentlyContinue
    return ($proc -eq $null)
}

Log "=== mine_loop starting (PID=$PID) ==="

while ($true) {
    $round++

    # Check lock - skip if a real mine job is running
    if (Test-Path $LOCKFILE) {
        if (Is-LockStale $LOCKFILE) {
            Log "Stale mine.lock cleared."
            Remove-Item $LOCKFILE -ErrorAction SilentlyContinue
        } else {
            Log "mine.lock active - waiting 30s..."
            Start-Sleep -Seconds 30
            continue
        }
    }

    Log "--- Round ${round}: mining all repo sets ---"
    $PID | Out-File $LOCKFILE -Encoding ascii

    try {
        & $PYTHON -W ignore::SyntaxWarning "$INTERCEPTOR\tools\mine_eye_bulk.py" --db $HARVEST_DB all --parallel
        $exit = $LASTEXITCODE
        Log "Round ${round} done (exit=$exit). Pausing 30s..."
    } catch {
        Log "Round ${round} exception: $_"
    } finally {
        Remove-Item $LOCKFILE -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 30
}
