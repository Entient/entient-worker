# start_brockpc.ps1 - Master launcher for BrockPC's 3 persistent loops
# Run once on startup (or manually). Each loop runs in its own window.
# Usage: powershell -ExecutionPolicy Bypass -File C:\entient-worker\start_brockpc.ps1

$BASE = "C:\entient-worker"

Write-Host "=== BrockPC startup ===" -ForegroundColor Cyan
Write-Host ""

# 1. Worker - claims jobs from master coordinator
Write-Host "[1] Starting worker (coordinator jobs)..." -ForegroundColor Green
$w = Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -NoExit -Command python $BASE\worker.py" -PassThru
Write-Host "    PID $($w.Id)"

Start-Sleep -Seconds 2

# 2. Mine loop - continuous repo mining
Write-Host "[2] Starting mine loop..." -ForegroundColor Green
$m = Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -NoExit -File $BASE\mine_loop.ps1" -PassThru
Write-Host "    PID $($m.Id)"

Start-Sleep -Seconds 2

# 3. Synth loop - continuous Qwen operator synthesis
Write-Host "[3] Starting synth loop (Qwen)..." -ForegroundColor Green
$s = Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -NoExit -File $BASE\synth_loop.ps1" -PassThru
Write-Host "    PID $($s.Id)"

Write-Host ""
Write-Host "All 3 loops running. PIDs: worker=$($w.Id), mine=$($m.Id), synth=$($s.Id)" -ForegroundColor Cyan
Write-Host "Logs:"
Write-Host "  Worker:  check coordinator at http://100.101.178.111:8420/status"
Write-Host "  Mine:    C:\Users\Brock\.entient\v2\mine_loop.log"
Write-Host "  Synth:   C:\Users\Brock\.entient\v2\synth_loop.log"
