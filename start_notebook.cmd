@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
echo 브라우저에서 노트북이 열립니다. 이 창을 닫으면 실행이 종료됩니다.
".venv\Scripts\python.exe" -m jupyterlab --ip=127.0.0.1 --port=8888 --ServerApp.root_dir="%CD%" --LabApp.default_url="/lab/tree/notebooks/01_처음부터_분석하기.ipynb"
popd
exit /b
:missing
echo install_windows.cmd 를 먼저 실행하세요.
popd
pause
exit /b 1
