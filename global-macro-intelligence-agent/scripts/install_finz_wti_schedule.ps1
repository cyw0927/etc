# Install a daily research-only collector, never replace an existing task.
# Recommended: run this script from a dedicated worktree (e.g. C:\dev\etc-ops) and pass -DataProject pointing at
# the main project, so branch switches in the main working tree cannot change or break the job.
param([string]$DataProject, [string]$Python)
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
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $runner
if ($DataProject) { $arguments += ' -DataProject "{0}"' -f $DataProject }
if ($Python) { $arguments += ' -Python "{0}"' -f $Python }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At '06:30'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'GMIA WTI research snapshots only; no forecasts or ledger changes.' | Out-Null
Write-Output 'Research collector task registered for 06:30 local time daily.'
