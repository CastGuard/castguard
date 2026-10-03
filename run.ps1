param(
    [ValidateSet('all', 'validate', 'verify', 'run', 'summarize', 'rebuild-check', 'test')]
    [string]$Command = 'all',
    [int]$Jobs = 4
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Create a Python 3.12 .venv and install requirements-lock.txt first; see README.md.'
}
Push-Location $PSScriptRoot
try {
    if ($Command -eq 'test') {
        & $taskPython -m pytest -q
    } else {
        & $taskPython -u -m castguard $Command --jobs $Jobs
    }
    if ($LASTEXITCODE -ne 0) { throw "CastGuard failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
