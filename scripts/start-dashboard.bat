@echo off
setlocal enabledelayedexpansion

:: Configuration
if "%PORT%"=="" set PORT=8000
set CONDA_ENV=mcpfolio

echo ========================================
echo       MCPFolio Dashboard Startup
echo ========================================

:: 1. Check Ollama
echo Checking Ollama status...
ollama list >nul 2>&1
if errorlevel 1 (
    echo Starting Ollama serve...
    start "" /b ollama serve >nul 2>&1
    timeout /t 5 /nobreak >nul
) else (
    echo Ollama is already running.
)

:: 2. Build Frontend
echo Building Frontend...
cd /d "%~dp0.."
set FRONTEND_DIR=src\web\frontend
call conda run -n %CONDA_ENV% npm --prefix %FRONTEND_DIR% install >nul 2>&1
call conda run -n %CONDA_ENV% npm --prefix %FRONTEND_DIR% run build >nul 2>&1
echo Frontend built.

:: 3. Start Backend (FastAPI)
echo Starting Backend Server...
:: Kill existing process on this port if any
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

start "mcpfolio-backend" /b cmd /c conda run -n %CONDA_ENV% python -m uvicorn src.web.main:app --host 127.0.0.1 --port %PORT%

:: 4. Wait for Health Check
echo Waiting for health check...
set RETRY_COUNT=0
set MAX_RETRIES=30
:healthloop
if !RETRY_COUNT! geq %MAX_RETRIES% goto healthfail

:: Write curl output to temp file to avoid pipe errorlevel issues
curl -s http://127.0.0.1:%PORT%/api/health > "%TEMP%\mcpfolio_health.tmp" 2>nul
findstr /c:"healthy" "%TEMP%\mcpfolio_health.tmp" >nul 2>&1
if !errorlevel!==0 (
    del "%TEMP%\mcpfolio_health.tmp" 2>nul
    echo Backend is healthy!
    goto healthpass
)
set /a RETRY_COUNT+=1
timeout /t 1 /nobreak >nul
goto healthloop

:healthfail
del "%TEMP%\mcpfolio_health.tmp" 2>nul
echo Backend failed to start or is unhealthy.
echo Check that conda environment "%CONDA_ENV%" exists and Ollama is running.
pause
exit /b 1

:healthpass

:: 5. Open Browser
set URL=http://127.0.0.1:%PORT%
echo Opening Dashboard at %URL%
start "" "%URL%"

echo ----------------------------------------
echo Platform is ready!
echo Press Ctrl+C to stop the servers.
echo ----------------------------------------

:: Keep script running so backend stays alive
pause >nul
