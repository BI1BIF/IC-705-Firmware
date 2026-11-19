@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
set "OUT=.analysis\cw-display-%RANDOM%-%RANDOM%"
".venv\Scripts\python.exe" -X utf8 -m tools.replay_705_cw_display "firmware\705J140.dat" "%OUT%"
set "STATUS=%ERRORLEVEL%"
if not "%STATUS%"=="0" goto done
if /i "%~1"=="--no-pause" goto done
start "" "%OUT%\rtty-frame-3.png"
:done
if /i not "%~1"=="--no-pause" pause
exit /b %STATUS%
