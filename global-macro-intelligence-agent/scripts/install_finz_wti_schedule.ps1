# Install a daily research-only collector, never replace an existing task.
$ErrorActionPreference = 'Stop'
$taskName = 'GMIA-FinzData-WTI-Research'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'A task with this name already exists; it was not modified.'
}
if (-not [Environment]::GetEnvironmentVariable('FINZDATA_API_KEY', 'User')) {
    throw 'FINZDATA_API_KEY is not configured for this Windows user.'
}
$runner = Join-Path $PSScriptRoot 'run_finz_wti.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw 'Collector runner not found.' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $runner)
$trigger = New-ScheduledTaskTrigger -Daily -At '06:30'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'GMIA WTI research snapshots only; no forecasts or ledger changes.' | Out-Null
Write-Output 'Research collector task registered for 06:30 local time daily.'
