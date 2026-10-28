@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist "%~dp0scripts\setup_windows.ps1" goto not_extracted
echo Python 3.12, Jupyter, 분석 패키지와 선택한 VS Code 확장을 설치합니다.
echo 공식 Python.org, Microsoft, PyPI에서 다운로드하며 인터넷 연결이 필요합니다.
echo 회사 PC의 프로그램 설치 규정에 따라 진행해 주세요.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %INSTALL_RESULT%
:not_extracted
echo ZIP 안에서 바로 실행할 수 없습니다. ZIP 전체를 C:\Movenex에 압축 해제한 뒤 실행하세요.
echo 01_설치.cmd와 scripts 폴더가 같은 폴더 안에 있어야 합니다.
popd
pause
exit /b 1
