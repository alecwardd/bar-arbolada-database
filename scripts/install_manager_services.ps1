[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Install", "Uninstall", "Validate", "Status", "RunApi", "RunTunnel")]
    [string]$Action = "Install",

    [string]$ProjectRoot = "",

    [string]$EnvironmentFile = "",

    [string]$CloudflaredExe = "",

    [string]$CloudflaredConfig = "",

    [ValidateSet("AtLogOn", "AtStartup")]
    [string]$StartupMode = "AtLogOn",

    [switch]$StartNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ApiTaskName = "BarArboladaManagerApi"
$TunnelTaskName = "BarArboladaManagerTunnel"
$ManagedTaskPath = "\BarArbolada\"
$ScriptPath = $MyInvocation.MyCommand.Path
$AllowedEnvironmentKeys = @(
    "MANAGER_DATABASE_URL",
    "MANAGER_API_TOKEN",
    "MANAGER_API_ALLOWED_HOSTS",
    "MANAGER_API_ALLOWED_ORIGINS",
    "MANAGER_API_ENABLE_DOCS",
    "MANAGER_API_READINESS_TIMEOUT_SECONDS"
)

function Get-FullExistingPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf) -and
        -not (Test-Path -LiteralPath $LiteralPath -PathType Container)) {
        throw "$Description is missing. Create the local file or directory before continuing."
    }
    return (Resolve-Path -LiteralPath $LiteralPath).Path
}

function Test-PathIsInside {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,

        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $candidateFull = [IO.Path]::GetFullPath($Candidate)
    $parentPrefix = [IO.Path]::GetFullPath($Parent).TrimEnd("\", "/") +
        [IO.Path]::DirectorySeparatorChar
    return $candidateFull.StartsWith(
        $parentPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-LocalOnlyConfigPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot,

        [switch]$RequireGitIgnored
    )

    $resolvedConfig = Get-FullExistingPath $ConfigPath "Local configuration"

    if (Test-PathIsInside $resolvedConfig $ResolvedProjectRoot) {
        if (-not $RequireGitIgnored) {
            return
        }

        $gitCommand = Get-Command "git.exe" -ErrorAction SilentlyContinue
        if ($null -eq $gitCommand) {
            throw "Git is required to verify that the local configuration is ignored."
        }

        $rootPrefix = $ResolvedProjectRoot.TrimEnd("\", "/") +
            [IO.Path]::DirectorySeparatorChar
        $relativePath = $resolvedConfig.Substring($rootPrefix.Length)
        & $gitCommand.Source -C $ResolvedProjectRoot check-ignore -q -- $relativePath
        if ($LASTEXITCODE -ne 0) {
            throw "Local configuration inside the repository must be ignored by Git."
        }
        return
    }

    $approvedParents = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $approvedParents += (Join-Path $env:LOCALAPPDATA "BarArbolada")
    }
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $approvedParents += (Join-Path $env:USERPROFILE ".cloudflared")
    }
    foreach ($approvedParent in $approvedParents) {
        if (Test-PathIsInside $resolvedConfig $approvedParent) {
            return
        }
    }

    throw (
        "Local configuration outside the repository must be under the current " +
        "user's BarArbolada LocalAppData or .cloudflared directory."
    )
}

function Read-ManagerEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
            continue
        }
        if ($line.StartsWith("export ")) {
            $line = $line.Substring(7).TrimStart()
        }

        $separator = $line.IndexOf("=")
        if ($separator -lt 1) {
            throw "Manager environment file contains an unsupported line."
        }

        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($key -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "Manager environment file contains an invalid key."
        }
        if ($AllowedEnvironmentKeys -notcontains $key) {
            throw "Manager environment file contains an unsupported key: $key"
        }
        if ($values.ContainsKey($key)) {
            throw "Manager environment file contains a duplicate key: $key"
        }

        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or
                ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$key] = $value
    }
    return $values
}

function Assert-ManagerEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot,

        [switch]$RequireGitIgnored,

        [switch]$SkipLocationPolicy
    )

    $resolvedPath = Get-FullExistingPath $Path "Manager API environment file"
    if (-not $SkipLocationPolicy) {
        Assert-LocalOnlyConfigPath `
            -ConfigPath $resolvedPath `
            -ResolvedProjectRoot $ResolvedProjectRoot `
            -RequireGitIgnored:$RequireGitIgnored
    }

    $values = Read-ManagerEnvironment $resolvedPath
    foreach ($requiredKey in @("MANAGER_DATABASE_URL", "MANAGER_API_TOKEN")) {
        if (-not $values.ContainsKey($requiredKey) -or
            [string]::IsNullOrWhiteSpace([string]$values[$requiredKey])) {
            throw "Manager API environment file is missing $requiredKey."
        }
    }

    $databaseUrl = [string]$values["MANAGER_DATABASE_URL"]
    if ($databaseUrl -notmatch "^postgresql(\+psycopg2)?://\S+$") {
        throw "MANAGER_DATABASE_URL must be a PostgreSQL URL with no whitespace."
    }
    if ([string]$values["MANAGER_API_TOKEN"] -match "\s" -or
        ([string]$values["MANAGER_API_TOKEN"]).Length -lt 32) {
        throw "MANAGER_API_TOKEN must be at least 32 non-whitespace characters."
    }

    if ($values.ContainsKey("MANAGER_API_ENABLE_DOCS") -and
        [string]$values["MANAGER_API_ENABLE_DOCS"] -match "^(?i:1|true|yes)$") {
        throw "API documentation must remain disabled in the production service."
    }
    if ($values.ContainsKey("MANAGER_API_ALLOWED_ORIGINS") -and
        -not [string]::IsNullOrWhiteSpace(
            [string]$values["MANAGER_API_ALLOWED_ORIGINS"]
        )) {
        throw "Production browser CORS must remain disabled; use the Sites proxy."
    }
    if ($values.ContainsKey("MANAGER_API_ALLOWED_HOSTS")) {
        $hosts = @(
            ([string]$values["MANAGER_API_ALLOWED_HOSTS"]).Split(",") |
                ForEach-Object { $_.Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        if ($hosts -contains "*") {
            throw "MANAGER_API_ALLOWED_HOSTS must not contain a wildcard."
        }
        if ($hosts -notcontains "127.0.0.1") {
            throw "MANAGER_API_ALLOWED_HOSTS must include 127.0.0.1."
        }
    }
    else {
        throw "Manager API environment file is missing MANAGER_API_ALLOWED_HOSTS."
    }

    if ($values.ContainsKey("MANAGER_API_READINESS_TIMEOUT_SECONDS")) {
        $parsedTimeout = 0.0
        if (-not [double]::TryParse(
            [string]$values["MANAGER_API_READINESS_TIMEOUT_SECONDS"],
            [ref]$parsedTimeout
        ) -or $parsedTimeout -lt 0.05 -or $parsedTimeout -gt 5.0) {
            throw (
                "MANAGER_API_READINESS_TIMEOUT_SECONDS must be between " +
                "0.05 and 5.0."
            )
        }
    }

    return $values
}

function Get-CloudflaredApiHostname {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $contents = Get-Content -LiteralPath $Path
    $joined = $contents -join "`n"
    if ($joined -notmatch "(?m)^\s*tunnel:\s*\S+\s*$") {
        throw "Cloudflared config must name a managed tunnel."
    }
    if ($joined -notmatch "(?m)^\s*credentials-file:\s*\S.+$") {
        throw "Cloudflared config must reference a credentials file."
    }
    if ($joined -match "(?im)^\s*(token|credentials-contents)\s*:") {
        throw "Cloudflared secrets must not be embedded in the YAML config."
    }
    $meaningfulLines = @(
        $contents |
            ForEach-Object { $_.Trim() } |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_) -and
                -not $_.StartsWith("#")
            }
    )
    if ($meaningfulLines.Count -eq 0 -or
        $meaningfulLines[-1] -notmatch "^-\s*service:\s*http_status:404\s*$") {
        throw "Cloudflared config must end with a fail-closed 404 ingress."
    }

    $currentHostname = $null
    $apiHostname = $null
    foreach ($line in $contents) {
        if ($line -match "^\s*-\s*hostname:\s*([A-Za-z0-9.-]+)\s*$") {
            $currentHostname = $matches[1]
            continue
        }
        if ($line -match "^\s*service:\s*http://127\.0\.0\.1:8600/?\s*$") {
            if ([string]::IsNullOrWhiteSpace($currentHostname)) {
                throw "The loopback manager API ingress must have an exact hostname."
            }
            $apiHostname = $currentHostname
        }
    }
    if ([string]::IsNullOrWhiteSpace($apiHostname)) {
        throw "Cloudflared config must route one hostname to 127.0.0.1:8600."
    }

    $credentialsLine = @(
        $contents |
            Where-Object { $_ -match "^\s*credentials-file:\s*(.+?)\s*$" }
    )
    if ($credentialsLine.Count -ne 1) {
        throw "Cloudflared config must contain exactly one credentials-file."
    }
    [void]($credentialsLine[0] -match "^\s*credentials-file:\s*(.+?)\s*$")
    $credentialsPath = $matches[1].Trim().Trim('"').Trim("'")
    if (-not [IO.Path]::IsPathRooted($credentialsPath)) {
        throw "Cloudflared credentials-file must use an absolute local path."
    }
    $resolvedCredentialsPath = Get-FullExistingPath `
        $credentialsPath `
        "Cloudflared credentials file"

    return [pscustomobject]@{
        ApiHostname = $apiHostname
        CredentialsPath = $resolvedCredentialsPath
    }
}

function Assert-CloudflaredConfiguration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot,

        [switch]$RequireGitIgnored,

        [switch]$SkipLocationPolicy
    )

    $resolvedPath = Get-FullExistingPath $Path "Cloudflared config"
    if (-not $SkipLocationPolicy) {
        Assert-LocalOnlyConfigPath `
            -ConfigPath $resolvedPath `
            -ResolvedProjectRoot $ResolvedProjectRoot `
            -RequireGitIgnored:$RequireGitIgnored
    }
    $details = Get-CloudflaredApiHostname $resolvedPath
    Assert-LocalOnlyConfigPath `
        -ConfigPath $details.CredentialsPath `
        -ResolvedProjectRoot $ResolvedProjectRoot `
        -RequireGitIgnored:$RequireGitIgnored
    return $details.ApiHostname
}

function Assert-CloudflaredExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $resolvedPath = Get-FullExistingPath $Path "Cloudflared executable"
    $versionOutput = (& $resolvedPath --version 2>&1) -join " "
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "^cloudflared version ") {
        throw "Cloudflared executable did not pass its version check."
    }
}

function Assert-ApiHostnameAllowed {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$ManagerEnvironment,

        [Parameter(Mandatory = $true)]
        [string]$ApiHostname
    )

    $hosts = @(
        ([string]$ManagerEnvironment["MANAGER_API_ALLOWED_HOSTS"]).Split(",") |
            ForEach-Object { $_.Trim() }
    )
    if ($hosts -notcontains $ApiHostname) {
        throw (
            "MANAGER_API_ALLOWED_HOSTS must include the exact Cloudflare API " +
            "hostname."
        )
    }
}

function Quote-TaskArgument {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    if ($Value.Contains('"')) {
        throw "Managed task paths must not contain double quotes."
    }
    return '"' + $Value + '"'
}

function New-RunnerArguments {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("RunApi", "RunTunnel")]
        [string]$RunnerAction,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedEnvironmentFile,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedCloudflaredExe,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedCloudflaredConfig
    )

    $arguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", (Quote-TaskArgument $ScriptPath),
        "-Action", $RunnerAction,
        "-ProjectRoot", (Quote-TaskArgument $ResolvedProjectRoot)
    )
    if ($RunnerAction -eq "RunApi") {
        $arguments += @(
            "-EnvironmentFile",
            (Quote-TaskArgument $ResolvedEnvironmentFile)
        )
    }
    else {
        $arguments += @(
            "-CloudflaredExe",
            (Quote-TaskArgument $ResolvedCloudflaredExe),
            "-CloudflaredConfig",
            (Quote-TaskArgument $ResolvedCloudflaredConfig)
        )
    }
    return $arguments -join " "
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Get-ManagedTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    return Get-ScheduledTask `
        -TaskName $Name `
        -TaskPath $ManagedTaskPath `
        -ErrorAction SilentlyContinue
}

function Assert-TaskOwnedByThisScript {
    param(
        [Parameter(Mandatory = $true)]
        $Task,

        [Parameter(Mandatory = $true)]
        [ValidateSet("RunApi", "RunTunnel")]
        [string]$RunnerAction
    )

    $owned = $false
    foreach ($taskAction in @($Task.Actions)) {
        if ([string]$taskAction.Arguments -like "*$ScriptPath*" -and
            [string]$taskAction.Arguments -like "*-Action $RunnerAction*") {
            $owned = $true
        }
    }
    if (-not $owned) {
        throw "Refusing to replace or remove a same-named task not managed by this script."
    }
}

function New-ManagedTaskDefinition {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("RunApi", "RunTunnel")]
        [string]$RunnerAction,

        [Parameter(Mandatory = $true)]
        [string]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot,

        [Parameter(Mandatory = $true)]
        [ValidateSet("AtLogOn", "AtStartup")]
        [string]$Mode
    )

    $powerShellExe = Join-Path `
        $env:SystemRoot `
        "System32\WindowsPowerShell\v1.0\powershell.exe"
    [void](Get-FullExistingPath $powerShellExe "Windows PowerShell")
    $taskAction = New-ScheduledTaskAction `
        -Execute $powerShellExe `
        -Argument $Arguments `
        -WorkingDirectory $ResolvedProjectRoot

    if ($Mode -eq "AtStartup") {
        if (-not (Test-IsAdministrator)) {
            throw "AtStartup installation requires an elevated PowerShell window."
        }
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal `
            -UserId "SYSTEM" `
            -LogonType ServiceAccount `
            -RunLevel Highest
    }
    else {
        $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $principal = New-ScheduledTaskPrincipal `
            -UserId $currentUser `
            -LogonType Interactive `
            -RunLevel Limited
    }

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable

    return New-ScheduledTask `
        -Action $taskAction `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description (
            "Bar Arbolada manager $RunnerAction; managed by " +
            "scripts\install_manager_services.ps1; no credentials in task."
        )
}

function Restore-ManagedTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [AllowNull()]
        [string]$PreviousXml
    )

    if ([string]::IsNullOrWhiteSpace($PreviousXml)) {
        $current = Get-ManagedTask $Name
        if ($null -ne $current) {
            Unregister-ScheduledTask `
                -TaskName $Name `
                -TaskPath $ManagedTaskPath `
                -Confirm:$false
        }
        return
    }

    Register-ScheduledTask `
        -TaskName $Name `
        -TaskPath $ManagedTaskPath `
        -Xml $PreviousXml `
        -Force | Out-Null
}

function Get-HttpStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    try {
        $result = Invoke-WebRequest `
            -Uri $Uri `
            -Method Get `
            -UseBasicParsing `
            -TimeoutSec 3
        return [int]$result.StatusCode
    }
    catch {
        if ($null -ne $_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        return 0
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path $PSScriptRoot -Parent
}
$resolvedProjectRoot = Get-FullExistingPath $ProjectRoot "Project root"
if ([string]::IsNullOrWhiteSpace($EnvironmentFile)) {
    $EnvironmentFile = Join-Path $resolvedProjectRoot ".env.manager-api"
}
if ([string]::IsNullOrWhiteSpace($CloudflaredExe)) {
    $CloudflaredExe = Join-Path (
        Join-Path $env:LOCALAPPDATA "BarArbolada\cloudflared"
    ) "cloudflared.exe"
}
if ([string]::IsNullOrWhiteSpace($CloudflaredConfig)) {
    $CloudflaredConfig = Join-Path (
        Join-Path $env:LOCALAPPDATA "BarArbolada\cloudflared"
    ) "config.yml"
}

switch ($Action) {
    "RunApi" {
        $pythonExe = Join-Path $resolvedProjectRoot ".venv\Scripts\python.exe"
        [void](Get-FullExistingPath $pythonExe "Python virtual environment")
        $managerEnvironment = Assert-ManagerEnvironment `
            -Path $EnvironmentFile `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -SkipLocationPolicy

        foreach ($key in $AllowedEnvironmentKeys) {
            if ($managerEnvironment.ContainsKey($key)) {
                [Environment]::SetEnvironmentVariable(
                    $key,
                    [string]$managerEnvironment[$key],
                    "Process"
                )
            }
        }
        [Environment]::SetEnvironmentVariable(
            "DATABASE_URL",
            [string]$managerEnvironment["MANAGER_DATABASE_URL"],
            "Process"
        )
        [Environment]::SetEnvironmentVariable(
            "PGAPPNAME",
            "bar-arbolada-manager-api",
            "Process"
        )
        [Environment]::SetEnvironmentVariable("PGCONNECT_TIMEOUT", "2", "Process")
        [Environment]::SetEnvironmentVariable(
            "PGOPTIONS",
            (
                "-c default_transaction_read_only=on " +
                "-c statement_timeout=15000 " +
                "-c lock_timeout=2000 " +
                "-c idle_in_transaction_session_timeout=15000"
            ),
            "Process"
        )

        Push-Location $resolvedProjectRoot
        try {
            & $pythonExe -m uvicorn "src.api.app:app" `
                --host "127.0.0.1" `
                --port 8600 `
                --workers 1 `
                --limit-concurrency 16 `
                --backlog 32 `
                --timeout-graceful-shutdown 10 `
                --proxy-headers `
                --forwarded-allow-ips "127.0.0.1" `
                --no-access-log `
                --no-server-header `
                --no-date-header
            exit $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }

    "RunTunnel" {
        Assert-CloudflaredExecutable $CloudflaredExe
        [void](Assert-CloudflaredConfiguration `
            -Path $CloudflaredConfig `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -SkipLocationPolicy)

        & $CloudflaredExe `
            --config $CloudflaredConfig `
            tunnel `
            --no-autoupdate `
            run
        exit $LASTEXITCODE
    }

    "Validate" {
        $managerEnvironment = Assert-ManagerEnvironment `
            -Path $EnvironmentFile `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -RequireGitIgnored
        Assert-CloudflaredExecutable $CloudflaredExe
        $apiHostname = Assert-CloudflaredConfiguration `
            -Path $CloudflaredConfig `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -RequireGitIgnored
        Assert-ApiHostnameAllowed $managerEnvironment $apiHostname
        [void](Get-FullExistingPath `
            (Join-Path $resolvedProjectRoot ".venv\Scripts\python.exe") `
            "Python virtual environment")
        Write-Output "Manager service configuration is valid; no secrets were displayed."
    }

    "Install" {
        $managerEnvironment = Assert-ManagerEnvironment `
            -Path $EnvironmentFile `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -RequireGitIgnored
        Assert-CloudflaredExecutable $CloudflaredExe
        $apiHostname = Assert-CloudflaredConfiguration `
            -Path $CloudflaredConfig `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -RequireGitIgnored
        Assert-ApiHostnameAllowed $managerEnvironment $apiHostname

        $resolvedEnvironmentFile = Get-FullExistingPath `
            $EnvironmentFile `
            "Manager API environment file"
        $resolvedCloudflaredExe = Get-FullExistingPath `
            $CloudflaredExe `
            "Cloudflared executable"
        $resolvedCloudflaredConfig = Get-FullExistingPath `
            $CloudflaredConfig `
            "Cloudflared config"
        [void](Get-FullExistingPath `
            (Join-Path $resolvedProjectRoot ".venv\Scripts\python.exe") `
            "Python virtual environment")

        $existingApi = Get-ManagedTask $ApiTaskName
        $existingTunnel = Get-ManagedTask $TunnelTaskName
        if ($null -ne $existingApi) {
            Assert-TaskOwnedByThisScript $existingApi "RunApi"
        }
        if ($null -ne $existingTunnel) {
            Assert-TaskOwnedByThisScript $existingTunnel "RunTunnel"
        }

        $previousApiXml = if ($null -ne $existingApi) {
            Export-ScheduledTask `
                -TaskName $ApiTaskName `
                -TaskPath $ManagedTaskPath
        }
        else {
            $null
        }
        $previousTunnelXml = if ($null -ne $existingTunnel) {
            Export-ScheduledTask `
                -TaskName $TunnelTaskName `
                -TaskPath $ManagedTaskPath
        }
        else {
            $null
        }

        $apiArguments = New-RunnerArguments `
            -RunnerAction "RunApi" `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -ResolvedEnvironmentFile $resolvedEnvironmentFile `
            -ResolvedCloudflaredExe $resolvedCloudflaredExe `
            -ResolvedCloudflaredConfig $resolvedCloudflaredConfig
        $tunnelArguments = New-RunnerArguments `
            -RunnerAction "RunTunnel" `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -ResolvedEnvironmentFile $resolvedEnvironmentFile `
            -ResolvedCloudflaredExe $resolvedCloudflaredExe `
            -ResolvedCloudflaredConfig $resolvedCloudflaredConfig
        $apiTask = New-ManagedTaskDefinition `
            -RunnerAction "RunApi" `
            -Arguments $apiArguments `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -Mode $StartupMode
        $tunnelTask = New-ManagedTaskDefinition `
            -RunnerAction "RunTunnel" `
            -Arguments $tunnelArguments `
            -ResolvedProjectRoot $resolvedProjectRoot `
            -Mode $StartupMode

        if ($PSCmdlet.ShouldProcess(
            "$ManagedTaskPath$ApiTaskName and $ManagedTaskPath$TunnelTaskName",
            "Install or update managed startup tasks"
        )) {
            try {
                Register-ScheduledTask `
                    -TaskName $ApiTaskName `
                    -TaskPath $ManagedTaskPath `
                    -InputObject $apiTask `
                    -Force | Out-Null
                Register-ScheduledTask `
                    -TaskName $TunnelTaskName `
                    -TaskPath $ManagedTaskPath `
                    -InputObject $tunnelTask `
                    -Force | Out-Null
            }
            catch {
                Restore-ManagedTask $ApiTaskName $previousApiXml
                Restore-ManagedTask $TunnelTaskName $previousTunnelXml
                throw
            }

            if ($StartNow) {
                Start-ScheduledTask `
                    -TaskName $ApiTaskName `
                    -TaskPath $ManagedTaskPath
                Start-ScheduledTask `
                    -TaskName $TunnelTaskName `
                    -TaskPath $ManagedTaskPath
            }
        }
        Write-Output (
            "Managed startup tasks are configured with one-minute " +
            "restart-on-failure and no embedded credentials."
        )
    }

    "Uninstall" {
        foreach ($entry in @(
            @($ApiTaskName, "RunApi"),
            @($TunnelTaskName, "RunTunnel")
        )) {
            $task = Get-ManagedTask $entry[0]
            if ($null -eq $task) {
                continue
            }
            Assert-TaskOwnedByThisScript $task $entry[1]
            if ($PSCmdlet.ShouldProcess(
                "$ManagedTaskPath$($entry[0])",
                "Unregister managed startup task"
            )) {
                Unregister-ScheduledTask `
                    -TaskName $entry[0] `
                    -TaskPath $ManagedTaskPath `
                    -Confirm:$false
            }
        }
        Write-Output "Managed tasks removed; local configuration files were retained."
    }

    "Status" {
        $apiTask = Get-ManagedTask $ApiTaskName
        $tunnelTask = Get-ManagedTask $TunnelTaskName
        $listeners = @(
            Get-NetTCPConnection `
                -State Listen `
                -LocalPort 8600 `
                -ErrorAction SilentlyContinue
        )
        $unsafeListener = @(
            $listeners |
                Where-Object { $_.LocalAddress -ne "127.0.0.1" }
        ).Count -gt 0
        $loopbackListener = @(
            $listeners |
                Where-Object { $_.LocalAddress -eq "127.0.0.1" }
        ).Count -gt 0

        [pscustomobject]@{
            ApiTaskState = if ($null -eq $apiTask) {
                "NotInstalled"
            }
            else {
                [string]$apiTask.State
            }
            TunnelTaskState = if ($null -eq $tunnelTask) {
                "NotInstalled"
            }
            else {
                [string]$tunnelTask.State
            }
            ApiBinding = if ($unsafeListener) {
                "UnsafeNonLoopback"
            }
            elseif ($loopbackListener) {
                "LoopbackOnly"
            }
            else {
                "NotListening"
            }
            LivenessHttpStatus = Get-HttpStatus "http://127.0.0.1:8600/health"
            ReadinessHttpStatus = Get-HttpStatus "http://127.0.0.1:8600/ready"
        }
    }
}
