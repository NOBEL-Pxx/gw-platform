@echo off
chcp 65001 >nul
title GravitationalWave Platform — Start Services (v4.15)

echo ========================================
echo   GravitationalWave Platform Launcher
echo   v4.15 — Windows (Batch)
echo ========================================
echo.

set PROJECT_DIR=D:\AliCPT
set URL_FILE=C:\Users\28610\public-url.txt

cd /d %PROJECT_DIR%

:: Create docker-data if needed
if not exist "%PROJECT_DIR%\docker-data" mkdir "%PROJECT_DIR%\docker-data"

echo [1/3] Starting Docker containers...
docker compose up -d
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker failed to start.
    pause
    exit /b 1
)
echo.

echo [2/3] Waiting for services to become healthy...
call :wait_healthy
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Not all services became healthy.
    echo Run: docker compose ps
    pause
    exit /b 1
)

echo [3/3] Starting public tunnel with auto-reconnect...
echo.
echo Tunneling to localhost.run...
echo   (The tunnel runs in this window. Close this window to stop.)
echo   (If the tunnel drops, close and re-run this script, or use start-gw.ps1 for auto-reconnect)
echo.

:: Start SSH tunnel and capture URL
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 80:localhost:6001 nokey@localhost.run 2>&1 | tee "%PROJECT_DIR%\docker-data\tunnel-output.txt"

:: Extract URL from captured output
findstr /R "https://[a-z0-9]*\.lhr\.life" "%PROJECT_DIR%\docker-data\tunnel-output.txt" > "%URL_FILE%" 2>nul

echo.
echo ========================================
echo   Platform stopped.
echo   LOCAL:  https://localhost:6002
echo.
echo   To restart: double-click start-gw.bat
echo ========================================
pause
exit /b 0

:: ── Wait for healthy ──────────────────────────────────────────────────────
:wait_healthy
set TRIES=0
:loop
timeout /t 5 /nobreak >nul
set /a TRIES+=5
for /f %%i in ('docker compose -f "%PROJECT_DIR%\docker-compose.yml" ps 2^>nul ^| findstr "healthy" ^| find /c "healthy"') do set HEALTHY=%%i
if %HEALTHY% GEQ 7 (
    echo   All 7 services healthy! (%TRIES%s)
    exit /b 0
)
if %TRIES% GEQ 180 (
    echo   Timeout: only %HEALTHY%/7 healthy after 180s
    exit /b 1
)
set /a REMAINING=7-%HEALTHY%
echo   %TRIES%s: %HEALTHY%/7 healthy, waiting for %REMAINING% more...
goto loop
