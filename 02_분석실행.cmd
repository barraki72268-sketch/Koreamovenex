@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
set "ECT_PROJECT_ROOT=%CD%"
set "ECT_DATA_MODE=company"
set "ECT_CSV_PATH=%CD%\data\private\C10A_49513-75270R.csv.gz"
echo 브라우저에서 09번 노트북이 열립니다. 이 창을 닫으면 실행이 종료됩니다.
echo Run - Run All Cells를 한 번 누르고 1, 2, 3번 순서로 진행하세요.
".venv\Scripts\python.exe" -m jupyterlab --ip=127.0.0.1 --port=8888 --ServerApp.root_dir="%CD%" --LabApp.default_url="/lab/tree/notebooks/09_통합테스트_샘플별결과.ipynb"
set "RUN_RESULT=%ERRORLEVEL%"
popd
pause
exit /b %RUN_RESULT%
:missing
echo 01_설치.cmd를 먼저 실행하세요.
popd
pause
exit /b 1
