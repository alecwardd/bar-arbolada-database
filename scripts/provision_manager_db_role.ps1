param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),

    [string]$OutputEnvironmentFile = (
        Join-Path $env:LOCALAPPDATA "BarArbolada\manager-api.env"
    ),

    [string]$ApiHostname = "",

    [ValidateSet("Password", "Url")]
    [string]$AdministratorInput = "Password",

    [string]$AdministratorHost = "localhost",

    [ValidateRange(1, 65535)]
    [int]$AdministratorPort = 5432,

    [string]$AdministratorUser = "postgres",

    [string]$AdministratorDatabase = "bar_arbolada"
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

$adminUrlSecret = $null
$administratorPasswordSecret = $null
$adminUrl = $null

if ($AdministratorInput -eq "Url") {
    $adminUrlSecret = Read-Host `
        "PostgreSQL administrator URL for the local bar_arbolada database" `
        -AsSecureString
    $adminUrl = ConvertFrom-TaskSecureString $adminUrlSecret
}
else {
    if ($AdministratorHost -notmatch "^[A-Za-z0-9.-]+$") {
        throw "AdministratorHost must be one local hostname or IPv4 address."
    }
    foreach ($identifier in @(
        $AdministratorUser,
        $AdministratorDatabase
    )) {
        if ($identifier -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") {
            throw "PostgreSQL user and database names must be simple identifiers."
        }
    }

    $administratorPasswordSecret = Read-Host (
        "Password for PostgreSQL administrator " +
        "$AdministratorUser@$AdministratorHost`:$AdministratorPort"
    ) -AsSecureString
    $administratorPassword = ConvertFrom-TaskSecureString (
        $administratorPasswordSecret
    )
    try {
        $encodedUser = [Uri]::EscapeDataString($AdministratorUser)
        $encodedPassword = [Uri]::EscapeDataString($administratorPassword)
        $encodedDatabase = [Uri]::EscapeDataString($AdministratorDatabase)
        $adminUrl = (
            "postgresql://${encodedUser}:${encodedPassword}@" +
            "$AdministratorHost`:$AdministratorPort/$encodedDatabase"
        )
    }
    finally {
        $administratorPassword = $null
        $encodedPassword = $null
    }
}

try {
    $env:MANAGER_DB_ADMIN_URL = $adminUrl
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
    $adminUrl = $null
    if ($null -ne $adminUrlSecret) {
        $adminUrlSecret.Dispose()
    }
    if ($null -ne $administratorPasswordSecret) {
        $administratorPasswordSecret.Dispose()
    }
    Remove-Item Env:\MANAGER_DB_ADMIN_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_DATABASE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_ENV_OUTPUT_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_API_HOSTNAME -ErrorAction SilentlyContinue
}
