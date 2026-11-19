@echo off
setlocal
cd /d "%~dp0" || exit /b 1
set "PYTHONPATH=%~dp0.analysis\ic705-emulator\deps"
py -3.14 -X utf8 -m tools.replay_705_font_boot "firmware\705J140.dat" ".analysis\zh-cn-preview\noto\NotoSansSC-VF.ttf" ".analysis\ic705-emulator\j140-board-return"
set "STATUS=%ERRORLEVEL%"
if /i not "%~1"=="--no-pause" pause
exit /b %STATUS%
