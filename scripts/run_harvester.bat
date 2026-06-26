@echo off
REM 24/7 supervisor: runs the interview harvester forever, auto-restarting on crash.
REM Logs to E:\kn-data\logs\harvest.log. Launched by the "KnessetHarvester" scheduled task.
cd /d C:\Users\noams\knesset-osint
set HF_HOME=E:\kn-data\models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
:loop
echo [%date% %time%] starting harvester >> E:\kn-data\logs\harvest.log
".venv\Scripts\python.exe" scripts\worker_harvest.py >> E:\kn-data\logs\harvest.log 2>&1
echo [%date% %time%] harvester exited (code %errorlevel%), restarting in 30s >> E:\kn-data\logs\harvest.log
timeout /t 30 /nobreak >nul
goto loop
