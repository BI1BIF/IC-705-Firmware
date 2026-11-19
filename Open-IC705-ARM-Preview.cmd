@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
set "ZH_FONT=.analysis\zh-cn-preview\noto\NotoSansSC-VF.ttf"
if not exist "%ZH_FONT%" (
    echo Source font missing. See docs\IC705_ZH_CATALOG.md.
    pause
    exit /b 1
)
where arm-none-eabi-gcc >nul 2>nul
if errorlevel 1 (
    echo Arm GNU Toolchain is not on PATH. See docs\IC705_ZH_ARM.md.
    pause
    exit /b 1
)
py -3.14 -X utf8 -m tools.virtual_705_display_catalog "firmware\705J140.dat" --font-source "%ZH_FONT%" %*
if errorlevel 1 pause
