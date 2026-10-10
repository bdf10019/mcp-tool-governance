$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:MCP_APP_ENV_KIND = 'automated_test'
$runId = [guid]::NewGuid().ToString('N')
$env:MCP_APP_DB_PATH = Join-Path $projectRoot ("tmp\test\e2e-$runId\app.db")
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m uvicorn backend.app.main:app --app-dir $projectRoot --host 127.0.0.1 --port 8132

