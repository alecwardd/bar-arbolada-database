param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
)

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $ProjectRoot "reports\task-scheduler"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "import_from_email-$timestamp.log"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe. Create the virtualenv first."
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:PYTHONIOENCODING = "utf-8"

Push-Location $ProjectRoot
try {
    & $pythonExe "scripts/import_from_email.py" --source imap *>&1 | Tee-Object -FilePath $logPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
