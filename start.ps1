# ICEFLOW: start the whole prototype with one command (Windows / PowerShell).
#
#   .\start.ps1              install if needed, then run backend and bridge console
#   .\start.ps1 -SkipInstall skip dependency installation
#   .\start.ps1 -Check       run the verification checks instead of serving
#
# Ctrl-C stops both servers.

param(
    [switch]$SkipInstall,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Say($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  ICEFLOW  |  SIH 2026 PS-26059  |  MoES / NCPOR" -ForegroundColor White
Write-Host "  ---------------------------------------------------" -ForegroundColor DarkGray

# --- ensure installed tools are in PATH ---------------------------------------------
$toolPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python311",
    "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
    "$env:LOCALAPPDATA\Programs\nodejs"
)
foreach ($p in $toolPaths) {
    if (Test-Path $p) {
        $env:Path = "$p;$env:Path"
    }
}

$npmExe = if (Get-Command "npm.cmd" -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }

# --- prerequisites -------------------------------------------------------------------
foreach ($tool in @('python', $npmExe)) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "  Missing prerequisite: $tool" -ForegroundColor Red
        Write-Host "  Install Python 3.11+ and Node 18+, then run this again."
        exit 1
    }
}

# --- dependencies --------------------------------------------------------------------
if (-not $SkipInstall) {
    Say "Installing Python dependencies..."
    python -m pip install -q -r requirements.txt
    if (-not (Test-Path "frontend/node_modules")) {
        Say "Installing frontend dependencies (first run only, takes a minute)..."
        Push-Location frontend; & $npmExe install --silent; Pop-Location
    }
}

# --- verification mode ---------------------------------------------------------------
if ($Check) {
    Say "Running the test suite..."
    python -m pytest tests/ -q
    Say "Running the command-line demonstration..."
    python -m src.cli --quick
    Write-Host ""
    Say "Checks complete. See the 'How to check the prototype is actually working' section of README.md."
    exit 0
}

# --- serve ---------------------------------------------------------------------------
Say "Starting the API on http://127.0.0.1:8000  (docs at /docs)"
$backend = Start-Process -PassThru -NoNewWindow -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", "8000"

# Wait for the API to answer before starting the console, so the first screen is never empty.
Say "Waiting for the API to warm its caches..."
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2 -UseBasicParsing | Out-Null
        $ready = $true
        break
    } catch { }
}
if (-not $ready) {
    Warn "The API did not become ready in 60 seconds. Check the output above."
} else {
    Say "API is up."
}

Say "Starting the bridge console on http://localhost:5173"
Write-Host ""
Write-Host "  Open  http://localhost:5173  in your browser." -ForegroundColor Green
Write-Host "  Press Ctrl-C here to stop both servers." -ForegroundColor DarkGray
Write-Host ""

try {
    Push-Location frontend
    & $npmExe run dev
} finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) {
        Say "Stopping the API..."
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
