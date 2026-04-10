# sync.ps1 - Bidirectional bank sync between BrockPC and coordinator
# Push new local ops up, pull new remote ops down.
# Runs on a schedule via ENTIENT-BrockPC-Sync task.

$PYTHON = "C:\entient-worker\.venv\Scripts\python.exe"
$BASE = "C:\entient-worker"
$BANK = "C:\Users\Brock\.entient\bank"
$COORDINATOR = "http://100.101.178.111:8420"
$LOG = "C:\Users\Brock\.entient\v2\sync.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

Log "=== Sync starting ==="

# --- PUSH: upload new local ops to coordinator ---
Log "PUSH: uploading new operators to coordinator..."
& $PYTHON "$BASE\upload_new_ops.py" --coordinator $COORDINATOR --bank $BANK
Log "PUSH done (exit=$LASTEXITCODE)."

# --- PULL: download new ops from coordinator ---
Log "PULL: syncing bank from coordinator..."
& $PYTHON "$BASE\pull_bank.py" --coordinator $COORDINATOR --bank $BANK
Log "PULL done (exit=$LASTEXITCODE)."

$localCount = (Get-ChildItem "$BANK\op_*.py" -ErrorAction SilentlyContinue | Measure-Object).Count
Log "=== Sync complete. Local bank: $localCount operators ==="
