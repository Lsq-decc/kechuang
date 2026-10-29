# Package-specific defaults for the Windows one-click deployer.
# Change Mode only when deploying a different project type.

@{
    AppName = "kechuang"
    Mode = "Python"
    InstallDependencies = $true
    AutoInstallRuntimes = $true
    Offline = $false
    InstallOcrDependencies = $false
    UseSqlite = $true
    RunBuild = $true
    StartAfterDeploy = $true

    Url = "http://127.0.0.1:8000"
    HealthCheckUrl = ""
    Port = 8080
    UpgradePipTools = $false
    PipIndexUrl = ""
    PythonCommand = ""
    NodeCommand = ""
    DockerComposeFile = ""
    StartExecutable = ".venv\Scripts\python.exe"
    StartArguments = @("run_prod.py")
    WorkingDirectory = ""
}