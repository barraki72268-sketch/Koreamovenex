"""One click runs the pinned legacy, crack and shaft inputs; no model pooling."""
from pathlib import Path
from datetime import datetime
import html,json,shutil,uuid,gc,os
import pandas as pd
import numpy as np

KEYS=('C10A','C80B','crack','shaft')


def read_batch_sources(root):
    root=Path(root)
    manifest=root/'data/private/전체실행_자료.json'
    if not manifest.is_file():manifest=root/'notebooks/전체실행_자료.json'
    if not manifest.is_file():
        raise ValueError('전체 실행용 자료 목록이 아직 없습니다. 담당자가 data/private/전체실행_자료.json 또는 notebooks/전체실행_자료.json에 실제 파일 4개를 등록하면 버튼이 준비됩니다. 개별 실행은 아래에서 사용할 수 있습니다.')
    sources=json.loads(manifest.read_text(encoding='utf-8'))['sources']
    if len(sources)!=4 or {s['key'] for s in sources}!=set(KEYS):
        raise ValueError('전체 실행 목록에는 C10A, C80B, crack, shaft를 각각 한 번씩 등록해 주세요.')
    by_key={s['key']:s for s in sources}
    jobs=[]
    for key in KEYS:
        job=dict(by_key[key]);p=Path(job['path'])
        if not p.is_absolute():p=root/p
        if not p.is_file():raise ValueError(key+' 파일이 없습니다: '+p.name)
        if key in ('crack','shaft') and p.suffix.lower()!='.xlsx':raise ValueError(key+'에는 원본 .xlsx를 등록해 주세요.')
        if key in ('C10A','C80B') and not p.name.lower().endswith(('.csv','.csv.gz')):raise ValueError(key+'에는 표준 CSV를 등록해 주세요.')
        job['path']=p;job.setdefault('label',{'crack':'새 크랙','shaft':'새 샤프트'}.get(key,'기존 '+key));jobs.append(job)
    return jobs


def gallery_entries(entries):
    """One consistently chosen display condition per product and position."""
    groups={}
    for e in entries:groups.setdefault((e['profile'],e['line'],e['product'],e['position']),[]).append(e)
    selected=[]
    for group in groups.values():
        preferred=next((e for e in group if e['condition']=='100·32767 채널 전체 제외'),group[0])
        # Do not swap to a more attractive plot when this condition cannot be computed.
        selected.append(preferred)
    return selected


def make_gallery_panel(folder,entry,target):
    from ectlab.sample_browser import tsne_figure
    from ectlab.pipeline import evenly_sample
    from ectlab.plots import style
    import matplotlib.pyplot as plt
    style();rows=pd.read_csv(Path(folder)/entry['file'],low_memory=False)
    valid=rows.분석가능&rows.PC1.notna()&rows.PC2.notna()
    if valid.sum()<5:raise ValueError('유효 입력이 있는 샘플이 5행 미만이어서 PCA·t-SNE 비교를 만들 수 없습니다.')
    tsne,coordinates=tsne_figure(folder,rows,entry)
    try:
        fig,axes=plt.subplots(1,2,figsize=(14,5.4))
        kinds=np.where(rows.MASTER여부,'MASTER',np.where(rows.설비판정.eq('OK'),'설비 OK','일반 NG (미확정)'))
        tk=np.where(coordinates.MASTER여부,'MASTER',np.where(coordinates.설비판정.eq('OK'),'설비 OK','일반 NG (미확정)'))
        for name,color,marker in [('설비 OK','#8C9DAF','o'),('일반 NG (미확정)','#DF952F','o'),('MASTER','#7951B0','*')]:
            ids=np.flatnonzero(valid&(kinds==name));shown=evenly_sample(ids,2000)
            axes[0].scatter(rows.iloc[shown].PC1,rows.iloc[shown].PC2,c=color,marker=marker,s=110 if name=='MASTER' else 14,alpha=.8,label=f'{name} ({len(ids)}행)')
            ix=tk==name
            axes[1].scatter(coordinates.loc[ix,'TSNE1'],coordinates.loc[ix,'TSNE2'],c=color,marker=marker,s=110 if name=='MASTER' else 14,alpha=.8,label=f'{name} ({int(ix.sum())}행)')
        ratios=entry.get('ratios',[])
        axes[0].set(title=f'PCA · 2축 설명 비율 {sum(ratios[:2]):.1%}\n전체 유효 {int(valid.sum()):,}행 · 종류별 최대 2,000점 표시',xlabel='PC1',ylabel='PC2')
        axes[1].set(title=f't-SNE · 표시 {len(coordinates):,} / 전체 {len(rows):,}행\nOK 최대 1,000행 + 나머지 최대 1,000행 · seed 42',xlabel='t-SNE 1',ylabel='t-SNE 2')
        for ax in axes:ax.legend(fontsize=8);ax.grid(alpha=.15)
        title=f'{entry["line"]} / {entry["product"]} / 위치 {entry["position"]} / {entry["condition"]}'
        fig.suptitle(title+'\n같은 입력 조건의 분포 비교 · 일반 NG의 진성/가성 정확도가 아님',fontsize=11)
        fig.tight_layout();fig.savefig(target,dpi=125,bbox_inches='tight');plt.close(fig)
        coordinates.to_csv(Path(target).with_suffix('.csv.gz'),index=False,compression='gzip')
    finally:plt.close(tsne)
    return {'title':title,'file':str(target),'rows':len(rows),'valid_rows':int(valid.sum()),'tsne_rows':len(coordinates)}


def run_batch(root,jobs=None,with_ml=True,on_progress=None,on_panel=None):
    from ectlab.unified import run_legacy
    from ectlab.delivery_ui import analyze_files
    from ectlab.data import file_hash
    from threadpoolctl import threadpool_limits
    root=Path(root);jobs=read_batch_sources(root) if jobs is None else jobs
    if len(jobs)!=4 or {j['key'] for j in jobs}!=set(KEYS):raise ValueError('기존 2개와 새 자료 2개가 모두 필요합니다.')
    jobs=sorted(jobs,key=lambda j:KEYS.index(j['key']))
    for job in jobs:
        if not Path(job['path']).is_file():raise ValueError('실행 전 파일 확인: '+job['key'])
    folder=root/'results'/('전체자료_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8])
    # Explicit extended paths work without changing Windows registry settings.
    if os.name=='nt' and not str(folder).startswith('\\\\?\\'):
        folder=Path('\\\\?\\'+str(folder.resolve()))
    folder.mkdir(parents=True);(folder/'gallery').mkdir()
    summaries=[];all_entries=[];panels=[];errors=[];sources=[]
    def progress(message):
        if on_progress:on_progress(message)
    with threadpool_limits(limits=2):
        for number,job in enumerate(jobs,1):
            key=job['key'];label=job.get('label',key);path=Path(job['path'])
            source_hash=file_hash(path);sources.append({'key':key,'label':label,'file':path.name,'sha256_before':source_hash})
            progress(f'{number}/4 · {label} 분석 중. PCA와 RF·XGBoost 다음에 위치별 t-SNE를 계산합니다.')
            try:
                jobroot=folder/'datasets'/key
                if key in ('C10A','C80B'):
                    result=run_legacy(path,jobroot,with_ml,job.get('train_end','2026-10-06' if key=='C80B' else '2026-08-20'),job.get('calibration_end','2026-10-07'))
                else:
                    result=analyze_files({key:path},root,with_ml,on_progress=lambda m:progress(f'{number}/4 · {label} · {m}'),crack_day_start_hour=6,output_root=jobroot)
                relative=result['folder'].relative_to(folder)
                for entry in result['sample_index']:
                    merged=dict(entry,dataset=label,source_folder=relative.as_posix(),file=(relative/entry['file']).as_posix());all_entries.append(merged)
                selected=gallery_entries(result['sample_index']);completed=0
                for index,entry in enumerate(selected,1):
                    progress(f'{number}/4 · {label} · PCA·t-SNE {index}/{len(selected)} · {entry["line"]} 위치 {entry["position"]}')
                    target=folder/'gallery'/f'{key}_{index:02d}_PCA_tSNE.png'
                    try:
                        panel=make_gallery_panel(result['folder'],entry,target);panel['dataset']=label;panels.append(panel);completed+=1
                        if on_panel:on_panel(panel)
                    except ValueError as exc:
                        errors.append({'dataset':label,'position':entry['position'],'product':entry['product'],'stage':'시각화','reason':str(exc)})
                        if on_panel:on_panel({'dataset':label,'title':entry['product']+' / 위치 '+str(entry['position']),'error':str(exc)})
                summaries.append({'자료':label,'상태':'완료' if completed==len(selected) else '일부 시각화 확인 필요','위치별그림':completed,'전체조건수':len(result['sample_index']),'샘플수':sum(e['rows'] for e in selected),'결과폴더':relative.as_posix()})
                # The outer archive already contains the child files.
                if result['zip'].is_file():result['zip'].unlink()
                del result;gc.collect()
            except Exception as exc:
                errors.append({'dataset':label,'stage':'분석','reason':str(exc)})
                summaries.append({'자료':label,'상태':'실패','오류':str(exc)})
                if on_panel:on_panel({'dataset':label,'title':label,'error':str(exc)})
            sources[-1]['sha256_after']=file_hash(path)
            if sources[-1]['sha256_after']!=source_hash:raise RuntimeError('원본 파일이 실행 도중 변경되었습니다: '+label)
    table=pd.DataFrame(summaries);table.to_csv(folder/'전체자료_실행요약.csv',index=False,encoding='utf-8-sig')
    policy={'targets':'C10A, C80B, crack, shaft 순차 실행. 품번·위치별 별도 모델 유지. 기존 라벨과 학습 기간 보존.',
            'display':'품번·위치별 PCA/t-SNE 자동 표시. 샤프트는 100·32767 채널 전체 제외 조건을 일관되게 표시. 다른 PCA 조건도 하위 보고서에 저장. 계산 불가 조건은 이유를 기록하며 유리한 그림으로 바꾸지 않음.',
            'tsne':'같은 입력으로 OK 최대 1000 + 나머지 최대 1000행, seed42, 750회. 확정 진성·가성 성능이 아님. 원본 행은 전체 샘플 CSV에 보존.'}
    (folder/'샘플결과_목록.json').write_text(json.dumps({'entries':all_entries,'policy':policy},ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'전체실행_기록.json').write_text(json.dumps({'sources':sources,'with_ml':with_ml,'crack_day_start_hour':6,'errors':errors,'policy':policy},ensure_ascii=False,indent=2),encoding='utf-8')
    body='<html lang="ko"><meta charset="utf-8"><title>전체 자료 분석</title><style>body{font:16px/1.7 sans-serif;margin:24px}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:7px}</style><h1>기존·신규 전체 자료 분석</h1>'+table.to_html(index=False)
    body+='<p>'+html.escape(policy['display'])+'</p><p>'+html.escape(policy['tsne'])+'</p>'
    for panel in panels:body+='<h2>'+html.escape(panel['dataset']+' / '+panel['title'])+'</h2><img src="gallery/'+Path(panel['file']).name+'">'
    for error in errors:body+='<p>확인 필요: '+html.escape(str(error))+'</p>'
    (folder/'전체자료_보고서.html').write_text(body,encoding='utf-8')
    progress('전체 자료 결과를 ZIP으로 저장하고 있습니다.')
    archive=Path(shutil.make_archive(str(folder),'zip',root_dir=folder))
    return {'folder':folder,'zip':archive,'sample_index':all_entries,'panels':panels,'errors':errors,'tables':{'전체실행':table}}


def show_batch_app(root):
    import ipywidgets as w
    from IPython.display import display,HTML,Image,clear_output
    from ectlab.sample_browser import show_sample_browser
    from ectlab.exploration import download_href
    root=Path(root);state={'result':None}
    run=w.Button(description='전체 자료 한 번에 분석',icon='play',button_style='success',layout=w.Layout(width='320px',height='52px'))
    status=w.HTML();inventory=w.HTML();output=w.Output();download=w.HTML()
    try:
        jobs=read_batch_sources(root)
        inventory.value='<ol>'+''.join('<li>'+html.escape(j['label']+' — '+j['path'].name)+'</li>' for j in jobs)+'</ol>'
        status.value='<p>파일 선택 없이 위 자료 4개를 모두 실행합니다. 버튼은 한 번만 누르세요. 전체 분석에는 수 분이 걸릴 수 있습니다.</p>'
    except Exception as exc:run.disabled=True;status.value='<p>'+html.escape(str(exc))+'</p>'
    def execute(_):
        run.disabled=True;state['result']=None;download.value='';output.clear_output()
        lock=state.get('lock_controls',lambda value:None);lock(True)
        def progress(message):status.value='<p style="background:#eaf3fc;padding:14px">'+html.escape(message)+'</p>'
        def panel_ready(panel):
            with output:
                display(HTML('<h3>'+html.escape(panel['dataset']+' / '+panel['title'])+'</h3>'))
                if panel.get('error'):display(HTML('<p>확인 필요: '+html.escape(panel['error'])+'</p>'))
                else:display(Image(filename=panel['file']))
        try:
            result=run_batch(root,on_progress=progress,on_panel=panel_ready);state['result']=result
            with output:
                display(HTML('<h3>전체 실행 요약</h3>'));display(result['tables']['전체실행'])
                if result['sample_index']:
                    detail=w.Output()
                    with detail:show_sample_browser(result)
                    box=w.Accordion(children=[detail]);box.set_title(0,'전체 샘플의 모델 결과·MASTER 거리 확인');display(box)
            def refresh_download():
                result['zip']=Path(shutil.make_archive(str(result['folder']),'zip',root_dir=result['folder']))
                download.value='<p><a style="font-size:20px" href="'+html.escape(download_href(result['zip'],root),quote=True)+'&v='+datetime.now().strftime('%H%M%S')+'" download>전체 결과 ZIP 다운로드 ↓</a></p>'
            result['refresh_download']=refresh_download;refresh_download()
            status.value='<p style="padding:14px;background:#eef8f1">'+('일부 확인 사항이 있습니다. 아래 요약과 보고서의 사유를 확인해 주세요.' if result['errors'] else '전체 분석 완료. 기존 자료부터 새 자료까지 PCA·t-SNE를 아래로 내려가며 확인하세요.')+'</p>'
        except Exception as exc:status.value='<p>실행 확인 필요: '+html.escape(str(exc))+'</p>'
        finally:run.disabled=False;lock(False)
    run.on_click(execute)
    app=w.VBox([w.HTML('<div style="background:#17354b;color:white;padding:20px;border-radius:10px"><h2 style="color:white">기존 자료 + 새 자료, 한 번에 확인하기</h2><p>한 번 실행 → 기존 C10A → 기존 C80B → 새 크랙 → 새 샤프트 → PCA·t-SNE 자동 표시 → ZIP 저장</p></div>'),inventory,run,status,output,download])
    display(app)
    return {'app':app,'run':run,'state':state,'status':status}
