@echo off
REM ============================================================================
REM Code Sonar — one-command startup (Windows).
REM
REM Launches the FastAPI backend and Vite dev server in two separate
REM windows so they can be stopped independently. The user sees:
REM   - Backend at http://127.0.0.1:8000 (auto-picked if 8000 is busy,
REM     it tries 8765 next).
REM   - Frontend at http://localhost:5173 (Vite default).
REM
REM Usage:
REM   scripts\start.bat
REM
REM Shutdown:
REM   - Close both windows (clean Ctrl+C), OR
REM   - Run scripts\stop.bat (sends WM_CLOSE via taskkill).
REM ============================================================================

setlocal enableextensions enabledelayedexpansion

REM ---- Resolve repo root (this script lives in <repo>\scripts) ---------------
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "REPO_ROOT=%CD%"
popd

echo.
echo === Code Sonar startup ===============================================
echo Repo root:  %REPO_ROOT%
echo Backend:    http://127.0.0.1:8000
echo Frontend:   http://localhost:5173
echo ======================================================================
echo.

REM ---- Pick a free port (try 8000, then 8765) -------------------------------
set "BACKEND_PORT=8000"
netstat -ano | findstr /R ":8000 .*LISTENING" >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo Port 8000 in use, falling back to 8765.
    set "BACKEND_PORT=8765"
)

REM ---- Dependency checks ----------------------------------------------------
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

REM ---- Backend venv setup ---------------------------------------------------
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

REM ---- Frontend dependency install -----------------------------------------
if not exist "%REPO_ROOT%\frontend\node_modules" (
    echo [INFO] Installing frontend dependencies ...
    pushd "%REPO_ROOT%\frontend"
    call npm install || (popd & echo [ERROR] frontend install failed & exit /b 1)
    popd
)

REM ---- Launch backend in new window ----------------------------------------
echo [INFO] Launching backend on port %BACKEND_PORT% ...
start "Code Sonar - Backend" cmd /k ^
    "cd /d %REPO_ROOT%\backend && ^"
    "%VENV%\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload

REM ---- Wait for backend health --------------------------------------------
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

REM ---- Launch frontend in new window --------------------------------------
echo [INFO] Launching frontend on http://localhost:5173 ...
start "Code Sonar - Frontend" cmd /k ^
    "cd /d %REPO_ROOT%\frontend && ^"
    "npm run dev"

echo.
echo === Code Sonar is starting ===========================================
echo.
echo   Backend:  http://127.0.0.1:%BACKEND_PORT%
echo   Frontend: http://localhost:5173
echo.
echo Both servers run in their own windows. Close the windows to stop,
or run scripts\stop.bat.
echo.
echo Tip: open the frontend URL in your browser, type a repo path, and
echo      click "Run scan".
echo ======================================================================
echo.
endlocal
exit /b 0
