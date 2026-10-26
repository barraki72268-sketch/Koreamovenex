"""Company-facing three-step training and repeated batch inspection."""
from pathlib import Path
import json,html,shutil,uuid
import ipywidgets as w
from IPython.display import display,HTML,clear_output
from ectlab.chunk_upload import ChunkUpload
from ectlab.workflow import prepare_training,fit_prepared,predict_file,export_prediction,pca_figure
from ectlab.exploration import download_href


def available_files(root,profile,upload):
    root=Path(root);paths=[]
    manifest=root/'notebooks/전체실행_자료.json'
    if not manifest.is_file():manifest=root/'data/private/전체실행_자료.json'
    if manifest.is_file():
        for source in json.loads(manifest.read_text(encoding='utf-8')).get('sources',[]):
            if source['key'] in (('C10A','C80B') if profile=='c10' else (profile,)):
                p=Path(source['path']);p=p if p.is_absolute() else root/p
                if p.is_file():paths.append(p)
    if profile=='c10':
        paths.extend((root/'data/private').glob('*.csv.gz'))
        demo=root/'data/demo/연습용_ECT.csv.gz'
    else:demo=root/'data/demo/excel'/('사용법_예제_'+('크랙' if profile=='crack' else '샤프트')+'.xlsx')
    if demo.is_file():paths.append(demo)
    paths.extend(p for p in upload.glob('*') if p.is_file() and p.name.endswith(('.xlsx','.csv','.csv.gz')))
    return list({str(p):p for p in paths}.values())


def show_workflow_app(root):
    import matplotlib.pyplot as plt
    root=Path(root);upload=root/'notebooks/학습검사_업로드';upload.mkdir(parents=True,exist_ok=True)
    state={'prepared':None,'bundle':None,'result':None,'busy':False,'refreshing':False}
    wide=w.Layout(width='98%');labelstyle={'description_width':'150px'}
    family=w.Dropdown(options=[('C10 열처리 (기존 ECT)','c10'),('크랙','crack'),('샤프트 열처리','shaft')],description='자료 종류:',style=labelstyle,layout=wide)
    train=w.Dropdown(options=[('선택 안 함','')],description='학습 파일:',style=labelstyle,layout=wide)
    test=w.Dropdown(options=[('선택 안 함','')],description='검사 파일:',style=labelstyle,layout=wide)
    drop=w.Checkbox(value=False,description='학습 데이터의 100·32767 포화 채널 제외',layout=wide)
    end=w.Text(description='학습 종료일:',placeholder='빈칸이면 선택 파일 전체 / 예: 2026-10-20',style=labelstyle,layout=wide)
    boundary=w.BoundedIntText(value=6,min=0,max=23,description='크랙 검사일 시작:',style=labelstyle)
    model=w.Dropdown(options=[('Random Forest (기본)','RandomForest'),('XGBoost','XGBoost')],description='학습 모델:',style=labelstyle,layout=wide)
    low=w.BoundedFloatText(value=.1,min=0,max=1,step=.05,description='낮음 기준:')
    high=w.BoundedFloatText(value=.9,min=0,max=1,step=.05,description='높음 기준:')
    first=w.Button(description='① 데이터 읽기 · 전처리',button_style='primary',icon='file',layout=w.Layout(width='270px',height='44px'))
    second=w.Button(description='② 모델 학습',button_style='success',icon='cogs',disabled=True,layout=w.Layout(width='270px',height='44px'))
    third=w.Button(description='③ 새 샘플 배치 검사',button_style='primary',icon='play',disabled=True,layout=w.Layout(width='270px',height='44px'))
    s1=w.HTML();s2=w.HTML();s3=w.HTML();out1=w.Output();out2=w.Output();out3=w.Output();trainplot=w.Output();testplot=w.Output();sampletable=w.Output()
    learned=w.Dropdown(description='학습 PCA:',options=[],style=labelstyle,layout=wide)
    tested=w.Dropdown(description='검사 PCA:',options=[],style=labelstyle,layout=wide)
    kind=w.Dropdown(description='결과 보기:',options=['전체','불량 의심 · FN 후보','진성불량 의심','가성불량 후보','판정 보류','입력 확인 필요','정상 유사'])
    search=w.Text(description='샘플 검색:',placeholder='샘플ID / 날짜 / 판정 검색',layout=wide)
    page=w.BoundedIntText(value=1,min=1,max=1,description='페이지:')
    pasted=w.Textarea(description='벡터 CSV:',placeholder='선택 사항: 학습 후 내려받은 벡터 입력 양식과 같은 헤더/행을 붙여넣습니다.',layout=w.Layout(width='98%',height='110px'),style=labelstyle)
    modeldownload=w.HTML();resultdownload=w.HTML()

    def reset_test():
        state['result']=None;out3.clear_output();testplot.clear_output();sampletable.clear_output();tested.options=[];resultdownload.value='';s3.value=''
    def invalidate(*_):
        if state['busy'] or state['refreshing']:return
        state['prepared']=None;state['bundle']=None;second.disabled=True;third.disabled=True
        out1.clear_output();out2.clear_output();trainplot.clear_output();learned.options=[];modeldownload.value='';reset_test()
        s1.value='<p>①번으로 선택한 학습 데이터를 준비하세요.</p>';s2.value='<p>아직 학습하지 않았습니다.</p>'
    def refresh(new_train=None,new_test=None):
        paths=available_files(root,family.value,upload)
        options=[('선택 안 함','')]+[(p.name+(' (합성 연습용)' if 'demo' in p.parts else ''),str(p)) for p in paths]
        old=train.value;old_test=test.value;state['refreshing']=True
        try:
            train.options=options;test.options=options
            vals=[v for _,v in options]
            train.value=str(new_train) if new_train else old if old in vals else ''
            test.value=str(new_test) if new_test else old_test if old_test in vals else ''
        finally:state['refreshing']=False
        if new_train:invalidate()
        elif new_test:reset_test()
    upload_train=ChunkUpload(upload,lambda p:refresh(new_train=p),label='학습 파일 올리기',extensions=('.xlsx','.csv','.csv.gz'))
    upload_test=ChunkUpload(upload,lambda p:refresh(new_test=p),label='새 검사 파일 올리기',extensions=('.xlsx','.csv','.csv.gz'))
    def change_family(_):
        drop.value=family.value=='shaft';train.value='';test.value='';refresh();invalidate()
    family.observe(change_family,names='value')
    for control in (train,drop,end,boundary):control.observe(invalidate,names='value')
    def invalidate_fit(*_):
        if state['busy'] or state['refreshing']:return
        state['bundle']=None;second.disabled=state['prepared'] is None;third.disabled=True
        out2.clear_output();trainplot.clear_output();learned.options=[];modeldownload.value='';reset_test()
        s2.value='<p>모델·점수 기준이 바뀌었습니다. ②번을 다시 실행하세요.</p>'
    for control in (model,low,high):control.observe(invalidate_fit,names='value')
    def change_test(*_):
        if not state['busy'] and not state['refreshing']:reset_test()
    test.observe(change_test,names='value');pasted.observe(change_test,names='value')
    def busy(value):
        state['busy']=value
        for control in (family,train,test,drop,end,boundary,model,low,high,upload_train,upload_test):control.disabled=value
        first.disabled=value;second.disabled=value or state['prepared'] is None;third.disabled=value or state['bundle'] is None
    def plot_train(*_):
        with trainplot:
            clear_output(wait=True)
            if state['bundle'] is None or learned.value is None:return
            fig=pca_figure(state['bundle'],learned.value);display(fig);plt.close(fig)
    def plot_test(*_):
        with testplot:
            clear_output(wait=True)
            if state['bundle'] is None or state['result'] is None or tested.value is None:return
            rows=state['result']['rows'];key=tested.value
            part=rows[rows.line.eq(key[0])&rows['product'].eq(key[1])&rows.position.eq(key[2])]
            fig=pca_figure(state['bundle'],key,part);display(fig);plt.close(fig)
    def render_rows(*_):
        with sampletable:
            clear_output(wait=True)
            if state['result'] is None:return
            rows=state['result']['rows']
            if kind.value!='전체':rows=rows[rows.예측.eq(kind.value)]
            if search.value.strip():rows=rows[rows[['sample_id','date','예측']].astype(str).agg(' | '.join,axis=1).str.contains(search.value.strip(),regex=False,case=False)]
            page.max=max(1,(len(rows)+49)//50)
            display(HTML(f'<p>검색 {len(rows):,}행 · {page.value}/{page.max}페이지 · 파일에는 전체 행이 저장됩니다.</p>'))
            cols=['sample_id','line','product','position','equipment_label','점수','예측','설명','PC1','PC2','학습기준','검증구분']
            renamed={'sample_id':'샘플ID','line':'라인','product':'품번','position':'위치','equipment_label':'설비판정'}
            display(rows.iloc[(page.value-1)*50:page.value*50][cols].rename(columns=renamed))
    def prepare(_):
        invalidate()
        if not train.value:s1.value='<p>학습 파일을 고르거나 올려 주세요.</p>';return
        busy(True);s1.value='<p>선택한 학습 파일을 읽고 전처리하고 있습니다.</p>'
        try:
            with out1:
                p=prepare_training(train.value,family.value,root,drop.value,end.value.strip(),boundary.value,on_progress=lambda text:setattr(s1,'value','<p>'+html.escape(text)+'</p>'))
                state['prepared']=p;display(p['summary'])
            s1.value='<p style="color:#21724b">데이터 준비 완료. 아래 ② 모델 학습을 누르세요. 시험 데이터는 전처리 기준을 정하는 데 사용하지 않습니다.</p>'
        except Exception as exc:s1.value='<p>확인: '+html.escape(str(exc))+'</p>'
        finally:busy(False)
    def fit(_):
        if state['prepared'] is None:return
        state['bundle']=None;reset_test();out2.clear_output();busy(True);s2.value='<p>품번·위치별로 모델과 PCA를 학습하고 있습니다.</p>'
        try:
            bundle=fit_prepared(state['prepared'],root,model.value,low.value,high.value);state['bundle']=bundle
            with out2:display(bundle['summary'])
            learned.options=[(f'{k[0]} / {k[1]} / 위치 {k[2]}',k) for k in bundle['models']]
            if learned.options:learned.value=learned.options[0][1]
            plot_train()
            archive=Path(shutil.make_archive(str(bundle['folder'])+'_학습모델','zip',root_dir=bundle['folder']))
            modeldownload.value='<p><a href="'+html.escape(download_href(archive,root),quote=True)+'" download>학습 모델·벡터 입력 양식 ZIP 다운로드 ↓</a></p>'
            s2.value='<p style="color:#21724b">학습 완료. 이제 ③번에서 새 검사 파일을 바꿔 가며 반복 검사하세요. 다시 ①·②를 누를 필요가 없습니다.</p>'
        except Exception as exc:s2.value='<p>학습 확인 필요: '+html.escape(str(exc))+'</p>'
        finally:busy(False)
    def predict(_):
        bundle=state['bundle']
        if bundle is None:return
        if not test.value and not pasted.value.strip():s3.value='<p>검사할 새 파일을 고르거나 벡터 CSV를 붙여넣으세요.</p>';return
        reset_test();busy(True);s3.value='<p>학습한 모델과 고정 PCA로 배치 검사 중입니다. 새 입력으로 재학습하지 않습니다.</p>'
        try:
            path=Path(test.value) if test.value else None
            if pasted.value.strip():path=upload/('벡터배치_'+uuid.uuid4().hex[:8]+'.csv');path.write_text(pasted.value.strip()+'\n',encoding='utf-8-sig')
            result=export_prediction(bundle,predict_file(bundle,path,root));state['result']=result
            with out3:
                display(result['summary'].rename(columns={'line':'라인','product':'품번','position':'위치'}))
                display(HTML('<p>FN은 현장 확인이 필요한 후보입니다. 진성·가성은 기업 라벨 학습 또는 MASTER 유사 참조에 따른 후보 예측입니다. 정답 없는 새 샘플의 실제 정확도는 계산하지 않습니다.</p>'))
            rows=result['rows'];options=[]
            for k in bundle['models']:
                if (rows.line.eq(k[0])&rows['product'].eq(k[1])&rows.position.eq(k[2])).any():options.append((f'{k[0]} / {k[1]} / 위치 {k[2]}',k))
            tested.options=options
            if options:tested.value=options[0][1]
            plot_test();page.value=1;render_rows()
            resultdownload.value='<p><a href="'+html.escape(download_href(result['zip'],root),quote=True)+'" download>이번 배치의 결과·PCA·전체 샘플 CSV 다운로드 ↓</a></p>'
            overlaps=result['record']['training_overlap_rows']
            overlap_note=('학습 파일과 중복 '+str(overlaps)+'행은 독립 검증으로 보지 않습니다.') if overlaps else '학습 파일과 중복 0행. 신규 입력의 실제 정확도는 정답 확인 후 검증합니다.'
            s3.value='<p style="color:#21724b">'+str(len(rows))+'행 검사 완료. 같은 모델로 다음 파일도 ③번만 눌러 검사할 수 있습니다. '+overlap_note+'</p>'
        except Exception as exc:s3.value='<p>검사 확인 필요: '+html.escape(str(exc))+'</p>'
        finally:busy(False)
    first.on_click(prepare);second.on_click(fit);third.on_click(predict)
    learned.observe(plot_train,names='value');tested.observe(plot_test,names='value')
    for control in (kind,search,page):control.observe(render_rows,names='value')
    refresh();invalidate()
    advanced=w.Accordion(children=[w.VBox([end,boundary,w.HBox([low,high])])]);advanced.set_title(0,'필요할 때만: 학습 기간 · 검사일 · 점수 기준');advanced.selected_index=None
    vector=w.Accordion(children=[pasted]);vector.set_title(0,'선택 사항: 벡터 CSV를 붙여넣어 검사');vector.selected_index=None
    app=w.VBox([w.HTML('<div style="background:#17354b;color:white;padding:20px;border-radius:10px"><h2 style="color:white">학습하고, 새 샘플을 반복 검사하기</h2><p>① 학습 데이터 준비 → ② 모델 학습 → ③ 새 샘플 배치 검사 반복</p></div>'),
        w.HTML('<h3>① 학습 데이터 넣기</h3><p>자료 종류를 고른 뒤 학습 파일을 올리거나 서버 목록에서 선택하세요. 샤프트의 포화 채널 제외 기준은 학습 데이터에서만 정합니다.</p>'),family,upload_train,train,drop,advanced,first,s1,out1,
        w.HTML('<h3>② 모델 학습하기</h3><p>기업 진성 라벨이 있으면 라벨을, 없으면 MASTER와 OK를 참조해 학습합니다. 이 단계에서 전처리·모델·PCA가 고정됩니다. 아래 그림은 학습 분포이며 시험 정확도 그림이 아닙니다.</p>'),model,second,s2,out2,learned,trainplot,modeldownload,
        w.HTML('<h3>③ 새 샘플 넣고 검사하기</h3><p>한 행 또는 수천 행을 한 번에 검사합니다. 다음 파일도 이 단계만 반복하세요. 배경은 학습 분포, 색이 있는 점은 새 샘플 예측입니다. PCA는 다시 학습하지 않습니다.</p>'),upload_test,test,vector,third,s3,out3,tested,testplot,w.HBox([kind,page]),search,sampletable,resultdownload])
    display(app);display(upload_train.javascript('notebooks/학습검사_업로드'));display(upload_test.javascript('notebooks/학습검사_업로드'))
    return {'app':app,'state':state,'family':family,'train':train,'test':test,'prepare':first,'fit':second,'predict':third,'status':[s1,s2,s3],'model':model,'drop':drop,'end':end,'pasted':pasted,'learned':learned,'tested':tested,'upload_train':upload_train,'upload_test':upload_test}
