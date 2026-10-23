"""End-to-end CI check using synthetic CSV only. Do not print login tokens."""
from pathlib import Path
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import nbformat
from nbclient import NotebookClient

root=Path('/workspace')
input_csv=Path(os.environ['ECT_CSV_PATH'])
before=hashlib.sha256(input_csv.read_bytes()).hexdigest()
try:
    with input_csv.open('ab'):
        pass
except (PermissionError, OSError):
    pass
else:
    raise AssertionError('Input CSV mount must be read-only')

runtime=next(Path(os.environ['JUPYTER_RUNTIME_DIR']).glob('jpserver-*.json'))
info=json.loads(runtime.read_text())
assert info['token'], 'Token authentication must be enabled'
url='http://127.0.0.1:8888/api/contents/notebooks/' + urllib.parse.quote('01_처음부터_분석하기.ipynb')
try:
    urllib.request.urlopen(url, timeout=10)
except urllib.error.HTTPError as error:
    assert error.code in (401,403), error.code
else:
    raise AssertionError('Notebook API accepted an unauthenticated request')
request=urllib.request.Request(url,headers={'Authorization':'token '+info['token']})
with urllib.request.urlopen(request, timeout=10) as response:
    assert json.load(response)['type']=='notebook'

notebook=nbformat.read(root/'notebooks/01_처음부터_분석하기.ipynb',as_version=4)
assert all(not c.get('outputs') for c in notebook.cells if c.cell_type=='code')
NotebookClient(notebook, timeout=600, kernel_name='movenex-ect', resources={'metadata':{'path':str(root/'notebooks')}}).execute()
assert any('실제 회사 데이터입니다' in str(c.get('outputs', [])) for c in notebook.cells)
nbformat.write(notebook, root/'notebooks/검증_실행기록.ipynb')
reports=list((root/'results').glob('*/결과보고서.html'))
assert reports
folder=max(reports,key=lambda p:p.stat().st_mtime).parent
assert len(list(folder.glob('*.png'))) >= 5
assert len(list(folder.glob('*.csv'))) >= 5
assert list((folder/'models').glob('p1_*.joblib'))
assert list((folder/'models').glob('p2_*.joblib'))
assert before==hashlib.sha256(input_csv.read_bytes()).hexdigest()
for relative in ('results/'+folder.name+'/결과보고서.html', 'notebooks/검증_실행기록.ipynb'):
    request=urllib.request.Request('http://127.0.0.1:8888/api/contents/'+urllib.parse.quote(relative),headers={'Authorization':'token '+info['token']})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status==200
print('PASS: authenticated Jupyter, read-only mounted CSV, all notebook cells, Korean plots, CSV/HTML/model exports, persistent files')
