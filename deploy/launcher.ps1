param(
    [ValidateSet("Deploy", "Start", "Stop", "Status", "Doctor")]
    [string]$Action = "Deploy"
)

$script = Join-Path $PSScriptRoot "deploy.ps1"
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $script -Action $Action
exit $LASTEXITCODE
