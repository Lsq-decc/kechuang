$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".env")) {
    throw "Missing .env. Copy .env.example to .env and set SECRET_KEY and database settings."
}

$port = if ($env:SERVER_PORT) { $env:SERVER_PORT } else { "8000" }
Write-Host "Starting kechuang server on 0.0.0.0:$port"
python run_prod.py

