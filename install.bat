@echo off
setlocal enabledelayedexpansion
echo.
echo  ============================================
echo   ENTIENT Remote Worker — One-Click Install
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Install Python 3.10+ from python.org
    echo     Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)
for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYVER=%%a
echo [OK] Python %PYVER% found

:: Check Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [X] Git not found. Install from git-scm.com
    pause
    exit /b 1
)
echo [OK] Git found

:: Get coordinator URL
echo.
set /p COORD_URL="Coordinator URL (e.g. http://192.168.1.100:8420): "
if "!COORD_URL!"=="" set COORD_URL=http://localhost:8420

:: Get worker name
set /p WORKER_NAME="Worker name (e.g. gaming-pc): "
if "!WORKER_NAME!"=="" set WORKER_NAME=%COMPUTERNAME%

:: Create virtual environment
echo.
echo [1/5] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo [X] Failed to create venv
    pause
    exit /b 1
)

:: Install requests
echo [2/5] Installing dependencies...
.venv\Scripts\pip install requests -q

:: Clone repos
echo [3/5] Cloning repositories...
if not exist repos mkdir repos

if not exist repos\entient-interceptor (
    git clone https://github.com/Entient/entient-interceptor.git repos/entient-interceptor
) else (
    echo       entient-interceptor already cloned, pulling latest...
    cd repos\entient-interceptor && git pull && cd ..\..
)

if not exist repos\entient-agents (
    git clone https://github.com/Entient/entient-agents.git repos/entient-agents
) else (
    echo       entient-agents already cloned, pulling latest...
    cd repos\entient-agents && git pull && cd ..\..
)

:: Install repo deps
echo [4/5] Installing repo dependencies...
.venv\Scripts\pip install -e repos/entient-agents -q 2>nul
.venv\Scripts\pip install -e repos/entient-interceptor -q 2>nul

:: Write config
echo [5/5] Writing config...
(
echo {
echo   "coordinator_url": "!COORD_URL!",
echo   "worker_name": "!WORKER_NAME!",
echo   "capabilities": ["compile", "mine", "retrain", "crossindex", "coverage"],
echo   "poll_interval": 10,
echo   "heartbeat_interval": 60
echo }
) > config.json

:: Create bank dir
if not exist "%USERPROFILE%\.entient\bank" mkdir "%USERPROFILE%\.entient\bank"

echo.
echo  ============================================
echo   Install complete!
echo.
echo   Coordinator: !COORD_URL!
echo   Worker name: !WORKER_NAME!
echo.
echo   To start: double-click start.bat
echo  ============================================
echo.
pause
