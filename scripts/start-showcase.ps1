$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$showcaseRoot = Join-Path $projectRoot "showcase"

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "找不到 pnpm。請使用專案已記錄的 Node.js 24 與 pnpm 11 環境。"
}

Set-Location -LiteralPath $showcaseRoot
if (-not (Test-Path -LiteralPath (Join-Path $showcaseRoot "node_modules"))) {
    pnpm install --frozen-lockfile
}
if (-not (Test-Path -LiteralPath (Join-Path $showcaseRoot "dist\index.html"))) {
    pnpm build
}
pnpm preview
