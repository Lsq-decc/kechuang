# Copy this file when you need to override automatic detection.
# Keep Mode = "Auto" for normal packages.

@{
    AppName = "kechuang"
    Mode = "Auto"                  # Auto, Docker, Python, Node, Static, Custom
    InstallDependencies = $true
    AutoInstallRuntimes = $true    # Uses winget when Python/Node.js is missing.
    Offline = $false               # Set to $true when deploying without internet.
    RunBuild = $true               # Runs "npm run build" when package.json has that script.
    StartAfterDeploy = $true

    # Optional overrides:
    Url = ""
    HealthCheckUrl = ""
    Port = 8080
    PythonCommand = ""             # Example: "runtime\python\python.exe"
    NodeCommand = ""               # Example: "runtime\node\node.exe"
    DockerComposeFile = ""         # Example: "docker-compose.yml"
    StartExecutable = ""           # Example: "venv\Scripts\python.exe" or "npm.cmd"
    StartArguments = @()           # Example: @("run", "start")
    WorkingDirectory = ""          # Defaults to the package root.
}
