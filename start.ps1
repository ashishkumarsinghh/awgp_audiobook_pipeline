<#
==============================================================================
AWGP Audiobook Production Pipeline - Windows PowerShell Launcher
Starts both the FastAPI Backend (:8000) and the Vite Frontend (:5173).
Runs natively on Windows without requiring WSL.
==============================================================================
#>

[CmdletBinding()]
param(
    [switch]$UseWSL
)

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) {
    $ProjectRoot = Get-Location
}
Set-Location $ProjectRoot

# If explicitly requested to run via WSL
if ($UseWSL) {
    Write-Host "Delegating execution to WSL..." -ForegroundColor Yellow
    wsl bash -c "cd `"$ProjectRoot`" && ./start.sh"
    exit $LASTEXITCODE
}

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "   AWGP Audiobook Production Pipeline Launcher        " -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Cyan

# 1. Clean up ports 8000 and 5173
Write-Host "[1/4] Checking and freeing ports 8000 and 5173..." -ForegroundColor Yellow
$ports = @(8000, 5173)
foreach ($port in $ports) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            if ($conn.OwningProcess -and $conn.OwningProcess -ne 0) {
                Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
}

# 2. Locate Python / Virtual Environment
Write-Host "[2/4] Detecting Python virtual environment..." -ForegroundColor Yellow
$PythonExe = $null

$candidates = @(
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot "..\venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot "venv\bin\python"),
    (Join-Path $ProjectRoot ".venv\bin\python")
)

foreach ($c in $candidates) {
    if (Test-Path $c) {
        $PythonExe = $c
        break
    }
}

if (-not $PythonExe) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonExe = "python"
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $PythonExe = "py"
    } else {
        Write-Host "Error: Python was not found in PATH or virtual environment!" -ForegroundColor Red
        Write-Host "Please install Python or create a venv: python -m venv venv" -ForegroundColor Red
        exit 1
    }
}
Write-Host "      Using Python: $PythonExe" -ForegroundColor Gray

# 3. Locate npm
$npmCmd = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
if (-not (Get-Command $npmCmd -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Node.js / npm is not installed or not found in PATH!" -ForegroundColor Red
    exit 1
}

# 4. Start FastAPI Backend
Write-Host "[3/4] Starting FastAPI Backend on http://localhost:8000..." -ForegroundColor Yellow
$backendArgs = "-m uvicorn api:app --reload --host 0.0.0.0 --port 8000"
$backendProcess = Start-Process -FilePath $PythonExe -ArgumentList $backendArgs -WorkingDirectory $ProjectRoot -PassThru

Start-Sleep -Seconds 2

# 5. Start Vite Frontend
Write-Host "[4/4] Starting Vite Frontend on http://localhost:5173..." -ForegroundColor Yellow
$frontendDir = Join-Path $ProjectRoot "frontend"
$frontendProcess = Start-Process -FilePath $npmCmd -ArgumentList "run dev -- --host 0.0.0.0" -WorkingDirectory $frontendDir -PassThru

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "  [+] Backend running at:  http://localhost:8000" -ForegroundColor Green
Write-Host "  [+] API Docs running at: http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  [+] Frontend running at: http://localhost:5173" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host "Press [Ctrl+C] to stop all services." -ForegroundColor Yellow
Write-Host ""

try {
    while (-not $backendProcess.HasExited -and -not $frontendProcess.HasExited) {
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host ""
    Write-Host "Stopping all services gracefully..." -ForegroundColor Yellow
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($frontendProcess -and -not $frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($port in $ports) {
        try {
            $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
            foreach ($conn in $conns) {
                if ($conn.OwningProcess -and $conn.OwningProcess -ne 0) {
                    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {}
    }
    Write-Host "All services stopped cleanly. Goodbye!" -ForegroundColor Green
}
