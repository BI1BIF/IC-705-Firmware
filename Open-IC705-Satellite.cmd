@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps;%PYTHONPATH%"
py -3.14 -X utf8 -m tools.virtual_705_satellite
if errorlevel 1 pause
