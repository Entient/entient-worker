# synth_loop.ps1 - Continuous Ollama synthesis loop for BrockPC
# Generates operators via Qwen, uploads new ones to coordinator after each round.

$INTERCEPTOR = "C:\entient-worker\repos\entient-interceptor"
$PYTHON = "C:\entient-worker\.venv\Scripts\python.exe"
$MODEL = "qwen2.5-coder:7b"
$COUNT = 50
$LOG = "C:\Users\Brock\.entient\v2\synth_loop.log"
$BANK = "C:\Users\Brock\.entient\bank"
$COORDINATOR = "http://100.101.178.111:8420"
$BASE = "C:\entient-worker"
$round = 0

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

function Upload-NewOps() {
    Log "Upload: checking for new operators to push..."
    & $PYTHON "$BASE\upload_new_ops.py" --coordinator $COORDINATOR --bank $BANK 2>&1 | ForEach-Object { Log "  $_" }
}

Log "=== synth_loop starting (model=$MODEL, count=$COUNT) ==="

while ($true) {
    $round++
    Log "--- Round $round ---"

    try {
        # Refresh miss clusters
        Log "Refreshing miss clusters..."
        & $PYTHON "$INTERCEPTOR\tools\miss_cluster_analysis.py" --force 2>&1
        if ($LASTEXITCODE -eq 0) {
            Log "Miss clusters refreshed."
        } else {
            Log "Miss cluster refresh failed (exit $LASTEXITCODE) - using existing clusters."
        }

        # Run synthesis batch
        Log "Running synthesis (count=$COUNT)..."
        & $PYTHON "$INTERCEPTOR\tools\bulk_synthesize.py" --ollama $MODEL --count $COUNT
        Log "Synthesis round $round done (exit=$LASTEXITCODE)."

        # Upload any new operators to coordinator
        Upload-NewOps

        # Grade ops and queue polish jobs for shallow ones
        Log "Grading ops for quality..."
        & $PYTHON "$BASE\grade_ops.py" --queue --top 5 --coordinator $COORDINATOR
        Log "Grade pass done (exit=$LASTEXITCODE)."

    } catch {
        Log "Round $round exception: $_ - continuing..."
    }

    Start-Sleep -Seconds 10
}
