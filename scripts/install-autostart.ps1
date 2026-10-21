# Registers two scheduled tasks: one starts Quill when you sign in to Windows (and restarts it
# if it crashes), the other backs up the database nightly.
# Run once:  powershell -File scripts\install-autostart.ps1
# Remove later with:  Unregister-ScheduledTask -TaskName Quill
$start = Join-Path $PSScriptRoot "start-quill.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$start`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "Quill" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Quill essay editor server" -Force | Out-Null
Write-Host "Quill will start automatically when you sign in. Start it now with: Start-ScheduledTask -TaskName Quill"

# Nightly database backup at 3 AM (runs at next wake if the laptop was asleep).
$root = Split-Path -Parent $PSScriptRoot
$backupAction = New-ScheduledTaskAction -Execute (Join-Path $root ".venv\Scripts\python.exe") `
    -Argument "`"$(Join-Path $root 'backend\manage.py')`" backup" -WorkingDirectory $root
$backupTrigger = New-ScheduledTaskTrigger -Daily -At 3am
$backupSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "Quill Backup" -Action $backupAction -Trigger $backupTrigger `
    -Settings $backupSettings -Description "Nightly Quill database backup" -Force | Out-Null
Write-Host "Nightly backups scheduled (data\backups, last 14 kept). Remove with: Unregister-ScheduledTask -TaskName 'Quill Backup'"
