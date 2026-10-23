@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
echo [1/4] Python 3.12 확인
py -3.12 -c "import sys; assert sys.version_info[:2] == (3,12)" >nul 2>&1
if errorlevel 1 goto missing_python
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
echo [2/4] 분석 프로그램 설치 - 인터넷 연결 필요
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo [3/4] 설치 상태 확인
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
echo [4/4] 노트북 실행 준비
".venv\Scripts\python.exe" -c "from pathlib import Path; [Path(p).mkdir(parents=True, exist_ok=True) for p in ['data/private','data/raw/original','data/raw/returned','data/processed','results']]"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m ipykernel install --sys-prefix --name movenex-ect --display-name "Python (Movenex ECT)"
if errorlevel 1 goto failed
echo 설치 완료. start_notebook.cmd 파일을 실행하세요.
popd
pause
exit /b 0
:missing_python
echo Python 3.12 64비트와 Python Launcher를 먼저 설치하세요.
echo 설치 주소: https://www.python.org/downloads/windows/
popd
pause
exit /b 1
:failed
echo 설치가 완료되지 않았습니다. 위 오류 내용을 확인하고 README의 문제 해결을 보세요.
popd
pause
exit /b 1
