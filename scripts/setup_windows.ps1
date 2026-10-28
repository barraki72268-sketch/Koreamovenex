param(
    [switch]$WithVSCode,
    [switch]$SkipVSCode,
    [switch]$CheckOnly,
    [switch]$DownloadOnly,
    [string]$PythonExe = '',
    [string]$EnvironmentDirectory = '.venv'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$cache = Join-Path $root '.installer-cache'
$logdir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logdir | Out-Null
$log = Join-Path $logdir ('install-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "실행 실패 ($LASTEXITCODE): $Program" }
}

function Test-Python([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    $ErrorActionPreference = 'Continue'
    $answer = & $Candidate -c "import sys,struct; print('ECT_PY_OK' if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 'NO')" 2>$null
    return $LASTEXITCODE -eq 0 -and $answer -contains 'ECT_PY_OK'
}

function Find-Python {
    if ($PythonExe) {
        if (-not (Test-Python $PythonExe)) { throw '지정한 Python은 3.12 64비트 실행 파일이어야 합니다.' }
        return $PythonExe
    }
    foreach ($candidate in @((Join-Path $root '.venv\Scripts\python.exe'), (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'))) {
        if (Test-Python $candidate) { return $candidate }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        # Windows PowerShell 5 treats a launcher's stderr as a terminating error
        # under Stop, even when Python is simply not installed yet.
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $found = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            $launcherExit = $LASTEXITCODE
        } catch {
            $found = @()
            $launcherExit = -1
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($launcherExit -eq 0 -and (Test-Python ($found | Select-Object -Last 1))) { return ($found | Select-Object -Last 1) }
    }
    foreach ($key in @('HKCU:\Software\Python\PythonCore\3.12\InstallPath', 'HKLM:\Software\Python\PythonCore\3.12\InstallPath')) {
        try {
            if (Test-Path $key) {
                $installPath = (Get-Item $key -ErrorAction Stop).GetValue('')
                if ($installPath) {
                    $candidate = Join-Path $installPath 'python.exe'
                    if (Test-Python $candidate) { return $candidate }
                }
            }
        } catch { continue }
    }
    return ''
}

function Get-OfficialInstaller([string]$Url, [string]$Filename, [string]$Publisher) {
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $destination = Join-Path $cache $Filename
    Write-Host "공식 설치 파일 확인: $Filename"
    if (-not (Test-Path -LiteralPath $destination)) {
        $partial = $destination + '.partial'
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $partial
        Move-Item -LiteralPath $partial -Destination $destination
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $destination
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $Publisher) {
        throw "설치 파일의 디지털 서명을 확인하지 못했습니다. 실행하지 않습니다: $destination (캐시 파일을 확인하세요.)"
    }
    Write-Host ('서명 확인 완료: ' + $signature.SignerCertificate.Subject)
    return $destination
}

function Find-Code {
    foreach ($path in @((Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'), (Join-Path $env:ProgramFiles 'Microsoft VS Code\bin\code.cmd'))) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $code = Get-Command code.cmd -ErrorAction SilentlyContinue
    if ($code) { return $code.Source }
    return ''
}

function Test-XGBoost([string]$Interpreter) {
    $ErrorActionPreference = 'Continue'
    & $Interpreter -c 'import xgboost' 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

try {
    Start-Transcript -Path $log | Out-Null
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw '현재 설치 구성은 Windows 10/11 x64 PC용입니다.' }
    if ($root.Length -gt 45) { throw '설치 폴더 경로가 너무 깁니다. ZIP을 C:\Movenex 같은 짧은 경로에 풀고 다시 실행하세요. Windows 파일 경로 제한으로 Jupyter 설치가 실패할 수 있습니다.' }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'requirements.txt'))) { throw 'ZIP 전체를 압축 해제한 뒤 실행하세요.' }
    $environment = [IO.Path]::GetFullPath((Join-Path $root $EnvironmentDirectory))
    if (-not $environment.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '실행 환경은 프로그램 폴더 안에 만들어야 합니다.' }
    $python = Find-Python
    $code = Find-Code
    Write-Host "프로그램 폴더: $root"
    Write-Host "Python 3.12: $(if($python){$python}else{'없음 - 공식 설치 파일로 준비합니다'})"
    Write-Host "VS Code: $(if($code){$code}else{'아직 설치되지 않음'})"
    if ($CheckOnly) { Write-Host '점검 완료. 다운로드·설치·환경 변경은 하지 않았습니다.'; return }
    if ($DownloadOnly) {
        Get-OfficialInstaller 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'python-3.12.10-amd64.exe' 'Python Software Foundation' | Out-Null
        Get-OfficialInstaller 'https://update.code.visualstudio.com/latest/win32-x64-user/stable' 'VSCodeUserSetup-x64.exe' 'Microsoft Corporation' | Out-Null
        Get-OfficialInstaller 'https://aka.ms/vc14/vc_redist.x64.exe' 'vc_redist.x64.exe' 'Microsoft Corporation' | Out-Null
        Write-Host '공식 설치 파일 3개 다운로드·서명 점검 완료. 설치는 하지 않았습니다.'
        return
    }
    if (-not $WithVSCode -and -not $SkipVSCode) {
        $choice = Read-Host 'VS Code와 Python/Jupyter 확장도 함께 설치할까요? [Y/n] (Enter: 함께 설치)'
        $WithVSCode = $choice -notmatch '^[nN]$'
    }
    Write-Host '[1/5] Python 준비'
    if (-not $python) {
        $installer = Get-OfficialInstaller 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' 'python-3.12.10-amd64.exe' 'Python Software Foundation'
        $target = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
        $proc = Start-Process -FilePath $installer -ArgumentList ('/passive InstallAllUsers=0 Include_launcher=0 Include_tcltk=1 PrependPath=0 Include_test=0 Shortcuts=0 TargetDir="' + $target + '"') -Wait -PassThru
        if ($proc.ExitCode -notin @(0,3010)) { throw "Python 설치 실패: $($proc.ExitCode)" }
        $python = Find-Python
        if (-not $python) { throw 'Python 설치 후 실행 파일을 확인하지 못했습니다. 로그를 전달해 주세요.' }
    }
    Write-Host '[2/5] 이 프로그램 전용 실행 환경 준비'
    $envPython = Join-Path $environment 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $envPython)) { Invoke-Checked $python @('-m','venv',$environment) }
    if (-not (Test-Python $envPython)) { throw '기존 실행 환경이 Python 3.12 64비트가 아닙니다. 기존 폴더를 보존한 상태에서 담당자에게 문의하세요.' }
    Write-Host '[3/5] Jupyter와 분석 패키지 설치 (인터넷 필요)'
    Invoke-Checked $envPython @('-m','pip','install','--disable-pip-version-check','-r',(Join-Path $root 'requirements.txt'))
    Invoke-Checked $envPython @('-m','pip','check')
    Invoke-Checked $envPython @('-m','ipykernel','install','--sys-prefix','--name','movenex-ect','--display-name','Python (Movenex ECT)')
    foreach ($name in @('data/private','data/processed','results','notebooks/학습검사_업로드')) { New-Item -ItemType Directory -Force -Path (Join-Path $root $name) | Out-Null }
    Write-Host '[4/5] VS Code 준비'
    if ($WithVSCode) {
        if (-not $code) {
            $installer = Get-OfficialInstaller 'https://update.code.visualstudio.com/latest/win32-x64-user/stable' 'VSCodeUserSetup-x64.exe' 'Microsoft Corporation'
            $proc = Start-Process -FilePath $installer -ArgumentList '/VERYSILENT /NORESTART /MERGETASKS="!runcode,!desktopicon"' -Wait -PassThru
            if ($proc.ExitCode -notin @(0,3010)) { throw "VS Code 설치 실패: $($proc.ExitCode)" }
            $code = Find-Code
            if (-not $code) { throw 'VS Code 실행 경로를 확인하지 못했습니다.' }
        }
        foreach ($extension in @('ms-python.python','ms-toolsai.jupyter','ms-python.debugpy')) { Invoke-Checked $code @('--install-extension',$extension) }
    } else { Write-Host 'VS Code는 생략했습니다. 브라우저에서 동일하게 실행할 수 있습니다.' }
    Write-Host '[5/5] 실행에 필요한 모듈 확인'
    if (-not (Test-XGBoost $envPython)) {
        Write-Host 'XGBoost DLL을 불러오지 못해 Microsoft Visual C++ 실행 구성요소를 준비합니다. Windows 권한 확인 창이 나타날 수 있습니다.'
        $installer = Get-OfficialInstaller 'https://aka.ms/vc14/vc_redist.x64.exe' 'vc_redist.x64.exe' 'Microsoft Corporation'
        $proc = Start-Process -FilePath $installer -ArgumentList '/passive /norestart' -Wait -PassThru
        if ($proc.ExitCode -notin @(0,3010,1638)) { throw "Visual C++ 실행 구성요소 설치 실패: $($proc.ExitCode)" }
        if (-not (Test-XGBoost $envPython)) { throw 'XGBoost를 불러오지 못했습니다. 설치 로그를 전달해 주세요. Windows 재시작이 필요할 수도 있습니다.' }
    }
    Invoke-Checked $envPython @('-c',"import jupyterlab,ipywidgets,numpy,pandas,sklearn,xgboost,matplotlib,lxml,tkinter; from ectlab.workflow_ui import show_workflow_app; print('PASS: Jupyter and analysis imports')")
    Write-Host "설치 완료. 02_분석실행.cmd를 더블클릭하세요. 로그: $log" -ForegroundColor Green
} catch {
    Write-Host ('설치가 끝나지 않았습니다: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host "회사 보안 정책이나 인터넷 차단이 있는지 확인하고, 다음 로그를 담당자에게 전달하세요: $log"
    exit 1
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
