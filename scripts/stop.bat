@echo off
REM ============================================================================
REM Code Sonar — stop the running services (Windows).
REM
REM Closes the backend and frontend windows started by start.bat.
REM If start.sh was used (Unix-style), use scripts\stop.sh from a bash
REM shell instead.
REM ============================================================================

setlocal enableextensions

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

echo Stopping Code Sonar...

REM ---- Close the backend window if present -------------------------------
taskkill /FI "WINDOWTITLE eq Code Sonar - Backend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [WARN] No 'Code Sonar - Backend' window found.
)

REM ---- Close the frontend window if present ------------------------------
taskkill /FI "WINDOWTITLE eq Code Sonar - Frontend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [WARN] No 'Code Sonar - Frontend' window found.
)

REM ---- Belt-and-braces: kill any uvicorn / vite still bound to the ports ---
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":8000 .*LISTENING"') do (
    echo Killing PID %%P on :8000
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":8765 .*LISTENING"') do (
    echo Killing PID %%P on :8765
    taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":5173 .*LISTENING"') do (
    echo Killing PID %%P on :5173
    taskkill /PID %%P /F >nul 2>&1
)

echo Code Sonar stopped.
endlocal
exit /b 0
