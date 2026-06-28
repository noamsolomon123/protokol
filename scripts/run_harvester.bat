@echo off
REM 24/7 supervisor: runs the PARALLEL interview harvester forever, auto-restarting on crash.
REM Parallel = discovery thread + 3 concurrent yt-dlp downloads + 1 batched-GPU transcriber,
REM so the GPU never idles during downloads/throttle (~2-5x faster than the serial harvester).
REM Logs to E:\kn-data\logs\harvest.log. Launched at boot by the KnessetHarvester startup shortcut.
cd /d C:\Users\noams\knesset-osint
set HF_HOME=E:\kn-data\models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
:loop
echo [%date% %time%] starting parallel harvester >> E:\kn-data\logs\harvest.log
REM per-mk 25 = take ALL new results per search: batched GPU is ~75x realtime, so the
REM YouTube search quota (100/day) is the bottleneck — grab the max per search to feed it.
REM --deep (F9): 5 query/order combos per MK, deduped, to grow the historical corpus past
REM the recent-25/MK cap. ~5x quota/MK -> fewer MKs/pass, deeper coverage (corpus saturated).
".venv\Scripts\python.exe" scripts\worker_harvest_parallel.py --download-workers 3 --batch-size 8 --per-mk 25 --dl-queue 30 --deep >> E:\kn-data\logs\harvest.log 2>&1
echo [%date% %time%] harvester exited (code %errorlevel%), restarting in 30s >> E:\kn-data\logs\harvest.log
timeout /t 30 /nobreak >nul
goto loop
