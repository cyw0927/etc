# Research-only scheduled collector. Does not issue or score predictions.
# Every run writes a log under data\operations\logs\finz_wti\ (git branch/commit, exit code, collector
# stdout/stderr). The API key is passed only through this process's environment and is never logged.
# Exit codes: 0 ok, 1 collector failed, 2 setup problem (key/venv), 3 collector missing on this branch.
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $project 'data\operations\logs\finz_wti'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log = Join-Path $logDir "finz-wti-$stamp.log"

function Write-Log([string]$message) {
    $line = '{0} {1}' -f (Get-Date).ToUniversalTime().ToString('o'), $message
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

function Finish([int]$code, [string]$message) {
    Write-Log "exit=$code $message"
    exit $code
}

function Get-Git([string[]]$gitArgs) {
    # Native stderr under ErrorActionPreference=Stop would abort the script (PowerShell 5.1); never let
    # a missing git or a non-repo folder prevent the log from being written.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $value = & git -C $project @gitArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and $value) { return "$value".Trim() }
        return 'unknown'
    } catch { return 'unknown' } finally { $ErrorActionPreference = $previous }
}

Write-Log "start project=$project"
$branch = Get-Git @('rev-parse', '--abbrev-ref', 'HEAD')
$commit = Get-Git @('rev-parse', '--short', 'HEAD')
Write-Log "git branch=$branch commit=$commit"

$collector = Join-Path $PSScriptRoot 'collect_finz_wti.py'
if (-not (Test-Path -LiteralPath $collector)) { Finish 3 "collect_finz_wti.py not found on branch '$branch'" }
$key = [Environment]::GetEnvironmentVariable('FINZDATA_API_KEY', 'User')
if (-not $key) { Finish 2 'FINZDATA_API_KEY is not configured for this Windows user' }
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { Finish 2 'Project Python environment is missing' }

$out = "$log.stdout"
$err = "$log.stderr"
$env:FINZDATA_API_KEY = $key
try {
    $proc = Start-Process -FilePath $python -ArgumentList ('"{0}"' -f $collector) -WorkingDirectory $project `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $code = $proc.ExitCode
} finally {
    Remove-Item Env:\FINZDATA_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable key -ErrorAction SilentlyContinue
}
foreach ($pair in @(@('stdout', $out), @('stderr', $err))) {
    if (Test-Path -LiteralPath $pair[1]) {
        Get-Content -LiteralPath $pair[1] -Encoding UTF8 | ForEach-Object { Write-Log ("{0}: {1}" -f $pair[0], $_) }
        Remove-Item -LiteralPath $pair[1]
    }
}
if ($code -ne 0) { Finish 1 'collector failed' }
Finish 0 'ok'
