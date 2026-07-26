param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
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

$adminUrlSecret = Read-Host `
    "PostgreSQL administrator URL for the local bar_arbolada database" `
    -AsSecureString
$managerPasswordSecret = Read-Host `
    "New password for the dedicated bar_manager_read role (32+ characters)" `
    -AsSecureString

try {
    $env:MANAGER_DB_ADMIN_URL = ConvertFrom-TaskSecureString $adminUrlSecret
    $env:MANAGER_DATABASE_PASSWORD = ConvertFrom-TaskSecureString $managerPasswordSecret

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
}
finally {
    Remove-Item Env:\MANAGER_DB_ADMIN_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\MANAGER_DATABASE_PASSWORD -ErrorAction SilentlyContinue
}
