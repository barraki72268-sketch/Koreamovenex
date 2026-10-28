"""Build one private Windows delivery: actual data only, no demo/research assets."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import subprocess
import zipfile


def build(root, destination):
    root=Path(root).resolve();destination=Path(destination).resolve()
    manifest=json.loads((root/'notebooks/전체실행_자료.json').read_text(encoding='utf-8'))
    assert {s['key'] for s in manifest['sources']}=={'C10A','C80B','crack','shaft'}
    assert len(manifest['sources'])==4
    entries={}
    names=['00_먼저읽어주세요.txt','01_설치.cmd','02_분석실행.cmd','03_데이터추가_분석.cmd',
           'requirements.txt','scripts/setup_windows.ps1','scripts/start_windows.ps1',
           'scripts/add_data_windows.py','.vscode/extensions.json','.vscode/settings.json',
           'notebooks/09_통합테스트_샘플별결과.ipynb']
    names += [p.relative_to(root).as_posix() for p in (root/'ectlab').rglob('*.py')]
    for name in names:
        data=(root/name).read_bytes()
        if name.endswith('.cmd'):
            data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        if name=='ectlab/workflow_ui.py':
            data=data.decode('utf-8').replace('서버 목록','파일 목록').encode('utf-8')
        if name.endswith('.ipynb'):
            notebook=json.loads(data.decode('utf-8'))
            for cell in notebook['cells']:
                if cell['cell_type']=='markdown':
                    cell['source']=[line.replace('연구 비교는 10번에 보존했습니다.','') for line in cell['source']]
            data=json.dumps(notebook,ensure_ascii=False,indent=1).encode('utf-8')
        entries[name]=data
    guide=(root/'docs/회사PC_간편설치.md').read_text(encoding='utf-8')
    guide=guide.replace('실제 데이터 포함 ZIP은 담당자에게 비공개로 받습니다. GitHub의 ZIP에는 합성 연습 자료만 있습니다.',
                        '이 ZIP에 실제 C10A·C80B·크랙·샤프트 데이터가 모두 포함되어 있습니다.')
    start=guide.index('![학습 자료 선택]');end=guide.index('## VS Code에서 실행할 때')
    guide=guide[:start]+'실제 파일은 이미 목록에 연결되어 있습니다. 데이터와 결과는 이 PC에 저장됩니다.\n\n'+guide[end:]
    entries['사용설명서.md']=guide.encode('utf-8')
    intro='''한국무브넥스 — 회사 실행 통합본

이 ZIP 하나에 설치·분석 프로그램과 실제 데이터 4종이 모두 들어 있습니다.
폴더 이름은 바꿔도 됩니다. ZIP 전체를 원하는 폴더에 압축 해제하세요.

01_설치.cmd              처음 한 번 설치 (인터넷 필요)
02_분석실행.cmd          포함된 실제 데이터로 분석
03_데이터추가_분석.cmd   새로운 CSV·Excel을 추가해 분석

설치 후 02번 실행 → 브라우저의 Run → Run All Cells → ① 전처리 → ② 학습 → ③ 검사
이미 학습한 화면에 새 샘플만 넣을 때는 그 화면의 ③ 새 검사 파일 올리기를 사용하세요.

포함 데이터: C10A 30,627행 / C80B 24,936행 / 크랙 30,252행 / 샤프트 110,510행
회사 PC에서 실행되며 NAS·연구실 서버·개발자 PC에 연결하지 않습니다.
데이터는 data/private, 분석 결과는 results에 저장됩니다.
이 파일에는 실제 회사 데이터가 있으므로 회사 관계자에게 비공개로 전달하세요.

사용설명서.html을 브라우저에서 열면 설치·실행 방법을 볼 수 있습니다.
'''
    entries['00_먼저읽어주세요.txt']=intro.replace('\n','\r\n').encode('utf-8-sig')
    page='<!doctype html><meta charset="utf-8"><title>회사 실행 통합본 안내</title><style>body{font:18px/1.8 sans-serif;max-width:1000px;margin:40px auto;padding:0 20px}pre{white-space:pre-wrap;font:inherit}h1{color:#17354b}</style><h1>한국무브넥스 회사 실행 통합본</h1><pre>'+html.escape(intro)+'\n'+html.escape(guide)+'</pre>'
    entries['사용설명서.html']=page.encode('utf-8')
    hashes={}
    for source in manifest['sources']:
        path=Path(source['path']);path=path if path.is_absolute() else root/path
        path=path.resolve(strict=True)
        if not path.is_relative_to(root/'data/private'):raise ValueError('회사 데이터 경로를 확인하세요.')
        name=path.relative_to(root).as_posix();data=path.read_bytes()
        entries[name]=data;source['path']=name;hashes[name]=hashlib.sha256(data).hexdigest()
    manifest['storage']='Company PC local disk; actual data only; no NAS'
    entries['notebooks/전체실행_자료.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip()
    except (OSError,subprocess.CalledProcessError):commit='local'
    entries['배포정보.json']=json.dumps({'source_commit':commit,'actual_data_files':hashes,'demo_data_included':False},ensure_ascii=False,indent=2).encode('utf-8')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in entries.items():archive.writestr('Movenex/'+name,data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        names=archive.namelist()
        assert len([n for n in names if n.endswith('.cmd')])==3
        assert len([n for n in names if n.endswith('.ipynb')])==1
        assert not any('/demo/' in n or '/tests/' in n or '/gpu/' in n or '.jupyter/' in n for n in names)
        for name,digest in hashes.items():assert hashlib.sha256(archive.read('Movenex/'+name)).hexdigest()==digest
    print('PASS: one private package, three CMDs, one notebook, four actual datasets, no demo assets')
    print(destination)
    return destination


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(Path(__file__).resolve().parents[1],args.output)
