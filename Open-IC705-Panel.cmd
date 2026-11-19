@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
py -3.14 -X utf8 -m tools.virtual_705_panel "firmware\705J140.dat"
if errorlevel 1 pause
