param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),

    [string]$OutputEnvironmentFile = (
        Join-Path $env:LOCALAPPDATA "BarArbolada\manager-api.env"
    ),

    [string]$ApiHostname = ""
)

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python executable not found at $pythonExe. Create the virtualenv first."
}

function ConvertFrom-TaskSecureString {
    param([Security.SecureString]$Value)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-TaskSecret {
    param([int]$ByteCount = 48)

    $bytes = New-Object byte[] $ByteCount
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").
        Replace("+", "-").Replace("/", "_")
}

$adminUrlSecret = Read-Host `
    "PostgreSQL administrator URL for the local bar_arbolada database" `
    -AsSecureString

try {
    $env:MANAGER_DB_ADMIN_URL = ConvertFrom-TaskSecureString $adminUrlSecret
    $env:MANAGER_DATABASE_PASSWORD = New-TaskSecret
    $env:MANAGER_API_TOKEN = New-TaskSecret
    $env:MANAGER_ENV_OUTPUT_PATH = [IO.Path]::GetFullPath(
        $OutputEnvironmentFile
    )
    $env:MANAGER_API_HOSTNAME = $ApiHostname

    Push-Location $ProjectRoot
    try {
        & $pythonExe -m "scripts.provision_manager_db_role"
        if ($LASTEXITCODE -ne 0) {
            throw "Manager database role provisioning failed closed."
        }
    }
    finally {
        Pop-Location
    }

    $resolvedEnvironmentFile = (Resolve-Path -LiteralPath (
        $env:MANAGER_ENV_OUTPUT_PATH
    )).Path
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe `
        $resolvedEnvironmentFile `
        /inheritance:r `
        /grant:r `
        "${currentIdentity}:(R,W)" `
        "SYSTEM:(R)" `
        "BUILTIN\Administrators:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Manager environment file ACL restriction failed."
    }
    Write-Output (
        "Manager database role and local API environment are ready; " +
        "no credentials were displayed."
    )
}
finally {
    Remove-Item Env:\MANAGER_DB_ADMIN_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_DATABASE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_ENV_OUTPUT_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_API_HOSTNAME -ErrorAction SilentlyContinue
}
