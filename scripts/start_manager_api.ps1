param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [int]$Port = 8600,
    [switch]$AllowSharedDatabaseCredential
)

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe. Create the virtualenv first."
}

if (-not [string]::IsNullOrWhiteSpace($env:MANAGER_DATABASE_URL)) {
    $env:DATABASE_URL = $env:MANAGER_DATABASE_URL
}
elseif (-not $AllowSharedDatabaseCredential) {
    throw "MANAGER_DATABASE_URL is required. Use a dedicated PostgreSQL read-only role."
}

Push-Location $ProjectRoot
try {
    & $pythonExe -m uvicorn "src.api.app:app" `
        --host "127.0.0.1" `
        --port $Port
}
finally {
    Pop-Location
}
