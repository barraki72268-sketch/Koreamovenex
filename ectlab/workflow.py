"""Fit once, then score batches with frozen feature masks, classifiers and PCA."""
from pathlib import Path
from datetime import datetime
import hashlib,json,uuid,shutil
import numpy as np
import pandas as pd
import joblib
from sklearn.preprocessing import RobustScaler
from sklearn.decomposition import PCA
from ectlab.data import file_hash,feature_schema,read_workbook,company_label
from ectlab.delivery import feature_frame
from ectlab.pipeline import classifier,Settings,evenly_sample

LABELS={'OK':'normal','NG_master':'master','MASTER':'master','field_true':'true','field_false':'false','unlabeled':'unknown','normal':'normal','master':'master','true':'true','false':'false','unknown':'unknown','진성':'true','가성':'false','정상':'normal'}


def new_folder(root,prefix):
    p=Path(root)/'results'/(prefix+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    import os
    if os.name=='nt' and not str(p).startswith('\\\\?\\'):p=Path('\\\\?\\'+str(p.resolve()))
    p.mkdir(parents=True);return p


def signature(row,values):
    text='|'.join(str(row[k]) for k in ('line','product','position','date','time','counter'))
    numeric='|'.join(format(float(value),'.12g') for value in values)
    return hashlib.sha256((text+'|'+numeric).encode()).hexdigest()


def _meta(g,profile,legacy=False):
    if legacy:
        r=g[['date','time','counter','line','product','position','equipment_label','source_sheet','source_row']].copy()
        field=g.get('field_label',pd.Series('unlabeled',index=g.index))
        r['label']=field.map(LABELS).fillna('unknown')
        r.loc[r.label.eq('unknown')&r.equipment_label.eq('OK'),'label']='normal'
        r['master']=field.eq('NG_master').to_numpy()
        yellow=g.get('yellow_any',pd.Series(False,index=g.index)).astype(str).str.lower().isin(['true','1'])
        bad=field.isin(['measurement_error','color_on_OK_unverified','color_conflict','mapping_label_conflict','unmatched'])
        maximum=pd.to_numeric(g.max_value,errors='coerce')
        r['reason']=np.where(maximum.eq(0)|yellow,'최대값 0 / 노랑: 판정 불명',np.where(bad,'측정 오류 또는 라벨 확인 필요',np.where(maximum.isna(),'최대값 결측','')))
    else:
        r=g[['c0','c1','c2','c3','c4','c6','c5','source_sheet','source_row']].rename(columns={'c0':'date','c1':'time','c2':'counter','c3':'line','c4':'product','c6':'position','c5':'equipment_label'}).copy()
        r['master']=g.get('_master',pd.Series(False,index=g.index)).to_numpy()
        r['label']=np.where(r.master,'master',np.where(r.equipment_label.eq('OK'),'normal','unknown'))
        maximum=pd.to_numeric(g.c7,errors='coerce')
        r['reason']=np.where(maximum.eq(0),'최대값 0: 판정 불명',np.where(maximum.isna(),'최대값 결측',''))
    r=r.reset_index(drop=True)
    r['profile']=profile;r['position']=pd.to_numeric(r.position,errors='raise').astype(int)
    for col in ('line','product','date','time','counter','source_sheet'):r[col]=r[col].fillna('').astype(str)
    sources=g.get('source_file',pd.Series('',index=g.index)).astype(str).to_numpy()
    r['sample_id']=[f'{profile}|{f}|{s}|{n}|P{p}' for f,s,n,p in zip(sources,r.source_sheet,r.source_row,r.position)]
    r['conflict']=r.master&r.equipment_label.ne('NG')
    r.loc[r.conflict,'reason']='MASTER 후보 / 설비 OK 충돌'
    return r


def read_groups(path,profile,root,training=False,day_start=6,on_progress=None):
    """Supported native files or the exported feature-vector CSV format."""
    path=Path(path);root=Path(root)
    if profile not in ('c10','crack','shaft'):raise ValueError('C10 열처리 / 크랙 / 샤프트를 선택하세요.')
    vector=False
    if path.name.lower().endswith(('.csv','.csv.gz')):
        raw=pd.read_csv(path,dtype={'source_sheet':str},low_memory=False)
        vector=any(c.startswith('feature__') for c in raw.columns)
    elif path.suffix.lower()=='.xlsx' and profile=='c10':
        raw=read_workbook(path);raw['field_label']=raw.apply(company_label,axis=1)
    elif path.suffix.lower()=='.xlsx':
        from ectlab import delivery_excel as converter
        digest=file_hash(path);code=file_hash(Path(converter.__file__))
        key=hashlib.sha256((profile+digest+path.name+code).encode()).hexdigest()
        existing=root/'data/processed/새Excel_변환캐시'/key
        good=False
        if (existing/'cache.json').is_file():
            info=json.loads((existing/'cache.json').read_text(encoding='utf-8'))
            good=info.get('source_sha256')==digest and len(info.get('files',{}))==3 and all((existing/n).is_file() and file_hash(existing/n)==h for n,h in info['files'].items())
        if good:csv=existing/(profile+'_raw.csv.gz')
        else:
            folder=new_folder(root,'입력변환');csv=converter.convert_workbook(profile,path,folder,on_progress=on_progress)
        raw=pd.read_csv(csv,dtype={'source_sheet':str},low_memory=False)
    else:raise ValueError('지원하는 .xlsx / .csv / .csv.gz를 사용하세요.')
    if vector:
        required={'sample_id','line','product','position','equipment_label'}
        if not required.issubset(raw):raise ValueError('벡터 CSV에는 sample_id, line, product, position, equipment_label이 필요합니다.')
        if raw.sample_id.isna().any() or raw.sample_id.duplicated().any():raise ValueError('샘플 ID는 비어 있거나 중복될 수 없습니다.')
        for col in ('date','time','counter'):raw[col]=raw.get(col,pd.Series('',index=raw.index)).fillna('').astype(str)
        if training and 'label' not in raw:raise ValueError('벡터 학습 CSV에는 label(normal/master/true/false/unknown)을 넣으세요.')
        raw['source_sheet']='vector';raw['source_row']=np.arange(len(raw))+2
        raw['position']=pd.to_numeric(raw.position,errors='raise').astype(int)
        raw['line']=raw.line.astype(str);raw['product']=raw['product'].astype(str)
        raw['equipment_label']=raw.equipment_label.fillna('미입력').astype(str)
        raw['label']=raw.get('label',pd.Series('unknown',index=raw.index)).map(LABELS).fillna('unknown')
        raw['master']=raw.label.eq('master');raw['profile']=profile;raw['conflict']=raw.master&raw.equipment_label.ne('NG')
        raw['reason']=np.where(raw.conflict,'MASTER 후보 / 설비 OK 충돌','')
        if 'max_value' in raw:raw.loc[pd.to_numeric(raw.max_value,errors='coerce').eq(0),'reason']='최대값 0: 판정 불명'
        if raw.equipment_label.isin(['OK','NG','미입력']).eq(False).any():raise ValueError('설비 판정은 OK/NG 또는 빈칸입니다.')
    else:
        keys=['line','product','position'] if profile=='c10' else ['c3','c4','c6']
        missing=set(keys+(['date','time','counter','equipment_label','max_value'] if profile=='c10' else ['c0','c1','c2','c5','c7']))-set(raw)
        if missing:raise ValueError('선택한 자료 종류와 파일 형식이 다릅니다: '+', '.join(sorted(missing)))
    raw=raw.copy();raw['_input_order']=np.arange(len(raw))
    groups={}
    for key,g in raw.groupby(['line','product','position'] if vector or profile=='c10' else ['c3','c4','c6'],sort=False):
        g=g.reset_index(drop=True).copy()
        if vector:
            cols=[c for c in g if c.startswith('feature__')];features=[c[len('feature__'):] for c in cols]
            X=g[cols].apply(pd.to_numeric,errors='coerce').to_numpy(float)
            descriptors=[{'feature':name,'slot':i,'axis':'vector'} for i,name in enumerate(features)]
            rows=g[[c for c in g if not c.startswith('feature__')]].copy()
        elif profile=='c10':
            schema=feature_schema(g);features=[f'B{f["block"]}_S{f["column"].split("_")[-1]}_{f["frequency"]}_{f["axis"]}' for f in schema]
            X=g[[f['column'] for f in schema]].apply(pd.to_numeric,errors='coerce').to_numpy(float)
            descriptors=[dict(f,feature=name,slot=int(f['column'].split('_')[-1])) for f,name in zip(schema,features)]
            rows=_meta(g,profile,True)
        else:
            if profile=='crack':
                from ectlab.inspection_day import crack_inspection_days
                g,master=crack_inspection_days(g,day_start)
                g['_master']=master if training else g.c2.astype(str).str.contains('마스터|MASTER',case=False,regex=True)
            else:g['_master']=g.c2.astype(str).str.contains('마스터|MASTER',case=False,regex=True)
            frame,descriptors=feature_frame(g,profile);features=list(frame);X=frame.to_numpy(float)
            rows=_meta(g,profile)
        rows=rows.reset_index(drop=True)
        rows['order']=g['_input_order'].to_numpy()
        rows['signature']=[signature(row,x) for (_,row),x in zip(rows.iterrows(),X)]
        groupkey=(str(key[0]),str(key[1]),int(key[2]))
        groups[groupkey]={'rows':rows,'X':X,'features':features,'descriptors':descriptors,'vector':vector}
    return groups


def prepare_training(path,profile,root,drop_saturation=None,train_end='',day_start=6,on_progress=None):
    if drop_saturation is None:drop_saturation=profile=='shaft'
    digest=file_hash(path);groups=read_groups(path,profile,root,True,day_start,on_progress)
    summary=[]
    for key,g in groups.items():
        rows=g['rows'];X=g['X'];selected=np.ones(len(rows),bool)
        if train_end:
            dates=pd.to_datetime(rows.date,errors='coerce')
            if dates.isna().any():raise ValueError('학습 종료일을 쓰려면 모든 행의 날짜가 필요합니다.')
            selected=(dates<=pd.Timestamp(train_end)).to_numpy()
        valid=selected&rows.reason.eq('').to_numpy()&np.isfinite(X).all(axis=1)
        mask=np.ones(X.shape[1],bool)
        if drop_saturation and valid.any():
            badslots=set()
            for i,f in enumerate(g['descriptors']):
                v=X[valid,i]
                if np.isclose(np.abs(v),32767,rtol=0,atol=1e-9).any() or (f['axis'] in ('측정값','vector') and np.isclose(v,100,rtol=0,atol=1e-9).any()):badslots.add(f['slot'])
            mask=np.array([f['slot'] not in badslots for f in g['descriptors']])
        g.update(selected=selected,valid=valid,mask=mask)
        summary.append({'라인':key[0],'품번':key[1],'위치':key[2],'전체행':len(rows),'학습기간행':int(selected.sum()),'유효행':int(valid.sum()),'MASTER':int((valid&rows.master).sum()),'기업진성':int((valid&rows.label.eq('true')).sum()),'기업가성':int((valid&rows.label.eq('false')).sum()),'원본입력수':X.shape[1],'사용입력수':int(mask.sum()),'제외입력':', '.join(np.asarray(g['features'])[~mask])})
    if file_hash(path)!=digest:raise ValueError('파일이 읽는 중 변경됐습니다. ①번부터 다시 실행하세요.')
    return {'profile':profile,'source':str(path),'source_hash':digest,'groups':groups,'summary':pd.DataFrame(summary),'drop_saturation':bool(drop_saturation),'train_end':train_end,'day_start':day_start}


def fit_prepared(prepared,root,model_name='RandomForest',low=.1,high=.9):
    if not 0<=low<high<=1:raise ValueError('낮음 기준 < 높음 기준, 0~1 범위를 사용하세요.')
    if file_hash(prepared['source'])!=prepared['source_hash']:raise ValueError('학습 파일이 변경됐습니다. ①번부터 다시 실행하세요.')
    folder=new_folder(root,'학습모델');models={};summary=[]
    for key,g in prepared['groups'].items():
        r=g['rows'];valid=g['valid'];mask=g['mask'];base={'라인':key[0],'품번':key[1],'위치':key[2]}
        true=valid&r.label.eq('true').to_numpy()
        direct=bool(true.any())
        positive=true if direct else valid&r.master.to_numpy()&r.equipment_label.eq('NG').to_numpy()
        negative=valid&~r.master.to_numpy()&(r.equipment_label.eq('OK')|r.label.isin(['normal','false'])).to_numpy()&~true
        if mask.sum()<2 or not positive.any() or not negative.any():
            summary.append(dict(base,상태='학습 불가',학습기준='기업 진성/MASTER와 OK·가성 두 종류 및 입력 2개 이상 필요',양성=int(positive.sum()),음성=int(negative.sum())));continue
        neg=evenly_sample(np.flatnonzero(negative),2000);indices=np.r_[np.flatnonzero(positive),neg]
        y=positive[indices].astype(int);A=g['X'][:,mask]
        if not np.any(np.ptp(A[valid],axis=0)>0):
            summary.append(dict(base,상태='학습 불가',학습기준='유효 측정값에 변화가 없어 PCA/분류 기준 생성 불가',양성=int(positive.sum()),음성=len(neg)));continue
        estimator=classifier(model_name,Settings(c10a_retrospective_guard=False),y);estimator.fit(A[indices],y)
        scaler=RobustScaler().fit(A[valid]);scaled=scaler.transform(A[valid])
        pca=PCA(n_components=2,random_state=42).fit(scaled)
        plot_ids=evenly_sample(np.flatnonzero(valid),2000)
        # All rare labelled references remain visible in the training plot.
        plot_ids=np.unique(np.r_[plot_ids,np.flatnonzero(valid&r.label.isin(['true','false','master']).to_numpy())])
        plotrows=r.iloc[plot_ids].copy();plotrows[['PC1','PC2']]=pca.transform(scaler.transform(A[plot_ids]))
        mode='기업 진성 / 정상·가성 라벨 학습' if direct else 'MASTER / 설비 OK·가성 참조 학습'
        signatures=[signature(row,x) for (_,row),x in zip(r.iterrows(),A)]
        models[key]={'model':estimator,'model_name':model_name,'features':list(np.asarray(g['features'])[mask]),'all_features':g['features'],
                     'descriptors':[f for f,keep in zip(g['descriptors'],mask) if keep], 'scaler':scaler,'pca':pca,'reference':plotrows,
                     'mode':mode,'direct_labels':direct,'train_rows':len(indices),'positive_count':int(positive.sum()),'negative_count':len(neg),
                     'training_file_signatures':{signatures[i] for i in np.flatnonzero(g['selected'])},'model_signatures':{signatures[i] for i in indices}}
        summary.append(dict(base,상태='학습 완료',학습기준=mode,양성=int(positive.sum()),음성=len(neg),사용입력수=int(mask.sum()),PCA설명비율=float(pca.explained_variance_ratio_.sum())))
    if not models:raise ValueError('학습 가능한 구간이 없습니다. ①번 수량표에서 유효 MASTER/기업 진성, OK·가성, 남은 입력 수를 확인하세요.')
    bundle={'schema':1,'profile':prepared['profile'],'source_hash':prepared['source_hash'],'source_file':Path(prepared['source']).name,
            'model_name':model_name,'low':low,'high':high,'day_start':prepared['day_start'],'drop_saturation':prepared['drop_saturation'],
            'train_end':prepared['train_end'],'models':models,'summary':pd.DataFrame(summary),'folder':folder}
    joblib.dump(bundle,folder/'학습모델.joblib')
    bundle['summary'].to_csv(folder/'학습요약.csv',index=False,encoding='utf-8-sig')
    (folder/'학습기준.json').write_text(json.dumps({k:v for k,v in bundle.items() if k not in ('models','summary','folder')},ensure_ascii=False,indent=2),encoding='utf-8')
    for i,(key,m) in enumerate(models.items(),1):
        example={'sample_id':'새샘플_001','line':key[0],'product':key[1],'position':key[2],'equipment_label':'','date':'','time':'','counter':'','max_value':np.nan,'label':'unknown'}
        example.update({'feature__'+f:np.nan for f in m['features']})
        template=pd.DataFrame([example])
        template.to_csv(folder/f'벡터입력양식_{i:02d}.csv',index=False,encoding='utf-8-sig')
    return bundle


def predict_groups(bundle,groups):
    output=[]
    for key,g in groups.items():
        r=g['rows'].copy();r['점수']=np.nan;r['PC1']=np.nan;r['PC2']=np.nan;r['예측']='입력 확인 필요';r['설명']='학습하지 않은 품번·위치';r['학습기준']='미등록'
        r['학습파일중복']=False;r['모델학습행중복']=False
        m=bundle['models'].get(key)
        if m is None:output.append(r);continue
        r['학습기준']=m['mode'];features=g['features']
        missing=set(m['features'])-set(features)
        drift=not g['vector'] and set(features)!=set(m['all_features'])
        if missing or drift:r['설명']='학습 때와 주파수/입력 컬럼이 다름: '+', '.join(sorted(missing));output.append(r);continue
        A=g['X'][:,[features.index(f) for f in m['features']]]
        valid=r.reason.eq('').to_numpy()&np.isfinite(A).all(axis=1)
        r['설명']=np.where(r.reason.ne(''),r.reason,np.where(np.isfinite(A).all(axis=1),'','측정값 결측·무한값'))
        saturation=np.zeros(len(r),bool)
        if bundle['drop_saturation']:
            for j,f in enumerate(m['descriptors']):
                v=A[:,j];saturation|=np.isclose(np.abs(v),32767,rtol=0,atol=1e-9)
                if f['axis'] in ('측정값','vector'):saturation|=np.isclose(v,100,rtol=0,atol=1e-9)
        ids=np.flatnonzero(valid)
        if len(ids):
            p=m['model'].predict_proba(A[ids])[:,list(m['model'].classes_).index(1)]
            r.loc[ids,'점수']=p;r.loc[ids,['PC1','PC2']]=m['pca'].transform(m['scaler'].transform(A[ids]))
            equipment=r.iloc[ids].equipment_label.to_numpy();hi=p>=bundle['high'];lo=p<=bundle['low']
            prediction=np.where(hi,np.where(equipment=='OK','불량 의심 · FN 후보','진성불량 의심'),np.where(lo,np.where(equipment=='NG','가성불량 후보','정상 유사'),'판정 보류'))
            prediction[saturation[ids]]='판정 보류'
            r.loc[ids,'예측']=prediction
            r.loc[ids,'설명']=np.where(saturation[ids],'학습 이후 새 포화값: 입력 기준 유지·보류',np.where(hi,'높음 기준 이상',np.where(lo,'낮음 기준 이하','두 기준 사이')))
        signatures=pd.Series([signature(row,x) for (_,row),x in zip(r.iterrows(),A)],index=r.index)
        r['학습파일중복']=signatures.isin(m['training_file_signatures']);r['모델학습행중복']=signatures.isin(m['model_signatures'])
        output.append(r)
    if not output:raise ValueError('검사할 측정행이 없습니다.')
    result=pd.concat(output,ignore_index=True).sort_values('order',kind='stable').reset_index(drop=True)
    result['검증구분']=np.where(result.학습파일중복,'학습 파일과 중복 · 독립 검증 아님','신규 입력 · 정답 확인 별도 필요')
    result['판정범위']='진성/가성은 후보 예측이며 실제 FN 확정은 현장 검사·정답 연결 필요'
    return result


def predict_file(bundle,path,root):
    # No fit call: masks, scaler, PCA, classifier, thresholds and model version stay frozen.
    groups=read_groups(path,bundle['profile'],root,training=False,day_start=bundle['day_start'])
    rows=predict_groups(bundle,groups)
    folder=Path(bundle['folder'])/'검사결과'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');folder.mkdir(parents=True)
    rows.to_csv(folder/'샘플별_예측결과.csv',index=False,encoding='utf-8-sig')
    summary=rows.groupby(['line','product','position','예측'],dropna=False).size().rename('수량').reset_index()
    summary.to_csv(folder/'배치_판정요약.csv',index=False,encoding='utf-8-sig')
    record={'model_source_hash':bundle['source_hash'],'input_file':Path(path).name,'input_hash':file_hash(path),'refitted':False,'PCA_refitted':False,'rows':len(rows),'training_overlap_rows':int(rows.학습파일중복.sum()),'low':bundle['low'],'high':bundle['high'],'model_name':bundle['model_name']}
    (folder/'검사기록.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'rows':rows,'summary':summary,'folder':folder,'record':record}


def pca_figure(bundle,key,predictions=None):
    import matplotlib.pyplot as plt
    from ectlab.plots import style
    style();m=bundle['models'][key];r=m['reference'];fig,ax=plt.subplots(figsize=(9,6))
    if predictions is None:
        for label,name,color,marker in [('normal','학습 설비 OK','#8c9daf','o'),('false','기업 가성','#37a275','o'),('unknown','정답 미확정 · PCA 참고','#b8bec6','.'),('master','학습 MASTER','#7951b0','*'),('true','기업 진성','#d45450','X')]:
            ix=r.label.eq(label)
            if ix.any():ax.scatter(r.loc[ix,'PC1'],r.loc[ix,'PC2'],c=color,marker=marker,s=95 if label in ('master','true') else 15,alpha=.8,label=f'{name} ({int(ix.sum())}표시)')
    else:
        ax.scatter(r.PC1,r.PC2,c='#b5bec7',s=12,alpha=.3,label='고정된 학습 분포')
        for name,color,marker in [('정상 유사','#287cbb','o'),('가성불량 후보','#299b74','^'),('진성불량 의심','#d45450','X'),('불량 의심 · FN 후보','#b83d91','X'),('판정 보류','#e4a236','D')]:
            part=predictions[predictions.예측.eq(name)&predictions.PC1.notna()];part=part.iloc[evenly_sample(np.arange(len(part)),2000)]
            if len(part):ax.scatter(part.PC1,part.PC2,c=color,marker=marker,s=48,alpha=.85,label=f'{name} ({len(part)}표시)')
    ax.set(title=f'{key[0]} / {key[1]} / 위치 {key[2]}\n{m["model_name"]} · {m["mode"]}\n학습 때 고정한 PCA · 2축 설명 비율 {m["pca"].explained_variance_ratio_.sum():.1%}',xlabel='PC1',ylabel='PC2')
    ax.legend(fontsize=8);ax.grid(alpha=.15);fig.tight_layout();return fig


def export_prediction(bundle,result):
    import matplotlib.pyplot as plt
    import html
    folder=result['folder'];body='<html lang="ko"><meta charset="utf-8"><title>배치 검사 결과</title><style>body{font:16px/1.8 sans-serif;margin:24px}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px}</style><h1>배치 검사 결과</h1><p>저장된 모델·전처리·PCA를 그대로 사용했습니다. 새 입력으로 다시 학습하지 않았습니다. 진성·가성 및 FN은 후보 예측이며 현장 확인이 필요합니다.</p>'+result['summary'].to_html(index=False)
    for i,(key,m) in enumerate(bundle['models'].items(),1):
        rows=result['rows'];part=rows[rows.line.eq(key[0])&rows['product'].eq(key[1])&rows.position.eq(key[2])]
        if part.empty:continue
        fig=pca_figure(bundle,key,part);name=f'{i:02d}_신규샘플_PCA.png';fig.savefig(folder/name,dpi=140,bbox_inches='tight');plt.close(fig)
        body+='<h2>'+html.escape(str(key))+'</h2><img src="'+name+'">'
    (folder/'배치검사_보고서.html').write_text(body,encoding='utf-8')
    result['zip']=Path(shutil.make_archive(str(folder),'zip',root_dir=folder));return result
