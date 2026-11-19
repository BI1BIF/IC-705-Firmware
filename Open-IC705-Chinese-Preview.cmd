@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
set "ZH_FONT=.analysis\zh-cn-preview\display-page\IC705LabSC-Regular.ttf"
if not exist "%ZH_FONT%" (
    echo Font subset missing. See docs\IC705_ZH_DISPLAY_PAGE.md to generate it.
    pause
    exit /b 1
)
py -3.14 -X utf8 -m tools.virtual_705_panel "firmware\705J140.dat" --zh-font "%ZH_FONT%"
if errorlevel 1 pause
