[CmdletBinding()]
param(
    [string]$WorkerRoot = "",

    [string]$OutputFile = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-RelaySecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).
        TrimEnd("=").
        Replace("+", "-").
        Replace("/", "_")
}

function Read-RelaySecrets {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $separator = $line.IndexOf("=")
        if ($separator -lt 1) {
            throw "Relay environment file contains an unsupported line."
        }
        $key = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($key -notin @("RELAY_CLIENT_ID", "RELAY_CLIENT_SECRET")) {
            throw "Relay environment file contains an unsupported key."
        }
        if ($values.ContainsKey($key)) {
            throw "Relay environment file contains a duplicate key."
        }
        if ($value.Length -lt 32 -or $value -match "\s") {
            throw "Relay credentials must be at least 32 non-space characters."
        }
        $values[$key] = $value
    }

    foreach ($required in @("RELAY_CLIENT_ID", "RELAY_CLIENT_SECRET")) {
        if (-not $values.ContainsKey($required)) {
            throw "Relay environment file is missing $required."
        }
    }
    return $values
}

function Set-SecretFileAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe `
        $Path `
        /inheritance:r `
        /grant:r `
        "${currentUser}:(R,W)" `
        "SYSTEM:(R)" `
        "BUILTIN\Administrators:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Relay credential file ACL restriction failed."
    }
}

if ([string]::IsNullOrWhiteSpace($WorkerRoot)) {
    $WorkerRoot = Join-Path (
        Split-Path $PSScriptRoot -Parent
    ) "cloudflare\manager-api-relay"
}
$resolvedWorkerRoot = (Resolve-Path -LiteralPath $WorkerRoot).Path
$wranglerConfig = Join-Path $resolvedWorkerRoot "wrangler.jsonc"
if (-not (Test-Path -LiteralPath $wranglerConfig -PathType Leaf)) {
    throw "Worker configuration is missing."
}

$localRoot = Join-Path $env:LOCALAPPDATA "BarArbolada"
if ([string]::IsNullOrWhiteSpace($OutputFile)) {
    $OutputFile = Join-Path $localRoot "cloudflare-relay.env"
}
$fullOutputPath = [IO.Path]::GetFullPath($OutputFile)
$localPrefix = [IO.Path]::GetFullPath($localRoot).TrimEnd("\", "/") +
    [IO.Path]::DirectorySeparatorChar
if (-not $fullOutputPath.StartsWith(
    $localPrefix,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Relay credentials must remain under the local BarArbolada directory."
}

if (-not (Test-Path -LiteralPath $fullOutputPath -PathType Leaf)) {
    [void](New-Item -ItemType Directory -Path (
        Split-Path $fullOutputPath -Parent
    ) -Force)
    $temporaryPath = "$fullOutputPath.$PID.tmp"
    try {
        $contents = @(
            "RELAY_CLIENT_ID=$(New-RelaySecret)"
            "RELAY_CLIENT_SECRET=$(New-RelaySecret)"
            ""
        ) -join "`r`n"
        [IO.File]::WriteAllText(
            $temporaryPath,
            $contents,
            [Text.UTF8Encoding]::new($false)
        )
        Set-SecretFileAcl $temporaryPath
        Move-Item -LiteralPath $temporaryPath -Destination $fullOutputPath
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

Set-SecretFileAcl $fullOutputPath
$secrets = Read-RelaySecrets $fullOutputPath

Push-Location $resolvedWorkerRoot
try {
    foreach ($secretName in @("RELAY_CLIENT_ID", "RELAY_CLIENT_SECRET")) {
        $secretValue = [string]$secrets[$secretName]
        $secretValue | & npx --yes wrangler@latest secret put $secretName
        if ($LASTEXITCODE -ne 0) {
            throw "Wrangler failed to set $secretName."
        }
    }
}
finally {
    Pop-Location
    $secrets.Clear()
    $secretValue = $null
}

Write-Output (
    "Cloudflare relay credentials are stored locally with restricted access " +
    "and applied to the Worker; no secret values were displayed."
)
