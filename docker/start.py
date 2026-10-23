"""Prepare persistent notebooks and data paths, then start authenticated Jupyter."""
from pathlib import Path
import os
import shutil
import sys


def prepare(root=Path('/workspace'), output=Path('/output'), templates=Path('/opt/ect/notebooks')):
    mode = os.environ.get('ECT_DATA_MODE', 'company')
    if mode not in ('company', 'demo'):
        raise ValueError('ECT_DATA_MODE는 company 또는 demo로 설정하세요.')
    if mode == 'company':
        value = os.environ.get('ECT_CSV_PATH', '')
        if not value or not Path(value).is_file():
            raise FileNotFoundError('회사 CSV가 없습니다. .env의 ECT_CSV_DIR와 ECT_CSV_FILE을 확인하세요.')
    # Demo mode must use the bundled synthetic file, even if a CSV mount is present.
    else:
        os.environ.pop('ECT_CSV_PATH', None)
    for name in ('results', 'processed', 'notebooks'):
        folder = output / name
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / '.write-check'
        with probe.open('x'):
            pass
        probe.unlink()
    notebooks = root / 'notebooks'
    notebooks.mkdir(parents=True, exist_ok=True)
    for source in templates.glob('*.ipynb'):
        destination = notebooks / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
    print('회사 CSV 모드' if mode == 'company' else '합성 연습 데이터 모드', flush=True)
    print('결과: /workspace/results → 서버 ECT_OUTPUT_DIR/results', flush=True)


def main():
    try:
        prepare()
    except (OSError, ValueError) as error:
        print(f'시작 실패: {error}\n출력 폴더 권한과 ECT_UID/ECT_GID도 확인하세요.', file=sys.stderr)
        return 1
    os.makedirs(os.environ.get('JUPYTER_RUNTIME_DIR', '/tmp/jupyter-runtime'), exist_ok=True)
    os.makedirs(os.environ.get('HOME', '/tmp/ect-home'), exist_ok=True)
    os.execvp('python', ['python', '-m', 'jupyterlab', '--no-browser', '--ip=0.0.0.0',
                         '--port=8888', '--ServerApp.port_retries=0',
                         '--ServerApp.root_dir=/workspace',
                         '--LabApp.default_url=/lab/tree/notebooks/01_처음부터_분석하기.ipynb'])


if __name__ == '__main__':
    sys.exit(main())
