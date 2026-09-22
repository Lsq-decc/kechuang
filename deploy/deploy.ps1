param(
    [ValidateSet("Deploy", "Start", "Stop", "Status", "Doctor")]
    [string]$Action = "Deploy",
    [switch]$NoStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$script:Root = Split-Path -Parent $PSScriptRoot
$script:DeployDir = Join-Path $script:Root ".deploy"
$script:StatePath = Join-Path $script:DeployDir "state.json"
$script:PidPath = Join-Path $script:DeployDir "app.pid"
$script:OutLog = Join-Path $script:DeployDir "app.out.log"
$script:ErrLog = Join-Path $script:DeployDir "app.err.log"
$script:Config = @{}
$script:State = @{}
$script:TranscriptStarted = $false

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [WARN] $Message" -ForegroundColor Yellow
}

function Failure {
    param([string]$Message)
    throw $Message
}

function Get-ConfigValue {
    param(
        [string]$Name,
        [object]$Default = $null
    )

    if ($script:Config.ContainsKey($Name)) {
        return $script:Config[$Name]
    }

    return $Default
}

function Get-StateValue {
    param(
        [string]$Name,
        [object]$Default = $null
    )

    if ($script:State.ContainsKey($Name)) {
        return $script:State[$Name]
    }

    return $Default
}

function Resolve-ProjectPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $script:Root
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $script:Root $Path))
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($machinePath, $userPath) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $env:Path = $parts -join ";"
}

function Add-PathPrefix {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $entries = $env:Path -split ";"
    if ($entries -notcontains $fullPath) {
        $env:Path = "$fullPath;$env:Path"
    }
}

function Get-CommandPath {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        return $null
    }

    if (-not [string]::IsNullOrWhiteSpace($command.Path)) {
        return $command.Path
    }

    if (-not [string]::IsNullOrWhiteSpace($command.Source)) {
        return $command.Source
    }

    return $null
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$ErrorMessage,
        [switch]$AllowFailure
    )

    Write-Info ("Run: {0} {1}" -f $FilePath, ($Arguments -join " "))
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        Failure ("{0} (exit code: {1})" -f $ErrorMessage, $exitCode)
    }

    return $exitCode
}

function Get-PackageScripts {
    param([string]$PackageJsonPath)

    if (-not (Test-Path -LiteralPath $PackageJsonPath -PathType Leaf)) {
        return @()
    }

    try {
        $package = Get-Content -LiteralPath $PackageJsonPath -Raw | ConvertFrom-Json
    }
    catch {
        Failure "Cannot parse package.json: $($_.Exception.Message)"
    }

    if ($null -eq $package.scripts) {
        return @()
    }

    return @($package.scripts.PSObject.Properties.Name)
}

function Get-ComposeFile {
    foreach ($name in @("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")) {
        $candidate = Join-Path $script:Root $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return $null
}

function Get-ProjectMode {
    $configured = [string](Get-ConfigValue -Name "Mode" -Default "Auto")
    if (-not [string]::IsNullOrWhiteSpace($configured) -and $configured -ne "Auto") {
        switch ($configured.ToLowerInvariant()) {
            "docker" { return "Docker" }
            "python" { return "Python" }
            "node" { return "Node" }
            "static" { return "Static" }
            "custom" { return "Custom" }
            default { Failure "Unsupported Mode '$configured'. Use Auto, Docker, Python, Node, Static, or Custom." }
        }
    }

    if (Test-Path -LiteralPath (Join-Path $script:Root "package.json") -PathType Leaf) {
        return "Node"
    }

    foreach ($name in @("requirements.txt", "pyproject.toml", "setup.py", "Pipfile")) {
        if (Test-Path -LiteralPath (Join-Path $script:Root $name) -PathType Leaf) {
            return "Python"
        }
    }

    if (Test-Path -LiteralPath (Join-Path $script:Root "index.html") -PathType Leaf) {
        return "Static"
    }

    $startFile = [string](Get-ConfigValue -Name "StartExecutable" -Default "")
    if (-not [string]::IsNullOrWhiteSpace($startFile)) {
        return "Custom"
    }

    Failure "Cannot detect the project type. Set Mode and StartExecutable in deploy/deploy.config.ps1."
}

function Get-PortablePython {
    foreach ($relative in @("runtime\python\python.exe", "runtime\python311\python.exe", "python\python.exe")) {
        $candidate = Join-Path $script:Root $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return $null
}

function Get-PortableNode {
    foreach ($relative in @("runtime\node\node.exe", "node\node.exe")) {
        $candidate = Join-Path $script:Root $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Add-PathPrefix (Split-Path -Parent $candidate)
            return $candidate
        }
    }

    return $null
}

function Install-WingetPackage {
    param(
        [string]$Id,
        [string]$DisplayName
    )

    $winget = Get-CommandPath "winget.exe"
    if ([string]::IsNullOrWhiteSpace($winget)) {
        Failure "$DisplayName is missing and winget is unavailable. Install it manually, or put a portable runtime under the runtime folder."
    }

    if ([bool](Get-ConfigValue -Name "Offline" -Default $false)) {
        Failure "$DisplayName is missing and Offline=true. Bundle its portable runtime before deploying without internet."
    }

    Write-Info "Installing $DisplayName with winget..."
    $arguments = @(
        "install",
        "--id", $Id,
        "--exact",
        "--silent",
        "--scope", "user",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity"
    )

    $exitCode = Invoke-External -FilePath $winget -Arguments $arguments -ErrorMessage "Failed to install $DisplayName" -AllowFailure
    if ($exitCode -ne 0) {
        Write-Warn "User-scope installation failed. Retrying without --scope."
        $arguments = @(
            "install",
            "--id", $Id,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity"
        )
        Invoke-External -FilePath $winget -Arguments $arguments -ErrorMessage "Failed to install $DisplayName" | Out-Null
    }

    Refresh-ProcessPath
}

function Resolve-PythonCommand {
    $configured = [string](Get-ConfigValue -Name "PythonCommand" -Default "")
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        $resolved = Resolve-ProjectPath $configured
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            Failure "PythonCommand does not exist: $resolved"
        }
        return $resolved
    }

    $portable = Get-PortablePython
    if ($null -ne $portable) {
        return $portable
    }

    $python = Get-CommandPath "python.exe"
    if (-not [string]::IsNullOrWhiteSpace($python)) {
        return $python
    }

    if ([bool](Get-ConfigValue -Name "AutoInstallRuntimes" -Default $true)) {
        Install-WingetPackage -Id "Python.Python.3.11" -DisplayName "Python 3.11"
        $python = Get-CommandPath "python.exe"
        if (-not [string]::IsNullOrWhiteSpace($python)) {
            return $python
        }

        foreach ($candidate in @(
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311-32\python.exe")
        )) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return $candidate
            }
        }
    }

    Failure "Python 3.11 was not found. Set PythonCommand in deploy/deploy.config.ps1."
}

function Assert-PythonWorks {
    param([string]$Python)

    $version = & $Python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    if ($LASTEXITCODE -ne 0) {
        Failure "Python check failed: $Python"
    }

    Write-Ok "Python $version ($Python)"
}

function Get-Wheelhouse {
    foreach ($relative in @("wheelhouse", "wheels", "offline\wheels", "offline\wheelhouse")) {
        $candidate = Join-Path $script:Root $relative
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return $candidate
        }
    }

    return $null
}

function Install-PythonMode {
    $python = Resolve-PythonCommand
    Assert-PythonWorks -Python $python

    $venvDir = Join-Path $script:Root ".venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Info "Creating virtual environment at $venvDir"
        Invoke-External -FilePath $python -Arguments @("-m", "venv", $venvDir) -ErrorMessage "Failed to create the virtual environment"
    }
    else {
        Write-Ok "Reusing virtual environment"
    }

    if (-not [bool](Get-ConfigValue -Name "InstallDependencies" -Default $true)) {
        Write-Warn "Dependency installation is disabled."
        return $venvPython
    }

    $pipBase = @("-m", "pip", "install", "--disable-pip-version-check")
    $wheelhouse = Get-Wheelhouse
    $offline = [bool](Get-ConfigValue -Name "Offline" -Default $false)

    if ($null -ne $wheelhouse) {
        $pipBase += @("--no-index", "--find-links", $wheelhouse)
        Write-Info "Using local Python wheelhouse: $wheelhouse"
    }
    elseif ($offline) {
        Failure "Offline=true but no wheelhouse/wheels folder was found."
    }

    if (-not $offline) {
        $upgradeArgs = $pipBase + @("--upgrade", "pip", "setuptools", "wheel")
        Invoke-External -FilePath $venvPython -Arguments $upgradeArgs -ErrorMessage "Failed to upgrade pip tooling"
    }

    $requirements = $null
    foreach ($name in @("requirements.txt", "requirements-prod.txt")) {
        $candidate = Join-Path $script:Root $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $requirements = $candidate
            break
        }
    }

    if ($null -ne $requirements) {
        $requirementsArgs = $pipBase + @("-r", $requirements)
        Invoke-External -FilePath $venvPython -Arguments $requirementsArgs -ErrorMessage "Failed to install Python requirements"
    }

    $pyproject = Join-Path $script:Root "pyproject.toml"
    $setupPy = Join-Path $script:Root "setup.py"
    if (Test-Path -LiteralPath $pyproject -PathType Leaf) {
        $projectArgs = $pipBase + @("-e", $script:Root)
        Invoke-External -FilePath $venvPython -Arguments $projectArgs -ErrorMessage "Failed to install the Python project"
    }
    elseif (Test-Path -LiteralPath $setupPy -PathType Leaf) {
        $projectArgs = $pipBase + @("-e", $script:Root)
        Invoke-External -FilePath $venvPython -Arguments $projectArgs -ErrorMessage "Failed to install the Python project"
    }

    Write-Ok "Python dependencies are ready"
    return $venvPython
}

function Resolve-NodeCommand {
    $configured = [string](Get-ConfigValue -Name "NodeCommand" -Default "")
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        $resolved = Resolve-ProjectPath $configured
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            Failure "NodeCommand does not exist: $resolved"
        }
        Add-PathPrefix (Split-Path -Parent $resolved)
        return $resolved
    }

    $portable = Get-PortableNode
    if ($null -ne $portable) {
        return $portable
    }

    $node = Get-CommandPath "node.exe"
    if (-not [string]::IsNullOrWhiteSpace($node)) {
        return $node
    }

    if ([bool](Get-ConfigValue -Name "AutoInstallRuntimes" -Default $true)) {
        Install-WingetPackage -Id "OpenJS.NodeJS.LTS" -DisplayName "Node.js LTS"
        $node = Get-CommandPath "node.exe"
        if (-not [string]::IsNullOrWhiteSpace($node)) {
            return $node
        }
    }

    Failure "Node.js LTS was not found. Set NodeCommand in deploy/deploy.config.ps1."
}

function Get-NodePackageManager {
    if (Test-Path -LiteralPath (Join-Path $script:Root "pnpm-lock.yaml") -PathType Leaf) {
        return "pnpm"
    }

    if (Test-Path -LiteralPath (Join-Path $script:Root "yarn.lock") -PathType Leaf) {
        return "yarn"
    }

    return "npm"
}

function Invoke-NodePackageManager {
    param(
        [string]$PackageManager,
        [string[]]$Arguments,
        [string]$ErrorMessage
    )

    if ($PackageManager -eq "npm") {
        $npm = Get-CommandPath "npm.cmd"
        if ([string]::IsNullOrWhiteSpace($npm)) {
            Failure "npm.cmd was not found."
        }
        Invoke-External -FilePath $npm -Arguments $Arguments -ErrorMessage $ErrorMessage | Out-Null
        return
    }

    $corepack = Get-CommandPath "corepack.cmd"
    if ([string]::IsNullOrWhiteSpace($corepack)) {
        $corepack = Get-CommandPath "corepack.exe"
    }
    if ([string]::IsNullOrWhiteSpace($corepack)) {
        Failure "$PackageManager is required, but corepack was not found."
    }

    Invoke-External -FilePath $corepack -Arguments (@($PackageManager) + $Arguments) -ErrorMessage $ErrorMessage | Out-Null
}

function Install-NodeMode {
    $node = Resolve-NodeCommand
    $nodeVersion = & $node --version
    if ($LASTEXITCODE -ne 0) {
        Failure "Node.js check failed: $node"
    }
    Write-Ok "Node.js $nodeVersion ($node)"

    if (-not [bool](Get-ConfigValue -Name "InstallDependencies" -Default $true)) {
        Write-Warn "Dependency installation is disabled."
        return
    }

    $packageManager = Get-NodePackageManager
    $nodeModules = Join-Path $script:Root "node_modules"
    $hasLock = Test-Path -LiteralPath (Join-Path $script:Root "package-lock.json") -PathType Leaf

    if ($packageManager -eq "npm" -and $hasLock -and -not (Test-Path -LiteralPath $nodeModules -PathType Container)) {
        Invoke-NodePackageManager -PackageManager $packageManager -Arguments @("ci") -ErrorMessage "npm ci failed"
    }
    else {
        Invoke-NodePackageManager -PackageManager $packageManager -Arguments @("install") -ErrorMessage "$packageManager install failed"
    }

    Write-Ok "Node.js dependencies are ready"
}

function Invoke-NodeBuild {
    $packageJson = Join-Path $script:Root "package.json"
    $scripts = Get-PackageScripts -PackageJsonPath $packageJson
    if (-not [bool](Get-ConfigValue -Name "RunBuild" -Default $true)) {
        return
    }

    if ($scripts -contains "build") {
        $packageManager = Get-NodePackageManager
        Write-Info "Running the production build..."
        Invoke-NodePackageManager -PackageManager $packageManager -Arguments @("run", "build") -ErrorMessage "npm build failed"
    }
}

function Resolve-DockerCommand {
    $docker = Get-CommandPath "docker.exe"
    if (-not [string]::IsNullOrWhiteSpace($docker)) {
        $null = & $docker compose version 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @($docker, "compose")
        }
    }

    $dockerCompose = Get-CommandPath "docker-compose.exe"
    if (-not [string]::IsNullOrWhiteSpace($dockerCompose)) {
        return @($dockerCompose)
    }

    Failure "Docker or Docker Compose was not found. Install Docker Desktop, then run deployment again."
}

function Install-DockerMode {
    $composeFile = [string](Get-ConfigValue -Name "DockerComposeFile" -Default "")
    if ([string]::IsNullOrWhiteSpace($composeFile)) {
        $composeFile = Get-ComposeFile
    }
    else {
        $composeFile = Resolve-ProjectPath $composeFile
    }

    if ([string]::IsNullOrWhiteSpace($composeFile) -or -not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
        Failure "Docker mode requires compose.yaml or docker-compose.yml."
    }

    $dockerCommand = Resolve-DockerCommand
    $baseArgs = @()
    if ($dockerCommand.Count -gt 1) {
        $baseArgs = @($dockerCommand[1..($dockerCommand.Count - 1)])
    }
    $baseArgs += @("-f", $composeFile)

    Invoke-External -FilePath $dockerCommand[0] -Arguments ($baseArgs + @("up", "-d", "--build")) -ErrorMessage "Docker Compose deployment failed" | Out-Null
    Write-Ok "Docker services are running"
}

function Resolve-PythonStartPlan {
    param([string]$VenvPython)

    $streamlitFile = Join-Path $script:Root "app.py"
    $requirementsFile = Join-Path $script:Root "requirements.txt"
    $pyprojectFile = Join-Path $script:Root "pyproject.toml"
    $usesStreamlit = $false

    foreach ($manifest in @($requirementsFile, $pyprojectFile)) {
        if (Test-Path -LiteralPath $manifest -PathType Leaf) {
            $text = Get-Content -LiteralPath $manifest -Raw
            if ($text -match "(?im)^\s*streamlit\b" -or $text -match "(?im)streamlit\s*[=><]") {
                $usesStreamlit = $true
            }
        }
    }

    if ($usesStreamlit -and (Test-Path -LiteralPath $streamlitFile -PathType Leaf)) {
        return @{
            Kind = "Background"
            Executable = $VenvPython
            Arguments = @("-m", "streamlit", "run", $streamlitFile, "--server.address", "0.0.0.0", "--server.port", "8501")
            WorkingDirectory = $script:Root
            Url = "http://127.0.0.1:8501"
        }
    }

    $managePy = Join-Path $script:Root "manage.py"
    if (Test-Path -LiteralPath $managePy -PathType Leaf) {
        return @{
            Kind = "Background"
            Executable = $VenvPython
            Arguments = @($managePy, "runserver", "0.0.0.0:8000")
            WorkingDirectory = $script:Root
            Url = "http://127.0.0.1:8000"
        }
    }

    foreach ($name in @("app.py", "main.py", "run.py", "server.py")) {
        $entryPoint = Join-Path $script:Root $name
        if (Test-Path -LiteralPath $entryPoint -PathType Leaf) {
            return @{
                Kind = "Background"
                Executable = $VenvPython
                Arguments = @($entryPoint)
                WorkingDirectory = $script:Root
                Url = "http://127.0.0.1:8000"
            }
        }
    }

    return $null
}

function Resolve-NodeStartPlan {
    $scripts = Get-PackageScripts -PackageJsonPath (Join-Path $script:Root "package.json")
    $scriptName = $null
    foreach ($candidate in @("start", "preview", "dev", "serve")) {
        if ($scripts -contains $candidate) {
            $scriptName = $candidate
            break
        }
    }

    if ($null -eq $scriptName) {
        return $null
    }

    $packageManager = Get-NodePackageManager
    $executable = $null
    $arguments = @()

    if ($packageManager -eq "npm") {
        $executable = Get-CommandPath "npm.cmd"
        $arguments = @("run", $scriptName)
    }
    else {
        $executable = Get-CommandPath "corepack.cmd"
        if ([string]::IsNullOrWhiteSpace($executable)) {
            $executable = Get-CommandPath "corepack.exe"
        }
        $arguments = @($packageManager, "run", $scriptName)
    }

    if ([string]::IsNullOrWhiteSpace($executable)) {
        return $null
    }

    return @{
        Kind = "Background"
        Executable = $executable
        Arguments = $arguments
        WorkingDirectory = $script:Root
        Url = "http://127.0.0.1:3000"
    }
}

function Resolve-CustomStartPlan {
    $executable = [string](Get-ConfigValue -Name "StartExecutable" -Default "")
    if ([string]::IsNullOrWhiteSpace($executable)) {
        return $null
    }

    $resolvedExecutable = Resolve-ProjectPath $executable
    if (-not (Test-Path -LiteralPath $resolvedExecutable -PathType Leaf)) {
        $commandPath = Get-CommandPath $executable
        if ([string]::IsNullOrWhiteSpace($commandPath)) {
            Failure "StartExecutable does not exist and is not on PATH: $executable"
        }
        $resolvedExecutable = $commandPath
    }

    $argumentsValue = Get-ConfigValue -Name "StartArguments" -Default @()
    if ($argumentsValue -is [string]) {
        $arguments = @($argumentsValue)
    }
    else {
        $arguments = @($argumentsValue)
    }

    $workingDirectory = Resolve-ProjectPath ([string](Get-ConfigValue -Name "WorkingDirectory" -Default ""))
    return @{
        Kind = "Background"
        Executable = $resolvedExecutable
        Arguments = $arguments
        WorkingDirectory = $workingDirectory
        Url = [string](Get-ConfigValue -Name "Url" -Default "http://127.0.0.1:8000")
    }
}

function Resolve-StartPlan {
    param(
        [string]$Mode,
        [string]$VenvPython
    )

    $custom = [string](Get-ConfigValue -Name "StartExecutable" -Default "")
    if (-not [string]::IsNullOrWhiteSpace($custom)) {
        return Resolve-CustomStartPlan
    }

    switch ($Mode) {
        "Python" {
            $plan = Resolve-PythonStartPlan -VenvPython $VenvPython
        }
        "Node" {
            $plan = Resolve-NodeStartPlan
        }
        "Static" {
            $python = Resolve-PythonCommand
            $port = [int](Get-ConfigValue -Name "Port" -Default 8080)
            $plan = @{
                Kind = "Background"
                Executable = $python
                Arguments = @("-m", "http.server", [string]$port, "--bind", "0.0.0.0", "--directory", $script:Root)
                WorkingDirectory = $script:Root
                Url = "http://127.0.0.1:$port"
            }
        }
        default {
            $plan = $null
        }
    }

    if ($null -ne $plan) {
        $configuredUrl = [string](Get-ConfigValue -Name "Url" -Default "")
        if (-not [string]::IsNullOrWhiteSpace($configuredUrl)) {
            $plan.Url = $configuredUrl
        }
        return $plan
    }

    Failure "No start command could be detected. Set StartExecutable and StartArguments in deploy/deploy.config.ps1."
}

function Save-State {
    param([hashtable]$State)

    New-Item -ItemType Directory -Path $script:DeployDir -Force | Out-Null
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $script:StatePath -Encoding UTF8
}

function Load-State {
    if (-not (Test-Path -LiteralPath $script:StatePath -PathType Leaf)) {
        Failure "No deployment state was found. Run the one-click deployment first."
    }

    try {
        $data = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
    }
    catch {
        Failure "Cannot read deployment state: $($_.Exception.Message)"
    }

    $state = @{}
    foreach ($property in $data.PSObject.Properties) {
        $state[$property.Name] = $property.Value
    }
    $script:State = $state
}

function ConvertTo-ArgumentString {
    param([object[]]$Arguments)

    $parts = @()
    foreach ($argument in $Arguments) {
        $value = [string]$argument
        if ($value -match '[\s"]') {
            $value = '"' + ($value -replace '"', '\"') + '"'
        }
        $parts += $value
    }

    return ($parts -join " ")
}

function Test-ProcessMatchesState {
    param([hashtable]$State)

    $pidValue = Get-StateValue -Name "ProcessId" -Default $null -ErrorAction SilentlyContinue
    if ($null -eq $pidValue) {
        return $false
    }

    $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }

    $storedStart = [string](Get-StateValue -Name "ProcessStartTime" -Default "")
    if ([string]::IsNullOrWhiteSpace($storedStart)) {
        return $true
    }

    try {
        $expected = [DateTime]::Parse($storedStart).ToUniversalTime()
        $actual = $process.StartTime.ToUniversalTime()
        return [math]::Abs(($expected - $actual).TotalSeconds) -lt 5
    }
    catch {
        return $true
    }
}

function Test-Health {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return $false
    }

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch {
        return $false
    }
}

function Start-App {
    param([switch]$Quiet)

    Load-State
    $kind = [string](Get-StateValue -Name "Kind" -Default "Background")
    $url = [string](Get-StateValue -Name "Url" -Default "")

    if ($kind -eq "Docker") {
        $executable = [string](Get-StateValue -Name "Executable" -Default "")
        $arguments = @(Get-StateValue -Name "Arguments" -Default @())
        Invoke-External -FilePath $executable -Arguments ($arguments + @("up", "-d")) -ErrorMessage "Failed to start Docker services" | Out-Null
        Write-Ok "Docker services are running"
        if (-not [string]::IsNullOrWhiteSpace($url)) {
            Write-Info "URL: $url"
        }
        return
    }

    if (Test-ProcessMatchesState -State $script:State) {
        Write-Ok "The application is already running (PID $([int](Get-StateValue -Name 'ProcessId')))"
        if (-not [string]::IsNullOrWhiteSpace($url)) {
            Write-Info "URL: $url"
        }
        return
    }

    New-Item -ItemType Directory -Path $script:DeployDir -Force | Out-Null
    Remove-Item -LiteralPath $script:OutLog -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $script:ErrLog -Force -ErrorAction SilentlyContinue

    $executable = [string](Get-StateValue -Name "Executable" -Default "")
    $arguments = @(Get-StateValue -Name "Arguments" -Default @())
    $workingDirectory = [string](Get-StateValue -Name "WorkingDirectory" -Default $script:Root)

    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        Failure "The configured executable does not exist: $executable"
    }

    if (-not (Test-Path -LiteralPath $workingDirectory -PathType Container)) {
        Failure "The configured working directory does not exist: $workingDirectory"
    }

    $argumentString = ConvertTo-ArgumentString -Arguments $arguments
    if (-not $Quiet) {
        Write-Info "Starting: $executable $argumentString"
    }

    $process = Start-Process `
        -FilePath $executable `
        -ArgumentList $argumentString `
        -WorkingDirectory $workingDirectory `
        -RedirectStandardOutput $script:OutLog `
        -RedirectStandardError $script:ErrLog `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep -Seconds 2
    if ($process.HasExited) {
        $details = ""
        if (Test-Path -LiteralPath $script:ErrLog) {
            $details = (Get-Content -LiteralPath $script:ErrLog -Tail 30 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
        }
        Failure "The application exited immediately.`n$details"
    }

    $script:State["ProcessId"] = $process.Id
    $script:State["ProcessStartTime"] = $process.StartTime.ToUniversalTime().ToString("o")
    Save-State -State $script:State

    Write-Ok "Application started (PID $($process.Id))"
    if (-not [string]::IsNullOrWhiteSpace($url)) {
        Write-Info "URL: $url"
    }
    Write-Info "Logs: $script:OutLog"
}

function Stop-App {
    Load-State
    $kind = [string](Get-StateValue -Name "Kind" -Default "Background")

    if ($kind -eq "Docker") {
        $executable = [string](Get-StateValue -Name "Executable" -Default "")
        $arguments = @(Get-StateValue -Name "Arguments" -Default @())
        Invoke-External -FilePath $executable -Arguments ($arguments + @("stop")) -ErrorMessage "Failed to stop Docker services" | Out-Null
        Write-Ok "Docker services stopped"
        return
    }

    if (-not (Test-ProcessMatchesState -State $script:State)) {
        Write-Warn "No running application process was found."
        Remove-Item -LiteralPath $script:PidPath -Force -ErrorAction SilentlyContinue
        return
    }

    $processId = [int](Get-StateValue -Name "ProcessId")
    Invoke-External -FilePath "taskkill.exe" -Arguments @("/PID", [string]$processId, "/T", "/F") -ErrorMessage "Failed to stop PID $processId" | Out-Null
    Remove-Item -LiteralPath $script:PidPath -Force -ErrorAction SilentlyContinue
    $script:State.Remove("ProcessId") | Out-Null
    $script:State.Remove("ProcessStartTime") | Out-Null
    Save-State -State $script:State
    Write-Ok "Application stopped"
}

function Show-Status {
    Load-State
    $kind = [string](Get-StateValue -Name "Kind" -Default "Background")
    $mode = [string](Get-StateValue -Name "Mode" -Default "")
    $url = [string](Get-StateValue -Name "Url" -Default "")

    Write-Section "Application status"
    Write-Info "Mode: $mode"
    Write-Info "Start kind: $kind"
    if (-not [string]::IsNullOrWhiteSpace($url)) {
        Write-Info "Configured URL: $url"
    }

    if ($kind -eq "Docker") {
        $executable = [string](Get-StateValue -Name "Executable" -Default "")
        $arguments = @(Get-StateValue -Name "Arguments" -Default @())
        Invoke-External -FilePath $executable -Arguments ($arguments + @("ps")) -ErrorMessage "Failed to read Docker service status" -AllowFailure | Out-Null
    }
    elseif (Test-ProcessMatchesState -State $script:State) {
        Write-Ok "Running (PID $([int](Get-StateValue -Name 'ProcessId')))"
    }
    else {
        Write-Warn "Not running"
    }

    if (-not [string]::IsNullOrWhiteSpace($url)) {
        if (Test-Health -Url $url) {
            Write-Ok "Health check passed: $url"
        }
        else {
            Write-Warn "Health check did not respond yet: $url"
        }
    }
}

function Show-Doctor {
    param([string]$DetectedMode)

    Write-Section "Environment"
    Write-Info "Package root: $script:Root"
    Write-Info "PowerShell: $($PSVersionTable.PSVersion)"
    Write-Info "OS: $([Environment]::OSVersion.VersionString)"
    Write-Info "Detected mode: $DetectedMode"

    foreach ($tool in @("winget.exe", "python.exe", "node.exe", "npm.cmd", "docker.exe", "docker-compose.exe", "git.exe")) {
        $path = Get-CommandPath $tool
        if ([string]::IsNullOrWhiteSpace($path)) {
            Write-Warn "$tool not found"
        }
        else {
            Write-Ok "$tool -> $path"
        }
    }

    if (Test-Path -LiteralPath $script:StatePath -PathType Leaf) {
        Write-Ok "Deployment state exists: $script:StatePath"
    }
    else {
        Write-Warn "No deployment state found yet"
    }
}

function Invoke-Deploy {
    $mode = Get-ProjectMode
    Write-Section "Deploying $([string](Get-ConfigValue -Name 'AppName' -Default 'application'))"
    Write-Info "Mode: $mode"

    $venvPython = $null
    $kind = "Background"
    $dockerExecutable = $null
    $dockerArguments = @()

    switch ($mode) {
        "Python" {
            $venvPython = Install-PythonMode
        }
        "Node" {
            Install-NodeMode
            Invoke-NodeBuild
        }
        "Docker" {
            Install-DockerMode
            $kind = "Docker"
            $composeFile = [string](Get-ConfigValue -Name "DockerComposeFile" -Default "")
            if ([string]::IsNullOrWhiteSpace($composeFile)) {
                $composeFile = Get-ComposeFile
            }
            else {
                $composeFile = Resolve-ProjectPath $composeFile
            }
            $dockerCommand = Resolve-DockerCommand
            $dockerExecutable = $dockerCommand[0]
            if ($dockerCommand.Count -gt 1) {
                $dockerArguments = @($dockerCommand[1..($dockerCommand.Count - 1)])
            }
            $dockerArguments += @("-f", $composeFile)
        }
        "Static" {
            $null = Resolve-PythonCommand
        }
        "Custom" {
            if (-not [bool](Get-ConfigValue -Name "InstallDependencies" -Default $true)) {
                Write-Warn "Dependency installation is disabled."
            }
        }
    }

    $plan = $null
    if ($kind -eq "Docker") {
        $plan = @{
            Kind = "Docker"
            Executable = $dockerExecutable
            Arguments = $dockerArguments
            WorkingDirectory = $script:Root
            Url = [string](Get-ConfigValue -Name "Url" -Default "")
        }
    }
    else {
        $plan = Resolve-StartPlan -Mode $mode -VenvPython $venvPython
    }

    $state = @{
        AppName = [string](Get-ConfigValue -Name "AppName" -Default "application")
        Root = $script:Root
        Mode = $mode
        Kind = [string]$plan.Kind
        Executable = [string]$plan.Executable
        Arguments = @($plan.Arguments)
        WorkingDirectory = [string]$plan.WorkingDirectory
        Url = [string]$plan.Url
        DeployedAt = (Get-Date).ToString("o")
    }

    Save-State -State $state
    $script:State = $state
    Write-Ok "Deployment configuration saved"

    $shouldStart = [bool](Get-ConfigValue -Name "StartAfterDeploy" -Default $true)
    if ($NoStart) {
        $shouldStart = $false
    }

    if ($shouldStart) {
        Start-App
    }
    else {
        Write-Warn "Automatic startup is disabled. Run start-application.bat when ready."
    }
}

function Invoke-Main {
    try {
        New-Item -ItemType Directory -Path $script:DeployDir -Force | Out-Null
        $transcript = Join-Path $script:DeployDir "deploy.log"
        try {
            Start-Transcript -LiteralPath $transcript -Append | Out-Null
            $script:TranscriptStarted = $true
        }
        catch {
            Write-Warn "Could not start the deployment log."
        }

        switch ($Action) {
            "Deploy" {
                Invoke-Deploy
            }
            "Start" {
                Start-App
            }
            "Stop" {
                Stop-App
            }
            "Status" {
                Show-Status
            }
            "Doctor" {
                $detectedMode = try { Get-ProjectMode } catch { "Unknown" }
                Show-Doctor -DetectedMode $detectedMode
            }
        }
    }
    finally {
        if ($script:TranscriptStarted) {
            Stop-Transcript | Out-Null
        }
    }
}

$configPath = Join-Path $PSScriptRoot "deploy.config.ps1"
if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    $loadedConfig = & $configPath
    if ($null -ne $loadedConfig) {
        foreach ($property in $loadedConfig.PSObject.Properties) {
            $script:Config[$property.Name] = $property.Value
        }
    }
}

Invoke-Main
