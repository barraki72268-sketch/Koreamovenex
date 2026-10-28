@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
echo 새 데이터의 종류와 파일을 선택하세요. 원본은 수정하지 않습니다.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" -AddData
set "RUN_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %RUN_RESULT%
