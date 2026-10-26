"""Excel selection and delivery analysis, without editing notebook code."""
from pathlib import Path
from datetime import datetime
import html
import io
import json
import traceback
import uuid
from zipfile import ZipFile

from ectlab.delivery_excel import convert_workbook
from ectlab.delivery import run_delivery


def save_upload(folder, name, content,extensions=('.xlsx',)):
    """Keep originals, validate names and reject oversized/invalid workbooks."""
    if Path(name).name != name or '\\' in name or not name.lower().endswith(tuple(extensions)):
        raise ValueError('허용 형식('+', '.join(extensions)+')의 파일을 선택해 주세요.')
    data = bytes(content)
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('100MB 이하의 파일을 사용해 주세요.')
    if name.lower().endswith('.xlsx'):
        try:
            with ZipFile(io.BytesIO(data)) as book:
                if 'xl/workbook.xml' not in book.namelist():raise ValueError('Excel 파일 내용을 확인해 주세요.')
                if sum(i.file_size for i in book.infolist()) > 1024**3:raise ValueError('압축 해제 후 파일이 너무 큽니다.')
        except Exception as exc:raise ValueError('읽을 수 있는 .xlsx 검사 파일인지 확인해 주세요.') from exc
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    suffix='.csv.gz' if name.lower().endswith('.csv.gz') else Path(name).suffix
    target = folder / (name[:-len(suffix)] + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8] + suffix)
    with target.open('xb') as stream:
        stream.write(data)
    return target


def analyze_files(files, root, with_ml=False, on_progress=None,crack_day_start_hour=6,output_root=None,use_crack_view=False):
    """Each run converts only the selected files into its own private folder."""
    files = {kind: Path(path) for kind, path in files.items() if path}
    if not files:
        raise ValueError('크랙 또는 샤프트 Excel을 하나 이상 선택해 주세요.')
    if any(kind not in ('crack', 'shaft') for kind in files):
        raise ValueError('분석 대상을 확인해 주세요.')
    root = Path(root)
    run = Path(output_root or root) / 'results' / ('Excel실행_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex[:8])
    inputs = run / '변환CSV'
    import hashlib,shutil
    from ectlab.data import file_hash
    import ectlab.delivery_excel as converter
    converter_hash=file_hash(Path(converter.__file__))
    for kind, path in files.items():
        source_hash=file_hash(path)
        key=hashlib.sha256((kind+source_hash+path.name+converter_hash).encode()).hexdigest()
        cache=root/'data/processed/새Excel_변환캐시'/key
        manifest=cache/'cache.json'
        reusable=False
        if manifest.is_file():
            metadata=json.loads(manifest.read_text(encoding='utf-8'))
            reusable=metadata.get('source_sha256')==source_hash and all((cache/name).is_file() and file_hash(cache/name)==digest for name,digest in metadata.get('files',{}).items()) and len(metadata.get('files',{}))==3
        if reusable:
            if on_progress:on_progress(('크랙' if kind=='crack' else '샤프트')+' · 같은 Excel의 검증된 변환 CSV를 읽습니다.')
            inputs.mkdir(parents=True,exist_ok=True)
            for name in metadata['files']:shutil.copyfile(cache/name,inputs/name)
        else:
            convert_workbook(kind, path, inputs, on_progress=on_progress)
            cache.mkdir(parents=True,exist_ok=True)
            hashes={}
            for suffix in ('_raw.csv.gz','_schema.json','_inventory.json'):
                name=kind+suffix
                shutil.copyfile(inputs/name,cache/name);hashes[name]=file_hash(cache/name)
            manifest.write_text(json.dumps({'source_sha256':source_hash,'converter_sha256':converter_hash,'files':hashes},ensure_ascii=False,indent=2),encoding='utf-8')
    result = run_delivery(inputs, run, pca_only=not with_ml,on_progress=on_progress,crack_day_start_hour=crack_day_start_hour)
    # Include converted CSVs and original-file hashes so the same run can be reproduced.
    import shutil
    shutil.copytree(inputs, result['folder'] / '변환CSV')
    (result['folder'] / '화면실행.json').write_text(json.dumps({
        'files': {k: v.name for k, v in files.items()},
        'mode': 'PCA + RF + XGBoost' if with_ml else 'PCA',
        'company_labels': '일반 NG 진성·가성 미확정',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    if use_crack_view and files.get('crack'):
        from ectlab.crack_view import attach_crack_view
        attach_crack_view(result,root,files['crack'],crack_day_start_hour)
    result['zip'] = Path(shutil.make_archive(str(result['folder']), 'zip', root_dir=result['folder']))
    return result


def show_delivery_app(root,crack_tabicl=False):
    import ipywidgets as w
    from ectlab.chunk_upload import ChunkUpload
    from IPython.display import display, HTML, Image, clear_output
    from ectlab.exploration import download_href

    root = Path(root)
    uploads = root / 'notebooks' / '새Excel_업로드'
    uploads.mkdir(parents=True, exist_ok=True)
    state = {'files': {}, 'result': None}
    width = w.Layout(width='100%')
    heading = w.HTML('''<div style="background:#17354b;color:white;padding:20px;border-radius:12px">
    <h2 style="color:white;margin:0 0 8px">새 Excel로 크랙·샤프트 분석하기</h2>
    <div>① 파일 선택　→　② 분석 시작　→　③ 위치별 그래프 확인　→　④ ZIP 저장</div></div>
    <p>Excel을 CSV로 바꿀 필요가 없습니다. 크랙·샤프트 중 하나만 올려도 됩니다.</p>''')
    selectors = {}
    uploaders = {}
    selected = {}
    cards = []
    status = w.HTML('<p>준비 중: 분석할 Excel 파일을 선택해 주세요.</p>')
    start = w.Button(description='② 분석 시작', button_style='primary', icon='play',
                     disabled=True, layout=w.Layout(width='220px', height='44px'))
    day_start=w.BoundedIntText(value=6,min=0,max=23,description='크랙 검사일 시작:',style={'description_width':'130px'})
    ml = w.Checkbox(value=False, description='RF·XGBoost 모델 비교도 함께 실행 (시간이 더 걸립니다)',
                    indent=False, layout=width)
    busy = w.IntProgress(value=0, min=0, max=3, description='진행:', layout=width)
    resultbox = w.Output()
    graphs = w.Output()
    details = w.Output()
    samples = w.Output()
    choice = w.Dropdown(options=[], description='볼 그래프:', layout=width,
                        style={'description_width': '85px'})
    download = w.HTML()
    log = w.Output()
    logbox = w.Accordion(children=[log])
    logbox.set_title(0, '실행 기록 · 오류가 있으면 이 내용을 담당자에게 전달하세요')
    logbox.selected_index = None

    def refresh(kind, new=None):
        label = '크랙' if kind == 'crack' else '샤프트'
        candidates = sorted((uploads / kind).glob('*.xlsx'))
        # Preloaded files are offered explicitly; no stale CSV is silently reused.
        prepared = root / 'notebooks' / '20261026_새자료_원본'
        candidates += sorted(prepared.glob('*크랙*.xlsx' if kind == 'crack' else '*샤프트*.xlsx'))
        selectors[kind].options = [('선택 안 함', '')] + [(p.name, str(p)) for p in candidates]
        if new:
            selectors[kind].value = str(new)

    def update_ready(*_):
        if state['result'] is not None:
            state['result'] = None
            choice.options = []
            download.value = ''
            for output in (resultbox, graphs, details, samples):
                output.clear_output()
        state['files'] = {kind: Path(box.value) for kind, box in selectors.items() if box.value}
        start.disabled = not bool(state['files']) or any(u.busy for u in uploaders.values())
        for kind, box in selectors.items():
            selected[kind].value = ('<p style="color:#20734b">선택됨: ' + html.escape(Path(box.value).name) + '</p>') if box.value else '<p style="color:#6b7280">선택하지 않음 · 이 검사는 건너뜁니다.</p>'
        status.value = '<p>준비 완료. 아래 파란색 <b>② 분석 시작</b>을 누르세요.</p>' if state['files'] else '<p>크랙 또는 샤프트 Excel을 선택하면 분석 버튼이 켜집니다.</p>'

        if any(u.busy for u in uploaders.values()):
            status.value = '<p>파일을 전송하고 있습니다. 업로드가 완료될 때까지 기다려 주세요.</p>'
        if any('사용법_예제' in p.name for p in state['files'].values()):
            status.value += '<p style="color:#966414">사용법 확인용 합성 예제가 선택되어 있습니다. 회사 성능 결과가 아닙니다.</p>'

    def receive(kind, path):
        refresh(kind, path)
        update_ready()

    for kind, label in [('crack', '크랙'), ('shaft', '샤프트')]:
        upload = ChunkUpload(uploads / kind, lambda path, kind=kind: receive(kind, path), label=label + ' Excel 선택', layout=w.Layout(width='100%'))
        selector = w.Dropdown(options=[('선택 안 함', '')], description='', layout=width)
        note = w.HTML()
        selectors[kind], uploaders[kind], selected[kind] = selector, upload, note
        upload.observe(update_ready, names='busy')
        upload.observe(lambda event: setattr(status, 'value', '<p style="color:#b42318">파일 확인: ' + html.escape(event['new']) + '</p>') if event['new'] else None, names='error')
        selector.observe(update_ready, names='value')
        cards.append(w.VBox([w.HTML('<h3>① ' + label + ' 파일</h3>'), upload,
                              w.HTML('<small>이미 서버에 올린 파일은 아래 목록에서 고르세요.</small>'), selector, note],
                             layout=w.Layout(width='48%', min_width='270px', padding='12px', border='1px solid #d5dfe8')))
    for kind in selectors:
        refresh(kind)
    update_ready()

    def show_graph(*_):
        with graphs:
            clear_output(wait=True)
            if state['result'] and choice.value:
                display(Image(filename=str(state['result']['folder'] / choice.value)))

    choice.observe(show_graph, names='value')

    def execute(_):
        start.disabled = True
        controls = list(uploaders.values()) + list(selectors.values()) + [ml,day_start]
        for control in controls:
            control.disabled = True
        download.value = ''
        choice.options = []
        state['result'] = None
        for output in (resultbox, graphs, details, samples, log):
            output.clear_output()
        busy.value = 1
        busy.bar_style = 'info'
        status.value = '<p style="background:#eaf3fc;padding:12px">분석 중입니다. Excel을 읽고 품번·위치별로 계산합니다. 완료될 때까지 기다려 주세요.</p>'
        try:
            def progress(message):
                if message.startswith('PCA'):busy.value=2
                status.value='<p style="background:#eaf3fc;padding:12px">'+html.escape(message)+'<br>계산이 끝나면 결과가 아래에 나타납니다.</p>'
            with log:
                result = analyze_files(state['files'], root, ml.value, on_progress=progress,crack_day_start_hour=day_start.value,use_crack_view=crack_tabicl)
            state['result'] = result
            busy.value = 2
            with resultbox:
                display(HTML('<h3>③ 분석 결과</h3><p>보라색 별 = MASTER · 회색 점 = 설비 OK · 주황색 점 = 일반 NG(진성·가성 미확정)</p>'))
                table = result['tables']['01_데이터수량']
                display(table[['검사', '라인', '품번', '위치', '측정행', 'MASTER기준시료', '일반NG', '최대값0']])
                if result.get('tabicl_view'):
                    display(HTML('<p>'+html.escape(result['tabicl_view']['message'])+'</p>'))
                    if result['tabicl_view'].get('summary_file'):display(Image(filename=result['tabicl_view']['summary_file']))
                display(HTML('<p>아래 목록에서 품번·위치를 골라 보세요. 샤프트는 원본·100값 제외·X/Y만 사용·100 및 32767 제외 그림을 함께 보여줍니다.</p>'))
            pcas = sorted((p.name for p in result['folder'].glob('*_PCA.png')),key=lambda name:(not name.startswith('TabICLv2_'),name))
            choice.options = [(p.removesuffix('_PCA.png').replace('_', ' / '), p) for p in pcas]
            if pcas:
                choice.value = pcas[0]
            show_graph()
            def refresh_download():
                import shutil
                result['zip']=Path(shutil.make_archive(str(result['folder']),'zip',root_dir=result['folder']))
                link=download_href(result['zip'],root)
                download.value='<h3>④ 결과 저장</h3><a href="'+html.escape(link,quote=True)+'&v='+datetime.now().strftime('%H%M%S')+'" download>추가 그림 포함 결과 ZIP 다운로드 ↓</a>'
            result['refresh_download']=refresh_download
            with samples:
                from ectlab.sample_browser import show_sample_browser
                show_sample_browser(result)
            with details:
                display(HTML('<h4>MASTER와 제외값 확인</h4><p>크랙은 화면에서 지정한 검사일 경계 이후 첫 행을 MASTER 후보로 봅니다. 경계 이전 새벽 측정은 전일에 속합니다. 샤프트는 검사번호의 NG마스터 표시를 우선합니다. 최대값 0은 판정 불명으로 제외합니다.</p>'))
                display(result['tables']['02_MASTER가정_확인표'])
                if ml.value:
                    display(HTML('<h4>RF·XGBoost 비교</h4><p>이전 날짜로 학습하고 마지막 날짜를 확인합니다. 점수는 실제 불량 확률이 아닙니다. 학습할 날짜·MASTER가 부족한 구간은 생략합니다.</p>'))
                    display(result['tables']['04_ML_마지막날짜시험'])
                for note in result['notes']:
                    display(HTML('<p>' + html.escape(note) + '</p>'))
            href = download_href(result['zip'], root)
            download.value = '<div style="background:#eef8f1;padding:18px;border-radius:10px"><h3>④ 결과 저장</h3><a style="font-size:18px" href="' + html.escape(href, quote=True) + '" download>결과 ZIP 다운로드 ↓</a><p>다운로드 → 압축 풀기 → 검증보고서.html 열기. 표·그래프·변환 CSV가 함께 들어 있습니다.</p></div>'
            busy.value = 3
            busy.bar_style = 'success'
            status.value = '<p style="color:#20734b"><b>분석 완료.</b> 아래에서 그래프를 확인하고 ZIP을 저장하세요.</p>'
        except Exception as exc:
            busy.bar_style = 'danger'
            status.value = '<p style="color:#b42318">실행을 멈췄습니다: ' + html.escape(str(exc)) + '<br>크랙·샤프트 파일을 서로 바꿔 선택했는지, 이번 검사 Excel 형식인지 확인해 주세요. 이전 결과로 대신 표시하지 않습니다.</p>'
            with log:
                traceback.print_exc()
        finally:
            for control in controls:
                control.disabled = False
            start.disabled = not bool(state['files']) or any(u.busy for u in uploaders.values())

    start.on_click(execute)
    detailbox = w.Accordion(children=[details])
    detailbox.set_title(0, '자세히 보기 · MASTER 확인표 / 모델 결과 / 확인 사항')
    detailbox.selected_index = None
    app = w.VBox([heading, w.HBox(cards, layout=w.Layout(width="100%", flex_flow="row wrap")),
                  w.HTML('<h3>② 분석 방법</h3><p>처음에는 체크하지 않고 PCA부터 확인하세요. 샤프트 100값 제외 비교는 자동으로 포함됩니다.</p>'),
                  day_start, w.HTML('<p>기본 오전 6시. 6시 이전은 전일 검사일에 속합니다. 첫 행이 OK인 경우 확정 진성 라벨로 학습하지 않습니다.</p>'),ml, start, busy, status, resultbox, choice, graphs, samples, download, detailbox,
                  w.HTML('<p style="color:#6b7280">PCA는 분포를 보는 그림입니다. 일반 NG의 진성·가성 정답이 없어 자동 확정 판정으로 사용하지 않습니다.</p>'), logbox], layout=w.Layout(width='100%', max_width='1150px'))
    display(app)
    for kind, uploader in uploaders.items():
        display(uploader.javascript('notebooks/새Excel_업로드/' + kind))
    return dict(state=state, uploaders=uploaders, selectors=selectors, run=start, mode=ml,
                choice=choice, status=status, day_start=day_start, app=app)
