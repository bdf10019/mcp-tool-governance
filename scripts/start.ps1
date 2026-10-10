$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Missing project Python environment. Run scripts\bootstrap.ps1 first.'
}
& $python -m uvicorn backend.app.main:app --app-dir $projectRoot --host 127.0.0.1 --port 8130

