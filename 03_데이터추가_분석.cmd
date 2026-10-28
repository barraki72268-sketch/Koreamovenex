@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
echo 새 데이터의 종류와 파일을 선택하세요. 원본은 수정하지 않습니다.
".venv\Scripts\python.exe" scripts/add_data_windows.py
set "RUN_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %RUN_RESULT%
:missing
echo 01_설치.cmd를 먼저 실행하세요.
popd
pause
exit /b 1
