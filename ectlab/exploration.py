"""Exploratory PCA for unverified NG labels. Never predicts true/false defects."""
from pathlib import Path
import datetime
import json
import shutil
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.decomposition import PCA
from sklearn.preprocessing import RobustScaler
from .data import load_csv, feature_schema, file_hash
from .plots import style
import matplotlib.pyplot as plt

def download_href(archive, root):
    """Stage a small downloadable copy within Jupyter's static root.

    Permanent reports stay on NAS. Do not broaden StaticFileHandler's symlink policy.
    """
    import os
    from urllib.parse import quote
    root=Path(root);archive=Path(archive)
    cache=root/'downloads'/str(os.getuid() if hasattr(os,'getuid') else 'local')
    cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=cache/archive.name
    if target.resolve().parent!=cache.resolve():raise ValueError('다운로드 경로를 확인하세요.')
    shutil.copyfile(archive,target)
    prefix=os.environ.get('JUPYTERHUB_SERVICE_PREFIX','/').rstrip('/')
    return prefix+'/files/'+quote(target.relative_to(root).as_posix())+'?download=1'

def explore_csv(path, output_root, profile='crack', remove_100=True):
    style()
    if profile not in ('crack','shaft'):
        raise ValueError('분석 대상은 크랙 또는 샤프트입니다.')
    path=Path(path); df=load_csv(path)
    points=[]; counts=[]; master_rows=[]; exclusions=[]; figures={}; notes=[]; removed=[]
    for position, group in df.groupby('position',sort=True):
        rows=group.sort_values(['date','source_sheet','source_row'],kind='stable').reset_index(drop=True)
        features=feature_schema(rows); names=[v['column'] for v in features]
        X=rows[names].to_numpy(float)
        first=rows.groupby('date',sort=False).head(1).index
        master=np.zeros(len(rows),bool)
        master[first]=rows.loc[first,'equipment_label'].eq('NG').to_numpy()
        if not master[first].all():
            notes.append(f'위치 {position}: 일자별 첫 측정행 중 OK가 있어 해당 행은 마스터로 지정하지 않았습니다. 최초 검사 건을 확인하세요.')
        for i in first:
            master_rows.append({'위치':position,'날짜':rows.loc[i,'date'],'원본시트':rows.loc[i,'source_sheet'],
                '원본행':int(rows.loc[i,'source_row']),'설비판정':rows.loc[i,'equipment_label'],'마스터지정':bool(master[i])})
        labels=np.where(master,'첫 측정 MASTER NG',np.where(rows.equipment_label.eq('OK'),'설비 OK (참고)','일반 NG (진성·가성 미확정)'))
        invalid=rows.yellow_any.to_numpy()|rows.max_value.eq(0).to_numpy()|rows.field_label.isin(['measurement_error','color_conflict','mapping_label_conflict','unmatched','color_on_OK_unverified']).to_numpy()
        hundred=np.isclose(X,100.0,rtol=0,atol=1e-9)
        keep=~hundred[~invalid].any(axis=0) if (~invalid).any() else np.ones(X.shape[1],bool)
        for j in np.flatnonzero(~keep):
            f=features[j]
            removed.append({'위치':position,'블록':f['block'],'주파수':f['frequency'],'축':f['axis'],'컬럼':f['column'],'100값_행수':int(hundred[:,j].sum())})
        variants=[('원본 X/Y',np.ones(X.shape[1],bool))]
        if profile=='shaft' and remove_100:variants.append(('100이 있는 X/Y축 제외',keep))
        fig,axes=plt.subplots(1,len(variants),figsize=(7*len(variants),5.7),squeeze=False)
        for ax,(variant,selected) in zip(axes[0],variants):
            valid=(~invalid)&np.isfinite(X[:,selected]).all(axis=1)
            row_count=int(valid.sum()); dim=int(selected.sum()); retained_master=int((valid&master).sum())
            counts.append({'위치':position,'조건':variant,'전체행':len(rows),'사용행':row_count,'제외행':int((~valid).sum()),'X/Y축':dim,
                '마스터지정행':int(master.sum()),'사용가능마스터':retained_master,'100이_있는행':int(hundred.any(axis=1).sum())})
            for i in np.flatnonzero(~valid):
                exclusions.append({'위치':position,'조건':variant,'날짜':rows.loc[i,'date'],'원본시트':rows.loc[i,'source_sheet'],'원본행':int(rows.loc[i,'source_row']),
                    '사유':'0·노랑 또는 명시적 오류/라벨 연결 문제' if invalid[i] else '선택한 X/Y축에 결측·무한값'})
            if dim<2 or row_count<3:
                message='PCA 불가: 사용 가능한 X/Y축 2개·측정행 3개 이상 필요'
                ax.text(.5,.5,message,ha='center',va='center',wrap=True,transform=ax.transAxes)
                ax.set_title(f'위치 {position} / {variant}')
                notes.append(f'위치 {position} / {variant}: {message}')
                continue
            raw=X[valid][:,selected]; label=labels[valid]; active=rows.loc[valid].reset_index(drop=True)
            ok=label=='설비 OK (참고)'
            reference=raw[ok] if ok.sum()>=3 else raw
            scale=RobustScaler().fit(reference); Z=scale.transform(raw)
            if not np.isfinite(Z).all() or np.linalg.norm(Z-Z.mean(0))==0:
                ax.text(.5,.5,'변동이 없어 PCA를 계산할 수 없습니다.',ha='center',transform=ax.transAxes)
                continue
            # Both PCA axes use this file's full valid data; this is visual exploration only.
            model=PCA(n_components=2,svd_solver='full'); P=model.fit_transform(Z)
            reference_master=Z[label=='첫 측정 MASTER NG']
            dm=np.min(cdist(Z,reference_master),axis=1)/np.sqrt(dim) if len(reference_master) else np.full(len(Z),np.nan)
            do=np.linalg.norm(Z-np.median(Z[ok],axis=0),axis=1)/np.sqrt(dim) if ok.any() else np.full(len(Z),np.nan)
            result=active[['id','date','source_sheet','source_row','position','equipment_label']].copy()
            result['표시구분']=label;result['조건']=variant;result['PC1']=P[:,0];result['PC2']=P[:,1]
            result['마스터거리_참고']=dm;result['OK중앙값거리_참고']=do
            points.append(result)
            for name,color,marker,size in [('설비 OK (참고)','#8B9DAF','o',16),('일반 NG (진성·가성 미확정)','#DA9B30','o',25),('첫 측정 MASTER NG','#7951B0','*',140)]:
                idx=np.flatnonzero(label==name)
                shown=idx[np.unique(np.linspace(0,len(idx)-1,min(len(idx),1500),dtype=int))] if len(idx) else idx
                ax.scatter(P[shown,0],P[shown,1],c=color,marker=marker,s=size,alpha=.6 if marker=='o' else 1,label=f'{name} ({len(idx):,}행)')
            ratio=model.explained_variance_ratio_.sum()*100
            ax.set(title=f'위치 {position} / {variant}\nX/Y축 {dim}개 · PCA 2축 설명 비율 {ratio:.1f}%',xlabel='PC1',ylabel='PC2')
            ax.legend(fontsize=8);ax.grid(alpha=.15)
            if not retained_master:notes.append(f'위치 {position} / {variant}: 사용 가능한 마스터가 없어 마스터 거리는 계산하지 않았습니다.')
        fig.suptitle('탐색용 PCA: 일반 NG의 진성·가성은 확정하지 않습니다',fontsize=13)
        fig.tight_layout();figures[f'위치{position}_PCA']=fig
    output=Path(output_root)/('PCA_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    output.mkdir(parents=True,exist_ok=False)
    table=pd.DataFrame(counts);masters=pd.DataFrame(master_rows)
    coords=pd.concat(points,ignore_index=True) if points else pd.DataFrame()
    table.to_csv(output/'01_위치별_조건비교.csv',index=False,encoding='utf-8-sig')
    masters.to_csv(output/'02_마스터지정_확인.csv',index=False,encoding='utf-8-sig')
    coords.to_csv(output/'03_PCA좌표와_참고거리.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(removed,columns=['위치','블록','주파수','축','컬럼','100값_행수']).to_csv(output/'04_100값으로_제외한축.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(exclusions,columns=['위치','조건','날짜','원본시트','원본행','사유']).to_csv(output/'05_제외행과_사유.csv',index=False,encoding='utf-8-sig')
    for name,fig in figures.items():fig.savefig(output/(name+'.png'),dpi=150,bbox_inches='tight')
    policy={'input_file':path.name,'input_sha256':file_hash(path),'profile':profile,'remove_100_axes':bool(remove_100),
        'master_rule':'위치·날짜별 원본 시트·행 순서의 첫 측정행이 NG인 경우 마스터로 지정. 최초 검사 건 확인 필요.',
        'saturation_rule':'명시적 오류·0·노랑을 제외한 행에서 +100이 하나라도 있는 X/Y축을 모든 행에서 제외. -100이나 최대측정값 열은 이 규칙의 대상이 아님.',
        'labels':'일반 NG의 진성/가성 라벨을 학습하거나 추정하지 않음. CSV에 기존 진성/가성 표시가 있어도 탐색 그림에서는 일반 NG로 표시.',
        'fit':'RobustScaler는 설비 OK가 3행 이상이면 OK로 적합. PCA는 현재 파일의 전체 유효행으로 적합. 새 데이터의 독립 검증 성능이 아님.',
        'limits':'PCA의 시각적 분리와 마스터 거리는 진성/가성 판정 근거로 확정할 수 없음. 크랙/샤프트 새 원본 형식과 첫 검사 건·100의 의미는 수령 후 확인 필요.',
        'notes':notes}
    (output/'실행설정.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
    import html
    body='<html lang="ko"><meta charset="utf-8"><title>새 CSV PCA 탐색</title><style>body{font:17px/1.8 sans-serif;margin:30px}img{max-width:100%}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}</style><h1>새 CSV PCA 탐색</h1><p>일반 NG의 진성·가성은 미확정입니다. 그림의 분리를 불량 판정이나 정확도로 해석하지 않습니다.</p>'
    body+=table.to_html(index=False)+masters.to_html(index=False)
    for name in figures:body+=f'<h2>{html.escape(name)}</h2><img src="{name}.png">'
    body+='<h2>분석 기준과 한계</h2>'+''.join('<p>'+html.escape(str(policy[k]))+'</p>' for k in ('master_rule','saturation_rule','fit','limits'))
    (output/'PCA보고서.html').write_text(body,encoding='utf-8')
    archive=Path(shutil.make_archive(str(output),'zip',root_dir=output))
    return {'folder':output,'zip':archive,'counts':table,'masters':masters,'points':coords,'removed_axes':pd.DataFrame(removed),'notes':notes,'figures':figures}

def show_explorer(root):
    """One startup cell, then file selection and buttons; no user code editing."""
    import ipywidgets as w
    from IPython.display import display,HTML,clear_output
    from urllib.parse import quote
    import html
    root=Path(root);folder=root/'notebooks/새CSV_업로드';folder.mkdir(exist_ok=True)
    files=w.Dropdown(description='CSV 파일:',options=['파일을 먼저 올려 주세요'],layout=w.Layout(width='95%'))
    upload=w.FileUpload(accept='.csv,.gz',multiple=False,description='새 CSV 선택')
    refresh=w.Button(description='파일 목록 새로고침',icon='refresh')
    target=w.ToggleButtons(options=[('크랙','crack'),('샤프트','shaft')],description='분석 대상:')
    exclude=w.Checkbox(value=True,description='샤프트: 100이 있는 X/Y축을 제외한 결과도 비교',indent=False,layout=w.Layout(width='95%'))
    run=w.Button(description='PCA 분석 실행',button_style='primary',icon='play',layout=w.Layout(width='230px',height='42px'))
    status=w.HTML('CSV를 올린 뒤 파일과 분석 대상을 선택하세요.');out=w.Output()
    def update(selected=None):
        names=sorted(p.name for p in folder.iterdir() if p.is_file() and p.name.lower().endswith(('.csv','.csv.gz')))
        files.options=names or ['파일을 먼저 올려 주세요']
        if selected in names:files.value=selected
    def receive(change):
        if not upload.value:return
        try:
            item=upload.value[0];name=item['name']
            if Path(name).name!=name or '\\' in name or not name.lower().endswith(('.csv','.csv.gz')):raise ValueError('CSV 파일명과 확장자를 확인하세요.')
            if len(item['content'])>100*1024*1024:raise ValueError('100MB 이하의 CSV를 사용하세요. 더 큰 파일은 담당자에게 전달해 주세요.')
            dest=folder/name
            if dest.exists():
                suffix='.csv.gz' if name.lower().endswith('.csv.gz') else '.csv'
                dest=folder/(name[:-len(suffix)]+'_'+datetime.datetime.now().strftime('%H%M%S_%f')+suffix)
            with dest.open('xb') as stream:stream.write(bytes(item['content']))
            update(dest.name);status.value='<p>업로드 완료: '+html.escape(dest.name)+'</p>'
        except Exception as e:status.value='<p>업로드 확인: '+html.escape(str(e))+'</p>'
    def execute(_):
        run.disabled=True
        with out:
            clear_output(wait=True)
            try:
                path=folder/files.value
                if not path.is_file():raise ValueError('먼저 CSV 파일을 올려 주세요.')
                print('선택 파일:',path.name)
                if '사용법_예제' in path.name:display(HTML('<p style="background:#fff3cd;padding:12px">합성 예제입니다. 회사 성능 결과로 사용하지 않습니다.</p>'))
                print('위치별 수량, 마스터 지정과 PCA를 계산하고 있습니다.')
                style();result=explore_csv(path,root/'results',target.value,exclude.value)
                display(HTML('<h3>위치별 조건 비교</h3>'));display(result['counts'])
                display(HTML('<h3>첫 측정 MASTER 지정 확인</h3>'));display(result['masters'])
                for note in result['notes']:print('확인 사항:',note)
                for fig in result['figures'].values():display(fig);plt.close(fig)
                href=download_href(result['zip'],root)
                display(HTML(f'<h2>저장 완료</h2><p><a href="{href}" download>결과 ZIP 다운로드</a></p><p>압축을 풀고 PCA보고서.html을 더블클릭하면 표와 그림을 함께 볼 수 있습니다.</p>'))
                status.value='<p>분석 완료. 아래 그래프와 다운로드 링크를 확인하세요.</p>'
            except Exception as e:display(HTML('<p style="color:#a00">실행 확인: '+html.escape(str(e))+'</p>'))
            finally:run.disabled=False
    upload.observe(receive,names='value');refresh.on_click(lambda _:update(files.value));run.on_click(execute);update()
    display(w.VBox([w.HTML('<h2>파일 선택 → 분석 대상 선택 → PCA 실행</h2><p>별도의 코드 수정은 필요하지 않습니다. 표준 ECT CSV용이며, 일반 NG의 진성·가성은 확정하지 않습니다.</p>'),w.HBox([upload,refresh]),files,target,exclude,run,status,out]))
    return {'upload':upload,'files':files,'target':target,'exclude':exclude,'run':run,'status':status,'output':out}
