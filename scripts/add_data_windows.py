"""Copy measurements locally, then open the standard three-step workflow."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid


def prepare_inputs(root, profile, inputs):
    root = Path(root).resolve()
    if profile not in ('c10', 'crack', 'shaft'):
        raise ValueError('자료 종류를 선택하세요.')
    folder = root / 'notebooks/학습검사_업로드'
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in map(Path, inputs):
        source = source.resolve(strict=True)
        if not source.is_file() or not source.name.lower().endswith(('.xlsx', '.csv', '.csv.gz')):
            raise ValueError('CSV, CSV.GZ, XLSX 파일을 선택하세요: ' + source.name)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        destination = folder / source.name
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            destination = folder / (uuid.uuid4().hex[:8] + '_' + source.name)
        if not destination.exists():
            shutil.copy2(source, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise IOError('복사 결과를 확인하지 못했습니다: ' + source.name)
        copied.append(destination)
    if not copied:
        raise ValueError('파일을 한 개 이상 선택하세요.')
    notebook = json.loads((root / 'notebooks/09_통합테스트_샘플별결과.ipynb').read_text(encoding='utf-8'))
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            cell['execution_count'] = None
            cell['outputs'] = []
    setup = ("\n화면['family'].value = " + repr(profile) + '\n'
             "추가파일 = ROOT / " + repr(copied[0].relative_to(root).as_posix()) + '\n'
             "화면['train'].value = str(추가파일)\n"
             "화면['test'].value = str(추가파일)\n")
    code = next(c for c in reversed(notebook['cells']) if c['cell_type'] == 'code')
    code['source'] = (''.join(code['source']) + setup).splitlines(True)
    notebook['cells'][0]['source'] = [
        '# 새 데이터를 추가했습니다\n',
        '\nRun → Run All Cells를 한 번 누르면 선택한 파일과 자료 종류가 준비됩니다.\n',
        '\n① 전처리 → ② 학습 → ③ 검사 순서로 진행합니다. 같은 학습 파일을 검사한 결과는 독립 검증이 아닙니다.\n',
        '\n이미 학습한 화면에서 새 샘플만 반복 검사하려면, 그 화면의 ③ 새 검사 파일 올리기를 사용하세요.\n',
        '\n여러 파일을 추가했다면 목록에서 원하는 학습 파일과 검사 파일을 각각 고를 수 있습니다.\n',
    ]
    run_folder = root / 'notebooks/추가데이터실행'
    run_folder.mkdir(exist_ok=True)
    destination = run_folder / ('추가데이터_' + uuid.uuid4().hex[:8] + '.ipynb')
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding='utf-8')
    temporary.replace(destination)
    return destination, copied


def choose_inputs():
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk()
    window.title('새 데이터 추가')
    window.geometry('560x290')
    selected = tk.StringVar(value='crack')
    tk.Label(window, text='1. 자료 종류를 선택하세요', font=('맑은 고딕', 14)).pack(pady=(18, 8))
    for name, value in [('기존 C10·C80 열처리 ECT', 'c10'), ('크랙', 'crack'), ('샤프트 열처리', 'shaft')]:
        tk.Radiobutton(window, text=name, variable=selected, value=value, font=('맑은 고딕', 11)).pack(anchor='w', padx=60)
    outcome = []

    def choose():
        paths = filedialog.askopenfilenames(parent=window, title='새 CSV 또는 Excel 선택 (여러 파일 가능)', filetypes=[('측정 데이터', '*.xlsx *.csv *.csv.gz'), ('모든 파일', '*.*')])
        if paths:
            outcome.extend([selected.get(), paths])
            window.destroy()

    tk.Button(window, text='2. 새 파일 선택 → 분석 화면 열기', command=choose, font=('맑은 고딕', 12), width=35, height=2).pack(pady=14)
    window.mainloop()
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=('c10', 'crack', 'shaft'))
    parser.add_argument('--input', nargs='+', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.input:
        if not args.profile:
            parser.error('--input을 쓰려면 --profile도 지정하세요.')
        profile, inputs = args.profile, args.input
    else:
        answer = choose_inputs()
        if not answer:
            print('파일 선택을 취소했습니다. 기존 데이터는 변경하지 않았습니다.')
            return 0
        profile, inputs = answer
    notebook, files = prepare_inputs(root, profile, inputs)
    print(f'{len(files)}개 파일 복사·해시 확인 완료. 원본은 수정하지 않았습니다.')
    if args.prepare_only:
        return 0
    os.chdir(root)
    os.environ['ECT_PROJECT_ROOT'] = str(root)
    os.environ['ECT_DATA_MODE'] = 'company'
    os.execv(sys.executable, [sys.executable, '-m', 'jupyterlab', '--ip=127.0.0.1', '--port=8888',
                             '--ServerApp.root_dir=' + str(root),
                             '--LabApp.default_url=/lab/tree/' + notebook.relative_to(root).as_posix()])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('새 데이터 추가를 완료하지 못했습니다:', exc)
        sys.exit(1)
