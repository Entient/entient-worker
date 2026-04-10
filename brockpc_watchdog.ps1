# brockpc_watchdog.ps1 - Master watchdog for all BrockPC loops
# Scheduled to run every 5 minutes. Ensures worker, mine, synth are always running.
# Installs itself as a scheduled task on first run with -Install flag.

param([switch]$Install)

$BASE = "C:\entient-worker"
$LOG = "C:\Users\Brock\.entient\v2\brockpc_watchdog.log"
$PYTHON = "$BASE\.venv\Scripts\python.exe"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

function Is-Running($scriptName) {
    $procs = Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*$scriptName*" }
    return ($procs -ne $null -and @($procs).Count -gt 0)
}

function Is-PythonRunning($scriptName) {
    $procs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*$scriptName*" }
    return ($procs -ne $null -and @($procs).Count -gt 0)
}

function Start-Loop($scriptName, $label) {
    Log "Starting $label..."
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -NoExit -File $BASE\$scriptName" -WindowStyle Normal
}

function Start-Worker() {
    Log "Starting worker..."
    $workerLog = "C:\Users\Brock\.entient\v2\worker.log"
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -Command & '$PYTHON' '$BASE\worker.py' *>> '$workerLog'" -WindowStyle Hidden
}

function Kill-Duplicates($scriptPattern, $label) {
    $procs = @(Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*$scriptPattern*" })
    if ($procs.Count -gt 1) {
        $sorted = $procs | Sort-Object ProcessId
        $sorted | Select-Object -Skip 1 | ForEach-Object {
            Log "Killing duplicate $label PID $($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($Install) {
    # Re-launch as admin if not already elevated
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$BASE\brockpc_watchdog.ps1`" -Install"
        return
    }
    Log "Installing ENTIENT-BrockPC-Watchdog scheduled task..."
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File $BASE\brockpc_watchdog.ps1"
    $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)
    $boot = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName "ENTIENT-BrockPC-Watchdog" `
        -Action $action -Trigger $trigger,$boot -Settings $settings -Principal $principal -Force
    Log "Installed. Runs every 5 min + on boot."

    # Also register start_brockpc as a one-time startup task
    $startAction = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File $BASE\start_brockpc.ps1"
    $startTrigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName "ENTIENT-BrockPC-Start" `
        -Action $startAction -Trigger $startTrigger -Settings $settings -Principal $principal -Force
    Log "Installed ENTIENT-BrockPC-Start (at boot)."
    return
}

Log "=== BrockPC watchdog tick ==="

# 0. Disk space check - auto-cleanup if C: drops below 10 GB
$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Log "Disk: C: free = ${freeGB} GB"
if ($freeGB -lt 10) {
    Log "WARNING: Low disk space (${freeGB} GB). Running cleanup..."
    & powershell -ExecutionPolicy Bypass -File "$BASE\cleanup_temp_dirs.ps1"
    $freeAfter = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
    Log "Disk after cleanup: ${freeAfter} GB free"
}
if ($freeGB -lt 3) {
    Log "CRITICAL: C: nearly full (${freeGB} GB). Pausing mine loop to prevent crash."
    Get-WmiObject Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*mine_loop*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Log "Mine loop paused until disk is recovered."
}

# 1. Worker - kill duplicates, restart if dead
Kill-Duplicates "worker.py" "worker"
if (-not (Is-PythonRunning "worker.py")) {
    Start-Worker
} else {
    Log "Worker: OK"
}

# 2. Mine loop
if (-not (Is-Running "mine_loop")) {
    Start-Loop "mine_loop.ps1" "mine_loop"
} else {
    Log "Mine loop: OK"
}

# 3. Synth loop
if (-not (Is-Running "synth_loop")) {
    Start-Loop "synth_loop.ps1" "synth_loop"
} else {
    Log "Synth loop: OK"
}

Log "=== Watchdog tick done ==="
