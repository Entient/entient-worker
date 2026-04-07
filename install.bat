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
echo [1/6] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo [X] Failed to create venv
    pause
    exit /b 1
)

:: Install Python packages
echo [2/6] Installing Python packages...
.venv\Scripts\pip install requests pynacl cryptography cbor2 pyyaml -q
if errorlevel 1 (
    echo [!] Some packages failed to install. Continuing...
)

:: Clone repos (all 3 needed for full capability)
echo [3/6] Cloning repositories...
if not exist repos mkdir repos

if not exist repos\entient (
    echo       Cloning entient (core^)...
    git clone https://github.com/Entient/entient.git repos/entient
) else (
    echo       entient already cloned, pulling latest...
    pushd repos\entient
    git pull
    popd
)

if not exist repos\entient-agents (
    echo       Cloning entient-agents...
    git clone https://github.com/Entient/entient-agents.git repos/entient-agents
) else (
    echo       entient-agents already cloned, pulling latest...
    pushd repos\entient-agents
    git pull
    popd
)

if not exist repos\entient-interceptor (
    echo       Cloning entient-interceptor...
    git clone https://github.com/Entient/entient-interceptor.git repos/entient-interceptor
) else (
    echo       entient-interceptor already cloned, pulling latest...
    pushd repos\entient-interceptor
    git pull
    popd
)

:: Install repos in dependency order (entient first, then agent, then interceptor)
echo [4/6] Installing repo packages...
echo       Installing entient (core)...
.venv\Scripts\pip install -e repos/entient -q
if errorlevel 1 (
    echo [!] entient install failed — retrain/mine may not work
)
echo       Installing entient-agents...
.venv\Scripts\pip install -e repos/entient-agents -q
if errorlevel 1 (
    echo [!] entient-agents install failed — mine may not work
)
echo       Installing entient-interceptor...
.venv\Scripts\pip install -e repos/entient-interceptor -q
if errorlevel 1 (
    echo [!] entient-interceptor install failed — retrain may not work
)

:: Write config
echo [5/6] Writing config...
(
echo {
echo   "coordinator_url": "!COORD_URL!",
echo   "worker_name": "!WORKER_NAME!",
echo   "capabilities": "auto",
echo   "poll_interval": 10,
echo   "heartbeat_interval": 60
echo }
) > config.json

:: Create data dirs
echo [6/6] Creating data directories...
if not exist "%USERPROFILE%\.entient\bank" mkdir "%USERPROFILE%\.entient\bank"
if not exist "%USERPROFILE%\.entient\v2" mkdir "%USERPROFILE%\.entient\v2"
if not exist "%USERPROFILE%\.entient\weights" mkdir "%USERPROFILE%\.entient\weights"
if not exist "%USERPROFILE%\.entient\forwards" mkdir "%USERPROFILE%\.entient\forwards"

:: Check capabilities
echo.
echo  Checking what this machine can run...
echo.
.venv\Scripts\python worker.py --check

echo.
echo  ============================================
echo   Install complete!
echo.
echo   Coordinator: !COORD_URL!
echo   Worker name: !WORKER_NAME!
echo.
echo   NEXT STEPS:
echo   1. Run: start.bat --bootstrap
echo      (Downloads DBs from coordinator to unlock more capabilities)
echo   2. Then: start.bat
echo      (Starts the worker)
echo   3. For CROSSINDEX: copy shapes.db (5GB) via USB to
echo      %USERPROFILE%\.entient\v2\shapes.db
echo  ============================================
echo.
pause
