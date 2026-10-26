"""End-to-end CI check using synthetic CSV only. Do not print login tokens."""
from pathlib import Path
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import nbformat
from nbclient import NotebookClient

root=Path('/workspace')
sys.path.insert(0, str(root))
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
assert sum('image/png' in o.get('data', {}) for c in notebook.cells for o in c.get('outputs', [])) >= 5, 'Notebook must display its graphs inline'
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

# Exercise notebook 02's CSV-only route with two disjoint date ranges.
from ectlab.data import load_csv
frame=load_csv(input_csv)
base=root/'data/processed/ci_base.csv.gz'
extra=root/'data/processed/ci_additional.csv.gz'
frame[frame.date.le('2026-08-20')].to_csv(base,index=False)
frame[frame.date.gt('2026-08-20')].to_csv(extra,index=False)
os.environ['ECT_CSV_PATH']=str(base)
second=nbformat.read(root/'notebooks/02_추가데이터_변환과_재학습.ipynb',as_version=4)
cells=[c for c in second.cells if c.cell_type=='code']
assert 'MERGE_FILES' in cells[3].source and 'TRAINING_CSV' in cells[4].source
retrain=nbformat.v4.new_notebook(cells=[cells[0],cells[1],
    nbformat.v4.new_code_cell('NEW_CSV = Path('+repr(str(extra))+')'),
    nbformat.v4.new_code_cell(cells[3].source.replace('MERGE_FILES = False','MERGE_FILES = True')),
    nbformat.v4.new_code_cell(cells[4].source.replace('TRAINING_CSV = NEW_CSV','TRAINING_CSV = MERGED_CSV')),
    nbformat.v4.new_code_cell(f'assert len(new_df) == {len(frame)}\nassert len(packs) == 2\nassert len(ml_result["models"]) == 6')])
NotebookClient(retrain,timeout=600,kernel_name='movenex-ect',resources={'metadata':{'path':str(root/'notebooks')}}).execute()
nbformat.write(retrain,root/'notebooks/검증_CSV재학습.ipynb')
assert before==hashlib.sha256(input_csv.read_bytes()).hexdigest()
print('PASS: notebook 02 CSV merge and separate position retraining')

# New-data exploration is separate from supervised defect classification.
import io
import zipfile
from ectlab.exploration import explore_csv, download_href
import matplotlib.pyplot as plt
exploration=explore_csv(input_csv,root/'results','shaft',True)
assert set(exploration['counts']['위치'])=={1,2}
href=download_href(exploration['zip'],root)
request=urllib.request.Request('http://127.0.0.1:8888'+href,headers={'Authorization':'token '+info['token']})
with urllib.request.urlopen(request,timeout=20) as response:
    with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
        assert archive.testzip() is None
        assert 'PCA보고서.html' in archive.namelist()
for figure in exploration['figures'].values():plt.close(figure)
fifth=nbformat.read(root/'notebooks/05_새데이터_PCA_버튼실행.ipynb',as_version=4)
NotebookClient(fifth,timeout=120,kernel_name='movenex-ect',resources={'metadata':{'path':str(root/'notebooks')}}).execute()
assert any('application/vnd.jupyter.widget-view+json' in output.get('data',{}) for cell in fifth.cells for output in cell.get('outputs',[]))
assert before==hashlib.sha256(input_csv.read_bytes()).hexdigest()
print('PASS: PCA by position, authenticated ZIP download, notebook 05 widgets, unchanged source CSV')

# The company-facing Excel route must start from the mounted notebooks directory.
sixth=nbformat.read(root/'notebooks/06_261026_크랙_샤프트_실제자료검증.ipynb',as_version=4)
sixth.cells.append(nbformat.v4.new_code_cell('''
from scripts.make_delivery_demo import make_workbook
from ectlab.data import file_hash
sample=make_workbook(ROOT/'notebooks/새Excel_업로드/shaft/사용법_예제_샤프트.xlsx','shaft')
original_hash=file_hash(sample)
selector=화면['selectors']['shaft']
selector.options=[('선택 안 함',''),(sample.name,str(sample))]
selector.value=str(sample)
assert not 화면['run'].disabled
화면['run'].click()
result=화면['state']['result']
assert result is not None, 화면['status'].value
assert set(result['tables']['01_데이터수량']['위치'])=={1,2}
assert len(result['tables']['03_PCA요약'])==8
assert len(화면['choice'].options)==2 and 화면['choice'].value
assert result['zip'].is_file()
assert original_hash==file_hash(sample)
selector.value=''
assert 화면['state']['result'] is None
assert not 화면['choice'].options
assert 화면['run'].disabled
'''))
NotebookClient(sixth,timeout=240,kernel_name='movenex-ect',resources={'metadata':{'path':str(root/'notebooks')}}).execute()
assert any('application/vnd.jupyter.widget-view+json' in o.get('data',{}) for c in sixth.cells for o in c.get('outputs',[]))
print('PASS: notebook 06 Excel conversion, button callback, position PCA, automatic graph selection, ZIP, stale result clearing')

# Exercise Jupyter's authenticated HTTP chunk path above one websocket message.
import base64
from scripts.make_delivery_demo import make_workbook
sample=make_workbook(root/'notebooks/새Excel_업로드/사용법_예제_전송검증.xlsx','crack')
with zipfile.ZipFile(sample,'a',compression=zipfile.ZIP_STORED) as book:
    book.writestr('synthetic-padding.bin',b'0'*(2*1024*1024))
data=sample.read_bytes();step=1024*1024
target='notebooks/새Excel_업로드/crack/upload_'+'a'*32+'.part'
for offset in range(0,len(data),step):
    body={'type':'file','format':'base64','content':base64.b64encode(data[offset:offset+step]).decode(),
          'chunk':-1 if offset+step>=len(data) else offset//step+1}
    request=urllib.request.Request('http://127.0.0.1:8888/api/contents/'+urllib.parse.quote(target),method='PUT',
        headers={'Authorization':'token '+info['token'],'Content-Type':'application/json'},data=json.dumps(body).encode())
    with urllib.request.urlopen(request,timeout=30) as response:assert response.status in (200,201)
assert hashlib.sha256((root/target).read_bytes()).digest()==hashlib.sha256(data).digest()
print('PASS: multi-part authenticated HTTP upload, byte-for-byte workbook preservation')

# The unified entry must start in the same mounted directory as the older notebooks.
make_workbook(root/'notebooks/새Excel_업로드/shaft/전체실행_샤프트.xlsx','shaft')
make_workbook(root/'notebooks/새Excel_업로드/crack/전체실행_크랙.xlsx','crack')
manifest={'sources':[
    {'key':'C10A','path':str(input_csv),'train_end':'2026-08-20'},
    {'key':'C80B','path':str(input_csv),'train_end':'2026-08-20'},
    {'key':'crack','path':'notebooks/새Excel_업로드/crack/전체실행_크랙.xlsx'},
    {'key':'shaft','path':'notebooks/새Excel_업로드/shaft/전체실행_샤프트.xlsx'}]}
(root/'notebooks/전체실행_자료.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
research=nbformat.read(root/'notebooks/10_연구용_기존자료_일괄비교.ipynb',as_version=4)
research.cells.append(nbformat.v4.new_code_cell('''
assert len(통합화면['tabs'].children)==2
assert 통합화면['new']['day_start'].value==6
assert not 통합화면['new']['mode'].value
assert 통합화면['new']['run'].disabled
assert 통합화면['legacy']['pick'].options
통합화면['tabs'].selected_index=1
assert not 통합화면['batch']['run'].disabled
통합화면['batch']['run'].click()
batch_result=통합화면['batch']['state']['result']
assert batch_result is not None, 통합화면['batch']['status'].value
assert not batch_result['errors'], batch_result['errors']
assert len(batch_result['panels'])==8
assert len(batch_result['tables']['전체실행'])==4
assert batch_result['zip'].is_file()
assert not 통합화면['batch']['run'].disabled
'''))
NotebookClient(research,timeout=300,kernel_name='movenex-ect',resources={'metadata':{'path':str(root/'notebooks')}}).execute()
assert any('application/vnd.jupyter.widget-view+json' in o.get('data',{}) for c in research.cells for o in c.get('outputs',[]))
print('PASS: research notebook 10 unified tabs, legacy CSV selection, default 6am boundary, preserved old entry points')

# Company route: prepare/train once, change or upload tests, never refit on queries.
training=nbformat.read(root/'notebooks/09_통합테스트_샘플별결과.ipynb',as_version=4)
training.cells.append(nbformat.v4.new_code_cell('''
import joblib,json
from scripts.make_delivery_demo import make_workbook
sample=make_workbook(ROOT/'notebooks/새Excel_업로드/crack/학습검사_합성예제.xlsx','crack')
화면['family'].value='crack'
화면['train'].options=[('합성 예제',str(sample))]
화면['test'].options=[('합성 예제',str(sample))]
화면['train'].value=str(sample)
화면['end'].value='2026-10-24'
화면['prepare'].click()
assert 화면['state']['prepared'] is not None,화면['status'][0].value
화면['fit'].click()
bundle=화면['state']['bundle'];assert bundle is not None,화면['status'][1].value
fingerprint=joblib.hash(bundle['models'])
화면['test'].value=str(sample)
화면['predict'].click()
result=화면['state']['result'];assert result is not None,화면['status'][2].value
assert len(result['rows'])==100
assert result['record']['training_overlap_rows']==50
assert not result['record']['refitted'] and not result['record']['PCA_refitted']
assert result['zip'].is_file()
part=화면['upload_test'].folder/('upload_'+'c'*32+'.part');part.write_bytes(sample.read_bytes())
화면['upload_test'].receive({'new':json.dumps({'action':'finish','part':part.name,'name':'다음검사.xlsx'})})
assert not 화면['upload_test'].error,화면['upload_test'].error
assert 화면['state']['bundle'] is bundle,'Test upload must not invalidate trained model'
화면['predict'].click()
assert 화면['state']['result'] is not None,화면['status'][2].value
assert joblib.hash(bundle['models'])==fingerprint,'Queries may not refit model/PCA'
'''))
NotebookClient(training,timeout=300,kernel_name='movenex-ect',resources={'metadata':{'path':str(root/'notebooks')}}).execute()
assert any('application/vnd.jupyter.widget-view+json' in o.get('data',{}) for c in training.cells for o in c.get('outputs',[]))
print('PASS: new notebook 09 prepare/train/repeated batches, frozen PCA/models, new upload preserves model, overlap marked, report download')
