# Research-only scheduled collector. Does not issue or score predictions.
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$key = [Environment]::GetEnvironmentVariable('FINZDATA_API_KEY', 'User')
if (-not $key) { Write-Error 'FINZDATA_API_KEY is not configured for this Windows user'; exit 2 }
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { Write-Error 'Project Python environment is missing'; exit 2 }
$env:FINZDATA_API_KEY = $key
try {
    & $python (Join-Path $PSScriptRoot 'collect_finz_wti.py')
    exit $LASTEXITCODE
} finally {
    Remove-Item Env:\FINZDATA_API_KEY -ErrorAction SilentlyContinue
}
