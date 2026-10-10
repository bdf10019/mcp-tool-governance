$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $projectRoot '.venv'
if (-not (Test-Path -LiteralPath $venv)) {
    python -m venv $venv
}
& (Join-Path $venv 'Scripts\python.exe') -m pip install --requirement (Join-Path $projectRoot 'requirements.lock.txt')
Push-Location (Join-Path $projectRoot 'frontend')
try {
    pnpm install --frozen-lockfile
    pnpm run build
}
finally {
    Pop-Location
}

