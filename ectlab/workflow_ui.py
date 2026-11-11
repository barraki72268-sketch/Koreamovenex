"""Company-facing three-step training and repeated batch inspection."""
from pathlib import Path
import json,html,shutil,uuid
import ipywidgets as w
from IPython.display import display,HTML,clear_output
from ectlab.chunk_upload import ChunkUpload
from ectlab.workflow import prepare_training,fit_prepared,predict_file,export_prediction,pca_figure
from ectlab.exploration import download_href
from ectlab.company_results import ng_summary,detail_table,styled_details,view_mask


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
    paths.extend(p for p in upload.glob('*') if p.is_file() and p.name.lower().endswith(('.xlsx','.csv','.csv.gz')))
    return list({str(p):p for p in paths}.values())


def show_workflow_app(root):
    import matplotlib.pyplot as plt
    root=Path(root);upload=root/'notebooks/학습검사_업로드';upload.mkdir(parents=True,exist_ok=True)
    state={'prepared':None,'bundle':None,'result':None,'busy':False,'refreshing':False}
    wide=w.Layout(width='98%');labelstyle={'description_width':'150px'}
    family=w.Dropdown(options=[('외륜 열처리','c10'),('외륜 크랙','crack'),('샤프트 열처리','shaft')],description='분석 대상:',style=labelstyle,layout=wide)
    train=w.Dropdown(options=[('선택 안 함','')],description='학습 파일:',style=labelstyle,layout=wide)
    test=w.Dropdown(options=[('선택 안 함','')],description='검사 파일:',style=labelstyle,layout=wide)
    drop=w.Checkbox(value=False,description='샤프트 포화 주파수 제외 (권장)',layout=wide)
    drop.layout.display='none'
    end=w.Text(description='학습 종료일:',placeholder='빈칸이면 선택 파일 전체 / 예: 2026-10-20',style=labelstyle,layout=wide)
    boundary=w.BoundedIntText(value=6,min=0,max=23,description='크랙 검사일 시작:',style=labelstyle)
    model=w.Dropdown(options=[('Random Forest (기본)','RandomForest'),('XGBoost','XGBoost'),('TabICLv2 (선택 설치 · CPU 비교)','TabICLv2')],description='학습 모델:',style=labelstyle,layout=wide)
    modelnote=w.HTML()
    tabicl_all_ok=w.Checkbox(value=False,description='TabICLv2로 OK도 전수 평가 (매우 느림)',layout=wide)
    low=w.BoundedFloatText(value=90,min=0,max=100,step=1,description='가성 후보 (%)',style=labelstyle)
    high=w.BoundedFloatText(value=90,min=0,max=100,step=1,description='진성 의심 (%)',style=labelstyle)
    first=w.Button(description='① 데이터 읽기 · 전처리',button_style='primary',icon='file',layout=w.Layout(width='270px',height='44px'))
    second=w.Button(description='② 모델 학습',button_style='success',icon='cogs',disabled=True,layout=w.Layout(width='270px',height='44px'))
    third=w.Button(description='③ 새 샘플 배치 검사',button_style='primary',icon='play',disabled=True,layout=w.Layout(width='270px',height='44px'))
    s1=w.HTML();s2=w.HTML();s3=w.HTML();out1=w.Output();out2=w.Output();out3=w.Output();trainplot=w.Output();testplot=w.Output();sampletable=w.Output()
    learned=w.Dropdown(description='학습 PCA:',options=[],style=labelstyle,layout=wide)
    tested=w.Dropdown(description='라인 / 품번 / 위치:',options=[],style=labelstyle,layout=wide)
    inspection_date=w.Dropdown(description='검사일자:',options=[('전체 일자',None)],style=labelstyle,layout=wide)
    kind=w.Dropdown(description='결과 보기:',options=['전체','불량 의심 · FN 후보','진성불량 의심','가성불량 후보','판정 보류','입력 확인 필요','정상 유사'])
    search=w.Text(description='샘플 검색:',placeholder='샘플ID / 날짜 / 판정 검색',layout=wide)
    page=w.BoundedIntText(value=1,min=1,max=1,description='페이지:')
    pasted=w.Textarea(description='벡터 CSV:',placeholder='선택 사항: 학습 후 내려받은 벡터 입력 양식과 같은 헤더/행을 붙여넣습니다.',layout=w.Layout(width='98%',height='110px'),style=labelstyle)
    modeldownload=w.HTML();resultdownload=w.HTML()
    view=w.Dropdown(options=[('전체 (100 포함)','full'),('0 ~ 5',5),('0 ~ 10',10),('0 ~ 20',20),('0 ~ 99',99),('전체 (100 제외)','all')],value='full',description='검출값 조회 범위:',style=labelstyle,layout=wide)
    kind.options=['NG 전체 (MASTER 포함)','전체','MASTER','진성불량 의심','가성불량 후보','기준자료 (최대값 0)','검사기 합격','FN 후보','보류','입력 확인 필요']
    kind.value='NG 전체 (MASTER 포함)'
    files_refresh=w.Button(description='파일 목록 새로고침',icon='refresh')
    sampletable.layout.overflow='auto'
    for panel in (out1,out2,out3):panel.layout.overflow='auto'

    def reset_test():
        state['result']=None;out3.clear_output();testplot.clear_output();sampletable.clear_output();tested.options=[];inspection_date.options=[('전체 일자',None)];resultdownload.value='';s3.value=''
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
        if new_train:change_train()
        elif new_test:reset_test()
    upload_train=ChunkUpload(upload,lambda p:refresh(new_train=p),label='분석할 Excel·CSV 선택',extensions=('.xlsx','.csv','.csv.gz'))
    upload_test=ChunkUpload(upload,lambda p:refresh(new_test=p),label='새 검사 파일 올리기',extensions=('.xlsx','.csv','.csv.gz'))
    def change_family(_):
        drop.layout.display='' if family.value=='shaft' else 'none'
        drop.value=family.value=='shaft';view.value='full';train.value='';test.value='';refresh();invalidate()
    def change_train(*_):
        if state['busy'] or state['refreshing']:return
        test.value=train.value
        pasted.value=''
        invalidate()
        if train.value:s1.value='<p>선택됨 · '+html.escape(Path(train.value).name)+' · ① 데이터 읽기 · 전처리를 누르세요.</p>'
    family.observe(change_family,names='value')
    files_refresh.on_click(lambda _:refresh())
    train.observe(change_train,names='value')
    for control in (drop,end,boundary):control.observe(invalidate,names='value')
    def invalidate_fit(*_):
        if state['busy'] or state['refreshing']:return
        state['bundle']=None;second.disabled=state['prepared'] is None;third.disabled=True
        out2.clear_output();trainplot.clear_output();learned.options=[];modeldownload.value='';reset_test()
        s2.value='<p>모델·점수 기준이 바뀌었습니다. ②번을 다시 실행하세요.</p>'
    for control in (model,low,high,tabicl_all_ok):control.observe(invalidate_fit,names='value')
    def update_modelnote(*_):
        tabicl_all_ok.layout.display='' if model.value=='TabICLv2' else 'none'
        modelnote.value=('<p style="background:#fff3dc;padding:12px">TabICLv2: 01번에서 추가 설치가 필요합니다. 공식 사전학습 가중치는 고정하고 기준자료를 등록합니다. CPU 비교에서는 구간별 OK 기준자료 최대 256행, 검사 NG 전체(유효·학습 가능 구간)와 OK 최대 128행을 평가합니다. 나머지 OK는 설비 합격으로만 표시하며 AI 미평가입니다. PCA는 원측정값 공간입니다. RF·XGBoost보다 오래 걸릴 수 있습니다.</p>' if model.value=='TabICLv2' else '')
        if model.value=='TabICLv2' and tabicl_all_ok.value:
            modelnote.value=modelnote.value.replace('OK 최대 128행','OK 전수').replace('나머지 OK는 설비 합격으로만 표시하며 AI 미평가입니다.','OK 전수 평가를 선택했습니다. 데이터가 많으면 매우 오래 걸립니다.')
    model.observe(update_modelnote,names='value');update_modelnote()
    tabicl_all_ok.observe(update_modelnote,names='value')
    def change_test(*_):
        if not state['busy'] and not state['refreshing']:reset_test()
    test.observe(change_test,names='value');pasted.observe(change_test,names='value')
    def busy(value):
        state['busy']=value
        for control in (family,train,test,drop,end,boundary,model,low,high,upload_train,upload_test,tabicl_all_ok):control.disabled=value
        first.disabled=value;second.disabled=value or state['prepared'] is None;third.disabled=value or state['bundle'] is None
    def plot_train(*_):
        with trainplot:
            clear_output(wait=True)
            if state['bundle'] is None or learned.value is None:return
            fig=pca_figure(state['bundle'],learned.value,view_limit=view.value);display(fig);plt.close(fig)
    def plot_test(*_):
        with testplot:
            clear_output(wait=True)
            if state['bundle'] is None or state['result'] is None:return
            key=tested.value
            if key is None:
                display(HTML('<p>PCA를 보려면 한 라인·품번·위치를 선택하세요.</p>'))
                return
            if key not in state['bundle']['models']:
                display(HTML('<p>이 라인·품번·위치에는 학습된 모델이 없습니다. 원본 정보는 상세 표에서 확인할 수 있습니다.</p>'))
                return
            fig=pca_figure(state['bundle'],key,selected_rows(),view_limit=view.value,inspection_date=inspection_date.value)
            display(fig);plt.close(fig)
    def selected_rows(filter_date=True):
        rows=state['result']['rows']
        if tested.value is not None:
            line,product,position=tested.value
            rows=rows[rows.line.eq(line)&rows['product'].eq(product)&rows.position.eq(position)]
        if filter_date and inspection_date.value is not None:
            rows=rows[rows.calendar_date.astype(str).eq(inspection_date.value)]
        return rows
    def render_summary(*_):
        with out3:
            clear_output(wait=True)
            if state['result'] is None:return
            rows=selected_rows()
            if not rows.empty:display(ng_summary(state['bundle'],rows,view.value))
            display(HTML('<p>총 NG = 원본 설비 NG 행 수 (MASTER 포함). MASTER + 가성 추정 + 진성 추정 + 보류 + 기준자료0 + 입력확인의 합계를 검증합니다. 조회 범위 밖 자료도 총 NG에서 빼지 않습니다.</p><p>진성·가성은 AI 추정이며 유사점수는 실제 불량 확률이 아닙니다. 최대값 0은 판정 미확정 기준자료입니다.</p>'))
    def render_rows(*_):
        with sampletable:
            clear_output(wait=True)
            if state['result'] is None:return
            rows=selected_rows()
            if kind.value=='NG 전체 (MASTER 포함)':rows=rows[rows.equipment_label.eq('NG')]
            elif kind.value!='전체':rows=rows[rows['판정'].eq(kind.value)]
            before=len(rows);rows=rows[view_mask(rows,view.value)]
            if search.value.strip():rows=rows[rows[['sample_id','date','예측']].astype(str).agg(' | '.join,axis=1).str.contains(search.value.strip(),regex=False,case=False)]
            page.max=max(1,(len(rows)+49)//50)
            display(HTML(f'<p>표시 {len(rows):,}행 / 범위 적용 전 {before:,}행 · {page.value}/{page.max}페이지 · 전체 행과 원본 연결 정보는 CSV에 저장됩니다. 붉은 글자는 진성 의심 또는 FN 후보입니다.</p>'))
            detail=detail_table(rows.iloc[(page.value-1)*50:page.value*50])
            cols=['검사일자','시간','검사수량','라인','품번','판정','설비판정(원본)','위치','최대검출값','MAX FRQ','Part_No','가성유사점수(%)','진성유사점수(%)','원본시트','원본행']
            display(styled_details(detail[cols]))
    def prepare(_):
        invalidate()
        if not train.value:s1.value='<p>학습 파일을 고르거나 올려 주세요.</p>';return
        busy(True);s1.value='<p>선택한 학습 파일을 읽고 전처리하고 있습니다.</p>'
        try:
            with out1:
                p=prepare_training(train.value,family.value,root,drop.value,end.value.strip(),boundary.value,on_progress=lambda text:setattr(s1,'value','<p>'+html.escape(text)+'</p>'))
                state['prepared']=p;display(p['summary'])
            if not test.value:test.value=train.value
            s1.value='<p style="color:#21724b">데이터 준비 완료. 아래 ② 모델 학습을 누르세요. 시험 데이터는 전처리 기준을 정하는 데 사용하지 않습니다.</p>'
        except Exception as exc:s1.value='<p>확인: '+html.escape(str(exc))+'</p>'
        finally:busy(False)
    def fit(_):
        if state['prepared'] is None:return
        state['bundle']=None;reset_test();out2.clear_output();busy(True);s2.value='<p>품번·위치별로 모델 기준자료와 PCA를 준비하고 있습니다.</p>'
        try:
            bundle=fit_prepared(state['prepared'],root,model.value,(100-low.value)/100,high.value/100,tabicl_all_ok=tabicl_all_ok.value);state['bundle']=bundle
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
        reset_test();busy(True);s3.value=f'<p>{html.escape(bundle["model_name"])} 모델로 배치 검사 중입니다.</p>'
        try:
            path=Path(test.value) if test.value else None
            if pasted.value.strip():path=upload/('벡터배치_'+uuid.uuid4().hex[:8]+'.csv');path.write_text(pasted.value.strip()+'\n',encoding='utf-8-sig')
            result=export_prediction(bundle,predict_file(bundle,path,root,on_progress=lambda text:setattr(s3,'value','<p>'+html.escape(text)+'</p>')));state['result']=result
            rows=result['rows'];options=[]
            for k in rows[['line','product','position']].drop_duplicates().itertuples(index=False,name=None):
                options.append((f'{k[0]} / {k[1]} / 위치 {k[2]}',k))
            tested.options=options+[('전체 라인·품번·위치 (표만)',None)]
            if options:tested.value=next((k for _,k in options if k in bundle['models']),options[0][1])
            resultdownload.value='<p><a href="'+html.escape(download_href(result['zip'],root),quote=True)+'" download>이번 배치의 결과·PCA·전체 샘플 CSV 다운로드 ↓</a></p>'
            overlaps=result['record']['training_overlap_rows']
            overlap_note=('학습 파일과 중복 '+str(overlaps)+'행은 독립 검증으로 보지 않습니다.') if overlaps else '학습 파일과 중복 0행. 신규 입력의 실제 정확도는 정답 확인 후 검증합니다.'
            s3.value=f'<p style="color:#21724b">적용 모델 {html.escape(bundle["model_name"])} · {len(rows):,}행 검사 완료. 같은 모델로 다음 파일도 ③번만 눌러 검사할 수 있습니다. {overlap_note}</p>'
        except Exception as exc:s3.value='<p>검사 확인 필요: '+html.escape(str(exc))+'</p>'
        finally:busy(False)
    first.on_click(prepare);second.on_click(fit);third.on_click(predict)
    learned.observe(plot_train,names='value')
    def result_view_changed(*_):
        page.value=1
        plot_test();render_summary();render_rows()
    def group_changed(*_):
        if state['result'] is None:return
        dates=sorted(set(selected_rows(filter_date=False).calendar_date.dropna().astype(str))-{'','NaT','nan'})
        inspection_date.options=[('전체 일자',None)]+[(date,date) for date in dates]
        target=dates[-1] if dates else None
        if inspection_date.value==target:result_view_changed()
        else:inspection_date.value=target
    tested.observe(group_changed,names='value')
    inspection_date.observe(result_view_changed,names='value')
    for control in (kind,search,page):control.observe(render_rows,names='value')
    def view_changed(*_):
        plot_train();plot_test();render_summary();render_rows()
    view.observe(view_changed,names='value')
    refresh();invalidate()
    advanced=w.Accordion(children=[w.VBox([end,boundary])]);advanced.set_title(0,'필요할 때만: 학습 기간 · 크랙 검사일 기준');advanced.selected_index=None
    vector=w.Accordion(children=[pasted]);vector.set_title(0,'선택 사항: 벡터 CSV를 붙여넣어 검사');vector.selected_index=None
    app=w.VBox([w.HTML('<div style="background:#17354b;color:white;padding:20px;border-radius:10px"><h2 style="color:white">학습하고, 새 샘플을 반복 검사하기</h2><p>① 학습 데이터 준비 → ② 모델 학습 → ③ 새 샘플 배치 검사 반복</p><small>회사 피드백 반영판 · 2026-11-09</small></div>'),
        w.HTML('<h3>① 학습 데이터 넣기</h3><p>자료 종류를 고른 뒤 학습 파일을 올리거나 파일 목록에서 선택하세요. Windows에서는 이 PC의 파일 선택 창을 사용합니다. 창이 열리지 않으면 파일 전체 경로를 붙여넣어 추가하세요.</p>'),family,upload_train,train,files_refresh,drop,advanced,first,s1,out1,
        w.HTML('<h3>② 모델 학습하기</h3><p>③에서는 여기서 선택해 준비한 모델을 사용합니다. 유사점수 기준은 이번 실행의 모든 품번에 적용됩니다. 품번별 기준을 적용하려면 해당 품번 자료를 따로 실행하세요. 기준을 바꾸면 ②를 다시 누르세요.</p>'),model,modelnote,tabicl_all_ok,w.HBox([low,high],layout=w.Layout(flex_flow='row wrap')),second,s2,out2,learned,trainplot,modeldownload,
        w.HTML('<h3>③ NG 판정 결과 및 상세 현황</h3><p>현재 파일은 ③번만 눌러 결과를 확인합니다. 다음 파일은 새로 선택해 ③번만 반복할 수 있습니다. 보라 별: MASTER / 초록 원: 최대값0 / 파랑 원: 검사기 합격 / 빨강: 진성 의심 / 주황: 가성 후보.</p>'),upload_test,test,vector,third,s3,
        w.HTML('<p>라인·품번·위치와 검사일자를 고르면 그래프와 표가 함께 바뀝니다. 검출값 범위는 표시할 행을 좁힙니다. 샤프트 MASTER는 범위 밖이어도 표시하며, ZIP에는 전체 검사 결과를 저장합니다.</p>'),tested,inspection_date,view,out3,testplot,w.HBox([kind,page]),search,sampletable,resultdownload])
    display(app);display(upload_train.javascript('notebooks/학습검사_업로드'));display(upload_test.javascript('notebooks/학습검사_업로드'))
    return {'app':app,'state':state,'family':family,'train':train,'test':test,'prepare':first,'fit':second,'predict':third,'status':[s1,s2,s3],'model':model,'modelnote':modelnote,'tabicl_all_ok':tabicl_all_ok,'drop':drop,'end':end,'pasted':pasted,'learned':learned,'tested':tested,'upload_train':upload_train,'upload_test':upload_test,'view':view,'kind':kind,'group':tested,'inspection_date':inspection_date,'low':low,'high':high}
