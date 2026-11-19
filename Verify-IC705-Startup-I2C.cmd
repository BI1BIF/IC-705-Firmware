@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
py -3.14 -X utf8 -m tools.replay_705_font_boot --riic0 "firmware\705J140.dat" ".analysis\ic705-emulator\j140-riic0"
set "STATUS=%ERRORLEVEL%"
if /i not "%~1"=="--no-pause" pause
exit /b %STATUS%
