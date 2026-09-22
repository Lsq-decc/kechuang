$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backupDir = Join-Path $projectRoot "backups"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $backupDir "kechuang-$timestamp.sql"

Push-Location $projectRoot
try {
    docker compose exec -T mysql mysqldump `
        -uroot `
        -proot `
        --single-transaction `
        --routines `
        --triggers `
        kechuang | Out-File -LiteralPath $backupFile -Encoding utf8
    Write-Host "Backup created: $backupFile"
}
finally {
    Pop-Location
}

