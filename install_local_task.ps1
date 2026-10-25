# Registers a Windows scheduled task that runs local_portals.py every 6 hours while the
# PC is on, and once shortly after you log in (so a run missed while it was off happens
# when it is next used). Runs as the current user, only when logged on, no password stored.
#
#   powershell -ExecutionPolicy Bypass -File install_local_task.ps1
# Remove it with:  Unregister-ScheduledTask -TaskName "BharatVacancy local portals" -Confirm:$false

$taskName = "BharatVacancy local portals"
$script = Join-Path $PSScriptRoot "run_local_portals.cmd"

$action = New-ScheduledTaskAction -Execute $script
$every6h = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 6)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$atLogon.Delay = "PT10M"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($every6h, $atLogon) -Settings $settings `
    -Description "Fetches the portals that block data-centre IPs from this PC and sends them to bharatvacancy.com" -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
