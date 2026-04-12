# cleanup_temp_dirs.ps1 - Free disk space on C: drive
# Cleans temp files, Python caches, old logs, mining artifacts
# Safe to run anytime. Never touches bank, DBs, or source code.

param(
    [int]$MaxAgeDays = 2,
    [switch]$DryRun
)

$LOG = "C:\Users\Brock\.entient\v2\cleanup.log"
$TempRoot = $env:TEMP
$CutoffDate = (Get-Date).AddDays(-$MaxAgeDays)

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line -ErrorAction SilentlyContinue
}

function Remove-Dir($path, $label) {
    if (-not (Test-Path $path)) { return }
    $sizeMB = [math]::Round((Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    if ($DryRun) {
        Log "  [DRY RUN] Would clean $label ($sizeMB MB)"
    } else {
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        Log "  Cleaned $label ($sizeMB MB)"
    }
}

function Remove-Pattern($root, $filter, $label, $ageFilter = $false) {
    $items = Get-ChildItem $root -Filter $filter -Recurse -ErrorAction SilentlyContinue
    if ($ageFilter) { $items = $items | Where-Object { $_.LastWriteTime -lt $CutoffDate } }
    if (-not $items) { return }
    $sizeMB = [math]::Round(($items | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    $count = @($items).Count
    if ($DryRun) {
        Log "  [DRY RUN] Would clean $label ($sizeMB MB, $count files)"
    } else {
        $items | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Log "  Cleaned $label ($sizeMB MB, $count files)"
    }
}

$before = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
Log "=== Cleanup starting$(if ($DryRun){' [DRY RUN]'}). C: free: ${before} GB ==="

# --- Mining temp dirs (wormhole_*, eye_harvest_*) ---
Log "Mining temp dirs..."
@("wormhole_*", "eye_harvest_*", "tmp_probe_*") | ForEach-Object {
    Get-ChildItem $TempRoot -Filter $_ -ErrorAction SilentlyContinue |
        Where-Object { $_.PSIsContainer -and $_.LastWriteTime -lt $CutoffDate } |
        ForEach-Object {
            $mb = [math]::Round((Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum / 1MB, 1)
            if ($DryRun) { Log "  [DRY RUN] $($_.FullName) ($mb MB)" }
            else { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue; Log "  Removed $($_.Name) ($mb MB)" }
        }
}

# --- User temp dir ---
Log "User temp dir..."
Get-ChildItem $TempRoot -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $CutoffDate } |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
$tempMB = [math]::Round((Get-ChildItem $TempRoot -Recurse -ErrorAction SilentlyContinue |
    Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Log "  User temp remaining: $tempMB MB"

# --- Python caches ---
Log "Python caches..."
Get-ChildItem "C:\entient-worker" -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { if (-not $DryRun) { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue } }
Remove-Pattern "C:\entient-worker" "*.pyc" "*.pyc files"
Log "  Python cache cleared"

# --- Old bulk_specs JSON files (keep 3 newest) ---
Log "Old bulk_specs files..."
Get-ChildItem "C:\entient-worker\repos\entient-interceptor" -Filter "bulk_specs_*.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 |
    ForEach-Object {
        $mb = [math]::Round($_.Length / 1MB, 2)
        if ($DryRun) { Log "  [DRY RUN] $($_.Name) ($mb MB)" }
        else { Remove-Item $_.FullName -Force; Log "  Removed $($_.Name) ($mb MB)" }
    }

# --- worker_results/ per-job upload dirs ---
# Each job drops a full pretrain_harvest.db snapshot (~2-3 GB) here after upload.
# Once ingested by coordinator they are redundant. Keep nothing older than MaxAgeDays.
Log "Worker result dirs..."
$workerResultsRoot = "C:\Users\Brock\.entient\v2\worker_results"
if (Test-Path $workerResultsRoot) {
    Get-ChildItem $workerResultsRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $CutoffDate } |
        ForEach-Object {
            $mb = [math]::Round((Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum / 1MB, 1)
            if ($DryRun) { Log "  [DRY RUN] $($_.Name) ($mb MB)" }
            else { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue; Log "  Removed worker_results/$($_.Name) ($mb MB)" }
        }
} else {
    Log "  worker_results not found, skipping"
}

# --- Claude temp output files ---
Log "Claude temp outputs..."
Remove-Dir "C:\Users\Brock\AppData\Local\Temp\claude" "Claude temp outputs"

# --- Trim log files to last 500 lines ---
Log "Trimming logs..."
@("synth_loop.log","mine_loop.log","worker.log","brockpc_watchdog.log","sync.log","cleanup.log","watcher.log") |
    ForEach-Object {
        $p = "C:\Users\Brock\.entient\v2\$_"
        if (-not (Test-Path $p)) { $p = "C:\Users\Brock\.entient\$_" }
        if (Test-Path $p) {
            $lines = Get-Content $p -ErrorAction SilentlyContinue
            if ($lines.Count -gt 500) {
                if (-not $DryRun) { $lines | Select-Object -Last 500 | Set-Content $p }
                Log "  Trimmed $_ ($($lines.Count) -> 500 lines)"
            }
        }
    }

$after = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
$freed = [math]::Round($after - $before, 2)
Log "=== Cleanup done. C: free: ${after} GB (freed ${freed} GB) ==="
