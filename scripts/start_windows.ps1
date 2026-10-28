param([switch]$AddData,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
try {
    $settingsPath=Join-Path $root '.jupyter/windows-runtime.json'
    if (Test-Path -LiteralPath $settingsPath) {
        $settings=Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $python=$settings.python_exe
    } else { $python=Join-Path $root '.venv/Scripts/python.exe' }
    if (-not $python -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '01_설치.cmd를 먼저 실행하세요. 설치된 실행 환경을 찾을 수 없습니다.' }
    $env:ECT_PROJECT_ROOT=$root
    $env:ECT_DATA_MODE='company'
    $env:ECT_CSV_PATH=Join-Path $root 'data/private/C10A_49513-75270R.csv.gz'
    $ErrorActionPreference='Continue'
    if ($CheckOnly) {
        Write-Host "프로그램 폴더: $root"
        Write-Host "연결된 Python: $python"
        & $python -c "import sys; print('PASS runtime connection: '+sys.executable)"
    } elseif ($AddData) {
        & $python (Join-Path $root 'scripts/add_data_windows.py')
    } else {
        Write-Host '브라우저에서 09번 노트북이 열립니다. 이 창을 닫으면 실행이 종료됩니다.'
        & $python -m jupyterlab --ip=127.0.0.1 --port=8888 "--ServerApp.root_dir=$root" '--LabApp.default_url=/lab/tree/notebooks/09_통합테스트_샘플별결과.ipynb'
    }
    exit $LASTEXITCODE
} catch {
    Write-Host ('실행을 완료하지 못했습니다: '+$_.Exception.Message) -ForegroundColor Red
    exit 1
}
