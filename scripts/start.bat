@echo off
REM ============================================================================
REM Code Sonar — one-command startup (Windows).
REM
REM Launches the FastAPI backend and Vite dev server in two separate
REM windows so they can be stopped independently.
REM ============================================================================

setlocal enableextensions enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "REPO_ROOT=%CD%"
popd

set "FRONTEND_PORT=3000"
set "BACKEND_PORT=8000"

REM Pick a backend port using PowerShell's TCP listener view. This avoids
REM findstr/netstat false positives and only treats a true LISTEN socket as busy.
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Port 8000 in use, falling back to 8765.
    set "BACKEND_PORT=8765"
)

REM Refuse to start if both supported backend ports are occupied.
if "%BACKEND_PORT%"=="8765" (
    powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !ERRORLEVEL! == 0 (
        echo [ERROR] Both backend ports 8000 and 8765 are already in use.
        echo         Stop the existing service or choose a different environment.
        exit /b 1
    )
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
if not exist "%VENV%\Scripts\uvicorn.exe" (
    echo [INFO] Installing backend dependencies ...
    pushd "%REPO_ROOT%\backend"
    "%VENV%\Scripts\python.exe" -m pip install -e ".[dev]" || (popd & echo [ERROR] backend install failed & exit /b 1)
    popd
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
    "%VENV%\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload

set /a HEALTH_TRIES=0
:wait_for_backend
set /a HEALTH_TRIES+=1
timeout /t 1 /nobreak >nul
curl -fsS http://127.0.0.1:%BACKEND_PORT%/health >nul 2>&1
if errorlevel 1 (
    if %HEALTH_TRIES% LSS 20 goto wait_for_backend
    echo [WARN] Backend did not respond on /health within 20s.
    echo        Continuing to launch frontend anyway.
)

REM Pass the selected backend URL into Vite so /api always follows the backend
REM even when Code Sonar falls back from 8000 to 8765.
echo [INFO] Launching frontend on http://localhost:%FRONTEND_PORT% ...
start "Code Sonar - Frontend" cmd /k ^
    "cd /d %REPO_ROOT%\frontend && ^"
    "set VITE_API_TARGET=http://127.0.0.1:%BACKEND_PORT%&& npm run dev"

echo.
echo === Code Sonar is starting ===========================================
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
