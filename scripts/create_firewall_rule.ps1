$ErrorActionPreference = "Stop"

$port = if ($env:SERVER_PORT) { [int]$env:SERVER_PORT } else { 8000 }
$ruleName = "Kechuang Web Server $port"

if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Firewall rule already exists: $ruleName"
    exit 0
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $port `
    -Profile Private

Write-Host "Created firewall rule: $ruleName"

