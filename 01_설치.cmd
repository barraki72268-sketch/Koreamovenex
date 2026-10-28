@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
echo Python 3.12, Jupyter, 분석 패키지와 선택한 VS Code 확장을 설치합니다.
echo 공식 Python.org, Microsoft, PyPI에서 다운로드하며 인터넷 연결이 필요합니다.
echo 회사 PC의 프로그램 설치 규정에 따라 진행해 주세요.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %INSTALL_RESULT%
