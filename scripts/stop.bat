@echo off
REM ============================================================================
REM Code Sonar — stop the running services (Windows).
REM
REM Stops only the command windows created by scripts\start.bat. It does not
REM kill arbitrary processes just because they happen to use a common port.
REM ============================================================================

setlocal enableextensions

echo Stopping Code Sonar...

REM Close the backend window and its child process tree if present.
taskkill /FI "WINDOWTITLE eq Code Sonar - Backend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [WARN] No 'Code Sonar - Backend' window found.
) else (
    echo [OK] Backend window stopped.
)

REM Close the frontend window and its child process tree if present.
taskkill /FI "WINDOWTITLE eq Code Sonar - Frontend*" /T /F >nul 2>&1
if errorlevel 1 (
    echo [WARN] No 'Code Sonar - Frontend' window found.
) else (
    echo [OK] Frontend window stopped.
)

echo Code Sonar stopped. No unrelated port-owning processes were terminated.
endlocal
exit /b 0
