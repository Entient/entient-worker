# install_sync_task.ps1 - Install ENTIENT-BrockPC-Sync scheduled task (requires admin)

$BASE = "C:\entient-worker"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File $BASE\sync.ps1"

# Run every 2 hours
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 2) -Once -At (Get-Date)
$boot = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName "ENTIENT-BrockPC-Sync" `
    -Action $action -Trigger $trigger,$boot -Settings $settings -Principal $principal -Force

Write-Host "ENTIENT-BrockPC-Sync installed. Runs every 2 hours + on boot."
