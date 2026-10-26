"""One notebook entry point; existing methods and per-product models stay separate."""
from pathlib import Path
from datetime import datetime
import os,shutil,json,html
import numpy as np
import pandas as pd


def run_legacy(path,root,with_ml=True,train_end='2026-08-20',calibration_end='2026-10-07'):
    from ectlab.data import load_csv
    from ectlab.pipeline import Settings,prepare,distance_analysis,train_models,export_run,DECISIONS
    from ectlab.plots import pca_plot,comparison_plot
    from ectlab.sample_reports import write_delivery_samples
    df=load_csv(path);settings=Settings(train_end=train_end,calibration_end=calibration_end)
    packs,counts=prepare(df,settings);distance=distance_analysis(packs)
    ml=train_models(packs) if with_ml else {'predictions':pd.DataFrame(),'models':{},'notes':[],'importance':pd.DataFrame()}
    figures={'기존_PCA':pca_plot(packs)}
    pieces=[p for p in (distance['predictions'],ml['predictions']) if not p.empty]
    all_predictions=pd.concat(pieces,ignore_index=True) if pieces else pd.DataFrame()
    if not all_predictions.empty:figures['기존_판정비교']=comparison_plot(all_predictions)
    folder=export_run(Path(root)/'results',path,settings,packs,distance,ml,figures)
    import matplotlib.pyplot as plt
    for fig in figures.values():plt.close(fig)
    df.to_csv(folder/'기존입력.csv.gz',index=False)
    entries=[]
    for position,pack in packs.items():
        r=pack['rows'];features=[f['column'] for f in pack['features']]
        g=pd.DataFrame({'c0':r.date,'calendar_date':r.date,'c1':r.time,'c2':r.counter,'c5':r.equipment_label,'c7':r.max_value,'source_sheet':r.source_sheet,'source_row':r.source_row})
        master=r.field_label.eq('NG_master').to_numpy();labels=np.where(master,'MASTER 기준시료 (기업 표시)',np.where(r.equipment_label.eq('OK'),'설비 OK','일반 NG / 기업라벨은 상세 확인'))
        X=pd.DataFrame(pack['X'],columns=features)
        entry=write_delivery_samples(folder,'기존자료_위치'+str(position),'기존 X_Y',g,X,np.ones(len(features),bool),r.eligible.to_numpy(),master,labels,'legacy',str(r.line.iloc[0]),str(r['product'].iloc[0]),position)
        table=pd.read_csv(folder/entry['file']);table['원본ID']=r.id.to_numpy();table['현장판정']=r.field_label.map({'field_true':'기업 진성','field_false':'기업 가성','NG_master':'기업 MASTER','measurement_error':'측정 오류'}).fillna('미확정').to_numpy()
        table['제외사유']=r.exclusion_reason.to_numpy()
        for model,short in [('RandomForest','RF'),('XGBoost','XGBoost')]:
            for experiment,suffix in [('master_proxy',''),('company_direct','_기업직접학습')]:
                p=ml['predictions']
                p=p[p.position.eq(position)&p.model.eq(model)&p.experiment.eq(experiment)].set_index('id') if not p.empty else pd.DataFrame()
                table[short+suffix+'점수']=r.id.map(p.positive_score).to_numpy() if not p.empty else np.nan
                table[short+suffix+'결과']=r.id.map(p.decision.map(DECISIONS)).fillna('미계산').to_numpy() if not p.empty else '미계산'
                table[short+suffix+'학습포함']=r.id.map(p.in_training).fillna(False).to_numpy() if not p.empty else False
        p=distance['predictions'];p=p[p.position.eq(position)].set_index('id') if not p.empty else pd.DataFrame()
        table['기존거리판정']=r.id.map(p.decision.map(DECISIONS)).fillna('미계산').to_numpy() if not p.empty else '미계산'
        d=distance['details']
        if not d.empty:
            d=d[d.position.eq(position)&d.scope.eq('full')&d.method.eq('robust_l2')].set_index('id')
            table['기존MASTER거리비율']=r.id.map(d.master_ratio).to_numpy()
            table['기존OK거리비율']=r.id.map(d.OK_ratio).to_numpy()
        table.to_csv(folder/entry['file'],index=False,compression={'method':'gzip','compresslevel':3});entries.append(entry)
    (folder/'샘플결과_목록.json').write_text(json.dumps({'entries':entries,'policy':{'legacy':'기존 prepare / distance_analysis / train_models와 날짜 설정을 그대로 사용. 현장라벨 보존. 샘플 탐색거리는 전체 파일의 별도 참고 거리이며 기존 거리판정 임계값과 구분.'}},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'folder':folder,'zip':Path(shutil.make_archive(str(folder),'zip',root_dir=folder)),'sample_index':entries,'tables':{'기존수량':counts}}


def show_legacy_app(root):
    import ipywidgets as w
    from IPython.display import display,HTML,Image,clear_output
    from ectlab.chunk_upload import ChunkUpload
    from ectlab.exploration import download_href
    from ectlab.sample_browser import show_sample_browser
    root=Path(root);uploads=root/'notebooks/기존CSV_업로드';uploads.mkdir(parents=True,exist_ok=True)
    pick=w.Dropdown(description='기존 CSV:',layout=w.Layout(width='98%'))
    status=w.HTML();out=w.Output();downloads=w.HTML()
    train=w.Text(value='2026-08-20',description='학습 종료일:');cal=w.Text(value='2026-10-07',description='기준 종료일:')
    ml=w.Checkbox(value=True,description='기존 RF·XGBoost 비교 포함')
    run=w.Button(description='기존 자료 분석 시작',button_style='primary',icon='play')
    state={'result':None}

    def refresh(new=None):
        candidates=[]
        for directory in (root/'data/private',uploads):
            if directory.is_dir():candidates.extend(p for p in directory.iterdir() if p.is_file() and p.name.endswith(('.csv','.csv.gz')))
        configured=os.environ.get('ECT_CSV_PATH')
        if configured and Path(configured).is_file():candidates.append(Path(configured))
        demo=root/'data/demo/연습용_ECT.csv.gz'
        if demo.is_file():candidates.append(demo)
        unique={str(p):p for p in candidates}
        pick.options=[('선택 안 함','')]+[(p.name+(' (합성 연습용)' if p==demo else ''),str(p)) for p in unique.values()]
        if new:pick.value=str(new)

    upload=ChunkUpload(uploads,lambda p:refresh(p),label='기존 CSV 선택',extensions=('.csv','.csv.gz'))
    refresh()
    refresh_button=w.Button(description='파일 목록 새로고침',icon='refresh');refresh_button.on_click(lambda _:refresh())
    def execute(_):
        if not pick.value:status.value='<p>서버에 있는 CSV를 고르거나 PC에서 올려 주세요.</p>';return
        run.disabled=True;out.clear_output();downloads.value='';state['result']=None
        status.value='<p>기존 거리 기준과 모델을 위치별로 계산하고 있습니다.</p>'
        with out:
            try:
                result=run_legacy(pick.value,root,ml.value,train.value,cal.value);state['result']=result
                display(result['tables']['기존수량'])
                display(Image(filename=str(result['folder']/'기존_PCA.png')))
                def refresh_download():
                    result['zip']=Path(shutil.make_archive(str(result['folder']),'zip',root_dir=result['folder']))
                    href=download_href(result['zip'],root)
                    downloads.value='<p><a href="'+html.escape(href,quote=True)+'&v='+datetime.now().strftime('%H%M%S')+'" download>기존 자료 결과 ZIP 다운로드 ↓</a></p>'
                result['refresh_download']=refresh_download
                show_sample_browser(result);refresh_download()
                status.value='<p>완료. 기존 판정과 현장라벨, MASTER 거리를 샘플별로 확인할 수 있습니다.</p>'
            except Exception as exc:status.value='<p>확인: '+html.escape(str(exc))+'</p>'
            finally:run.disabled=False
    def choose(_):
        if 'C80B' in Path(pick.value or '').name:
            train.value='2026-10-06';cal.value='2026-10-07'
        elif 'C10A' in Path(pick.value or '').name:
            train.value='2026-08-20';cal.value='2026-10-07'
    pick.observe(choose,names='value')
    run.on_click(execute)
    app=w.VBox([w.HTML('<h2>기존 자료: 기업 라벨이 연결된 ECT 표준 CSV</h2><p>기존 모델과 보완 기준을 그대로 사용합니다. 위치 1·2는 별도 학습합니다. 새 크랙·샤프트 Excel은 옆 탭을 사용하세요.</p>'),upload,refresh_button,pick,w.HBox([train,cal]),ml,run,status,out,downloads])
    display(app);display(upload.javascript('notebooks/기존CSV_업로드'))
    return dict(app=app,pick=pick,run=run,state=state,status=status)


def show_unified_app(root):
    import ipywidgets as w
    from IPython.display import display
    from ectlab.delivery_ui import show_delivery_app
    from ectlab.batch import show_batch_app
    batch=show_batch_app(root)
    new=w.Output();legacy=w.Output()
    with new:new_app=show_delivery_app(root,crack_tabicl=True)
    with legacy:legacy_app=show_legacy_app(root)
    tabs=w.Tab(children=[new,legacy]);tabs.set_title(0,'새 크랙·샤프트 Excel');tabs.set_title(1,'기존 자료 CSV')
    advanced=w.Accordion(children=[tabs]);advanced.set_title(0,'필요할 때만: 파일 하나씩 실행 / 새 파일 업로드');advanced.selected_index=None
    display(advanced)
    disabled_before=[]
    def lock_controls(locked):
        if locked:
            disabled_before.clear()
            def visit(widget):
                if 'disabled' in widget.traits():disabled_before.append((widget,widget.disabled));widget.disabled=True
                for child in getattr(widget,'children',()):visit(child)
            visit(tabs)
        else:
            for widget,previous in disabled_before:widget.disabled=previous
            disabled_before.clear()
    batch['state']['lock_controls']=lock_controls
    return {'batch':batch,'tabs':tabs,'new':new_app,'legacy':legacy_app,'advanced':advanced}
