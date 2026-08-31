@echo off
REM ============================================================================
REM Code Sonar — one-command startup (Windows).
REM
REM Launches the FastAPI backend and Vite dev server in two separate windows.
REM Ports are selected dynamically so stale or unrelated listeners do not block
REM startup. Uvicorn reload mode is intentionally disabled here to avoid leaving
REM Windows child/reloader process trees behind after the launcher is closed.
REM ============================================================================

setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "REPO_ROOT=%CD%"
popd

set "BACKEND_PORT="
set "FRONTEND_PORT="

REM Pick the first truly free backend port in a bounded local-dev range.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$used = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty LocalPort); $port = 8000..8099 ^| Where-Object { $used -notcontains $_ } ^| Select-Object -First 1; if ($null -eq $port) { exit 1 }; Write-Output $port"`) do set "BACKEND_PORT=%%P"
if not defined BACKEND_PORT (
    echo [ERROR] No free backend port found in range 8000-8099.
    exit /b 1
)

REM Pick the first truly free frontend port in a bounded local-dev range.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$used = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty LocalPort); $port = 3000..3099 ^| Where-Object { $used -notcontains $_ } ^| Select-Object -First 1; if ($null -eq $port) { exit 1 }; Write-Output $port"`) do set "FRONTEND_PORT=%%P"
if not defined FRONTEND_PORT (
    echo [ERROR] No free frontend port found in range 3000-3099.
    exit /b 1
)

echo.
echo === Code Sonar startup ===============================================
echo Repo root:  %REPO_ROOT%
echo Backend:    http://127.0.0.1:%BACKEND_PORT%
echo Frontend:   http://localhost:%FRONTEND_PORT%
echo ======================================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not on PATH. Install Python 3.11+ and retry.
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not on PATH. Install Node.js 20+ and retry.
    exit /b 1
)

set "VENV=%REPO_ROOT%\backend\.venv"
if not exist "%VENV%\Scripts\python.exe" (
    echo [INFO] Creating Python venv at %VENV% ...
    pushd "%REPO_ROOT%\backend"
    python -m venv .venv || (popd & echo [ERROR] venv creation failed & exit /b 1)
    popd
)

REM A venv can survive across pulls while pyproject.toml gains dependencies.
REM Verify required runtime imports and resync the editable installation when
REM anything is missing instead of launching a broken server.
"%VENV%\Scripts\python.exe" -c "import fastapi, uvicorn, sklearn, jwt" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Backend environment is stale or incomplete; syncing dependencies ...
    pushd "%REPO_ROOT%\backend"
    "%VENV%\Scripts\python.exe" -m pip install -e ".[dev]" || (popd & echo [ERROR] backend dependency sync failed & exit /b 1)
    popd
)

REM Final import gate.
"%VENV%\Scripts\python.exe" -c "import fastapi, uvicorn, sklearn, jwt" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Backend runtime dependencies are still incomplete.
    echo         Rebuild backend\.venv with a supported Python installation.
    exit /b 1
)

if not exist "%REPO_ROOT%\frontend\node_modules" (
    echo [INFO] Installing frontend dependencies ...
    pushd "%REPO_ROOT%\frontend"
    call npm install || (popd & echo [ERROR] frontend install failed & exit /b 1)
    popd
)

echo [INFO] Launching backend on port %BACKEND_PORT% ...
start "Code Sonar - Backend" cmd /k ^
    "cd /d %REPO_ROOT%\backend && ^"
    "%VENV%\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %BACKEND_PORT%

set /a HEALTH_TRIES=0
:wait_for_backend
set /a HEALTH_TRIES+=1
timeout /t 1 /nobreak >nul
curl -fsS http://127.0.0.1:%BACKEND_PORT%/health >nul 2>&1
if errorlevel 1 (
    if %HEALTH_TRIES% LSS 30 goto wait_for_backend
    echo [ERROR] Backend did not respond on /health within 30s.
    echo         Frontend was not launched because the API is unhealthy.
    exit /b 1
)

echo [OK] Backend healthy on http://127.0.0.1:%BACKEND_PORT%.

REM Pass the selected backend URL into Vite so /api follows the actual backend.
echo [INFO] Launching frontend on http://localhost:%FRONTEND_PORT% ...
start "Code Sonar - Frontend" cmd /k ^
    "cd /d %REPO_ROOT%\frontend && ^"
    "set VITE_API_TARGET=http://127.0.0.1:%BACKEND_PORT%&& npm run dev -- --port %FRONTEND_PORT%"

echo.
echo === Code Sonar is running ============================================
echo.
echo   Backend:  http://127.0.0.1:%BACKEND_PORT%
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo.
echo Both servers run in their own windows. Close those windows to stop,
echo or run scripts\stop.bat.
echo.
echo Tip: open the frontend URL, connect a project or enter a repo path,
echo      and run a deterministic scan.
echo ======================================================================
echo.
endlocal
exit /b 0
