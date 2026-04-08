@echo off
:: ENTIENT Worker Watchdog
:: Registered as a scheduled task via schtasks — no signing required.
:: Checks if worker.py is running; restarts it if not.

set WORKER_DIR=C:\entient-worker
set PYTHON=%WORKER_DIR%\.venv\Scripts\python.exe
set COORD=http://100.101.178.111:8420

:: Check if worker.py is running
tasklist /FI "IMAGENAME eq python.exe" /FO CSV 2>NUL | findstr /I "python" >NUL
if errorlevel 1 goto start_worker

:: Python is running — check if it's specifically worker.py
wmic process where "name='python.exe'" get commandline 2>NUL | findstr /I "worker.py" >NUL
if errorlevel 1 goto start_worker

echo [%date% %time%] worker.py already running. OK.
goto end

:start_worker
echo [%date% %time%] worker.py not running -- restarting...
start "" /MIN cmd /c "cd /d %WORKER_DIR% && %PYTHON% worker.py --url %COORD%"
echo [%date% %time%] worker.py launched.

:end
