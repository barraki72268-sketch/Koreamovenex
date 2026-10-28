@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
set "RUN_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %RUN_RESULT%
