# Secret Wards — One-click Local Launcher (Windows PowerShell)
# Run from demo-app/: .\start.ps1

$ErrorActionPreference = "Stop"
$PORT = if ($env:PORT) { [int]$env:PORT } else { 8081 }

# Auto-detect Python 3.10+
$PYTHON = (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
if (-not $PYTHON) {
    $PYTHON = (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
}
if (-not $PYTHON) {
    Write-Error "Python 3.10+ was not found on PATH. Install Python and try again."
    exit 1
}

Write-Host ""
Write-Host "  Secret Wards — Offline Privacy Firewall Launcher" -ForegroundColor Cyan
Write-Host "  ================================================" -ForegroundColor Cyan
Write-Host "  Python: $PYTHON" -ForegroundColor DarkGray
Write-Host ""

# 1. Build frontend if dist/ is missing
$distDir = Join-Path $PSScriptRoot "dist"
if (-not (Test-Path $distDir)) {
    Write-Host "  [1/2] Installing deps (if needed) & building React frontend..." -ForegroundColor Yellow
    if (-not (Test-Path (Join-Path $PSScriptRoot "node_modules"))) {
        npm --prefix $PSScriptRoot ci
    }
    npm --prefix $PSScriptRoot run build
    Write-Host "  [1/2] Build complete." -ForegroundColor Green
} else {
    Write-Host "  [1/2] dist/ found — skipping rebuild. (Run 'npm run build' to refresh)" -ForegroundColor DarkGray
}

# 2. Report a busy port without interrupting an existing service.
$existing = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Error "Port $PORT is in use. Set the PORT environment variable to choose a different port."
}

# 3. Start local HTTP adapter
Write-Host ""
Write-Host "  [2/2] Starting local offline adapter on http://127.0.0.1:$PORT ..." -ForegroundColor Yellow
Write-Host "  ==> Open: http://127.0.0.1:$PORT" -ForegroundColor Green
Write-Host "  ==> Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

Set-Location (Join-Path $PSScriptRoot "server")
& $PYTHON -B server.py
