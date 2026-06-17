param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [int]$Port = 8501
)

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe. Create the virtualenv first."
}

Push-Location $ProjectRoot
try {
    & $pythonExe -m streamlit run "dashboards/app.py" `
        --server.address "127.0.0.1" `
        --server.port $Port
}
finally {
    Pop-Location
}
