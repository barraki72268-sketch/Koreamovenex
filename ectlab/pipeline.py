"""CPU analysis. Every fit, scale and threshold is independent for positions 1/2."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import importlib.metadata
import numpy as np
import pandas as pd
import joblib
from .data import feature_schema, file_hash

METHODS = ['robust_l2','shrink_mahal','pca95','cosine']
DECISIONS = {'false_candidate':'가성 후보','review':'보류','true_suspect':'진성 의심'}

@dataclass
class Settings:
    train_end: str = '2026-08-20'
    calibration_end: str = '2026-10-07'
    seed: int = 42
    false_max: float = .1
    suspect_min: float = .9
    normal_reference: int = 512
    # The extra 30 Hz guard was selected AFTER reviewing two positives.
    c10a_retrospective_guard: bool = True

def evenly_sample(indices,n):
    return indices[np.unique(np.linspace(0,len(indices)-1,min(n,len(indices)),dtype=int))] if len(indices) else np.array([],dtype=int)

def balanced_sample(rows,mask,per_day):
    indices=np.flatnonzero(mask)
    groups=[evenly_sample(indices[rows.loc[indices,'date'].eq(d)],per_day) for d in sorted(rows.loc[indices,'date'].unique())]
    return np.concatenate(groups) if groups else np.array([],dtype=int)

def prepare(df, settings=None):
    """Freeze time cutoffs, reject incompatible features, and keep exclusion reasons."""
    settings=settings or Settings()
    if pd.Timestamp(settings.train_end)>=pd.Timestamp(settings.calibration_end): raise ValueError('학습 종료일은 기준 설정 종료일보다 빨라야 합니다.')
    packs={}; counts=[]
    for pos,g in df.groupby('position',sort=True):
        r=g.reset_index(drop=True).copy(); features=feature_schema(r); columns=[f['column'] for f in features]; X=r[columns].to_numpy(float)
        r['role']=np.select([r.date.le(settings.train_end),r.date.le(settings.calibration_end)],['train','calibration'],default='test')
        unknown=r.yellow_any|r.max_value.eq(0)
        badlabel=r.field_label.isin(['measurement_error','color_on_OK_unverified','color_conflict','mapping_label_conflict','unmatched'])
        r['eligible']=np.isfinite(X).all(1)&~unknown&~badlabel&r.max_value.notna()
        r['exclusion_reason']=np.select([unknown,r.field_label.eq('measurement_error'),badlabel,~np.isfinite(X).all(1),r.max_value.isna()],['0/노랑: 판정 불명','측정 오류','라벨 연결/확인 필요','X/Y 결측·무한값','최대값 결측'],default='')
        r['normal']=r.eligible&r.equipment_label.eq('OK')&~r.field_label.eq('NG_master')
        r['NG_evaluation']=r.eligible&r.equipment_label.eq('NG')&r.field_label.isin(['field_true','field_false'])
        r['NG_query']=r.eligible&r.equipment_label.eq('NG')&~r.field_label.eq('NG_master')
        truegroups=set(r.loc[r.NG_evaluation&r.field_label.eq('field_true'),'event_group'])
        r['company_train']=r.role.eq('train')&r.NG_evaluation&(r.field_label.eq('field_true')|~r.event_group.isin(truegroups))
        r['master_train']=r.eligible&r.role.eq('train')&r.field_label.eq('NG_master')&~r.event_group.isin(truegroups)
        pool=r.role.eq('train')&r.normal&~r.event_group.isin(truegroups)
        days=r.loc[pool,'date'].nunique()
        ref=balanced_sample(r,pool,max(1,settings.normal_reference//max(days,1)))
        r['normal_context']=False; r.loc[ref,'normal_context']=True
        r['proxy_train']=r.master_train|r.normal_context|(r.company_train&r.field_label.eq('field_false'))
        r['test_OK_sample']=False; r.loc[balanced_sample(r,r.role.eq('test')&r.normal,256),'test_OK_sample']=True
        if not (r.normal&r.role.eq('train')).any(): raise ValueError(f'위치{pos}: 학습 구간 설비 OK가 없습니다. 날짜 설정을 확인하세요.')
        packs[int(pos)]={'rows':r,'X':X,'features':features,'settings':settings}
        counts.append({'위치':pos,'측정행':len(r),'입력수':len(features),'학습 OK':int((r.normal&r.role.eq('train')).sum()),
                       '기준 설정 OK':int((r.normal&r.role.eq('calibration')).sum()),'시험 OK':int((r.normal&r.role.eq('test')).sum()),
                       '학습 마스터':int(r.master_train.sum()),'기업 진성':int((r.NG_evaluation&r.field_label.eq('field_true')).sum()),
                       '기업 가성':int((r.NG_evaluation&r.field_label.eq('field_false')).sum()),'미판정 NG':int((r.NG_query&~r.NG_evaluation).sum()),
                       '제외행':int((~r.eligible).sum()),'진성 사건그룹':len(truegroups)})
    return packs,pd.DataFrame(counts)

def distance(Q,R,cos=False,k=1):
    if not len(R): raise ValueError('거리 기준 샘플이 없습니다.')
    result=[]
    for start in range(0,len(Q),512):
        q=Q[start:start+512]
        d=np.maximum(1-q@R.T,0) if cos else np.sqrt(np.maximum((q*q).sum(1)[:,None]+(R*R).sum(1)[None,:]-2*q@R.T,0)/q.shape[1])
        result.append(np.median(np.partition(d,min(k,len(R))-1,axis=1)[:,:min(k,len(R))],axis=1))
    return np.concatenate(result) if result else np.array([])

def categories(dm,do,mt,ot,nt):
    c=np.full(len(dm),'border',object); c[dm<=mt]='true'
    c[(dm>1.5*mt)&(do>ot)]='false'; c[(dm>1.5*mt)&(do<=nt)]='ok_like'
    return c

def _space(A,train,name):
    if name=='robust_l2': return A,{'name':name}
    if name=='cosine': return A/np.maximum(np.linalg.norm(A,axis=1)[:,None],1e-12),{'name':name}
    mu=A[train].mean(0); cov=np.atleast_2d(np.cov(A[train],rowvar=False))
    if name=='shrink_mahal':
        shr=.9*cov+.1*np.diag(np.diag(cov))+np.eye(A.shape[1])*max(np.trace(cov)/A.shape[1]*1e-6,1e-8)
        ew,ev=np.linalg.eigh(shr); W=ev@np.diag(1/np.sqrt(np.maximum(ew,1e-8)))
        return A@W,{'name':name,'W':W}
    eig,V=np.linalg.eigh(cov); order=np.argsort(eig)[::-1]; eig=np.maximum(eig[order],0); V=V[:,order]
    k=max(1,int(np.searchsorted(np.cumsum(eig)/max(eig.sum(),1e-12),.95)+1))
    W=V[:,:k]/np.sqrt(np.maximum(eig[:k],max(eig[0]*1e-3,1e-8)))
    return (A-mu)@W,{'name':name,'mu':mu,'W':W}

def _distance_scope(pack,scope,indices):
    r,X=pack['rows'],pack['X']; train=np.flatnonzero(r.normal&r.role.eq('train')); cal=np.flatnonzero(r.normal&r.role.eq('calibration'))
    master=np.flatnonzero(r.eligible&r.field_label.eq('NG_master')&r.role.eq('train')); calm=np.flatnonzero(r.eligible&r.field_label.eq('NG_master')&r.role.eq('calibration'))
    if len(train)<3 or not len(cal) or not len(master): raise ValueError('거리 분석에는 학습 OK 3행 이상, 기준 설정 OK, 학습 마스터가 필요합니다.')
    days=r.loc[train,'date'].nunique(); ref=balanced_sample(r,r.normal&r.role.eq('train'),max(1,512//days))
    median=np.median(X[train],0); scale=np.quantile(X[train],.75,axis=0)-np.quantile(X[train],.25,axis=0); scale=np.where(scale<=1e-6,1,scale)
    A=((X-median)/scale)[:,indices]; query=np.flatnonzero(r.NG_query); allq=np.unique(np.r_[cal,query,calm]); lookup={v:i for i,v in enumerate(allq)}
    ngq=np.array([lookup[v] for v in query],dtype=int); calq=np.array([lookup[v] for v in cal],dtype=int); records=[]; artifacts=[]
    for name in METHODS:
        F,transform=_space(A,train,name); co=name=='cosine'
        dm=distance(F[allq],F[master],co); do=distance(F[allq],F[ref],co,5); mc=[]
        for j in master:
            other=master[r.loc[master,'date'].ne(r.at[j,'date'])]
            if len(other): mc.append(float(distance(F[[j]],F[other],co)[0]))
        mc.extend(float(dm[lookup[j]]) for j in calm)
        if len(mc)<3: raise ValueError('마스터 기준 설정 표본이 3개 미만입니다. 다른 날짜 마스터를 추가하세요.')
        mt=max(float(np.quantile(mc,.95)),1e-8); ot=max(float(np.quantile(do[calq],.99)),1e-8); nt=float(np.quantile(do[calq],.95))
        frame=r.iloc[query][['id','position','date','time','counter','source_row','source_sheet','field_label','role','NG_evaluation']].copy()
        frame['scope']=scope; frame['method']=name; frame['category']=categories(dm[ngq],do[ngq],mt,ot,nt)
        frame['master_ratio']=dm[ngq]/mt; frame['OK_ratio']=do[ngq]/ot; records.append(frame)
        artifacts.append({'scope':scope,'method':name,'indices':indices,'median':median,'scale':scale,'transform':transform,
                          'master_reference':F[master],'OK_reference':F[ref],'master_near95':mt,'OK_far99':ot,'OK_near95':nt})
    return pd.concat(records,ignore_index=True),artifacts

def distance_analysis(packs):
    detail=[]; decisions=[]; artifacts={}; notes=[]
    for pos,pack in packs.items():
        try:
            full,models=_distance_scope(pack,'full',list(range(len(pack['features']))))
            rows=pack['rows']; query=rows[rows.NG_query].copy().set_index('id')
            def matrix(df,col): return df.pivot(index='id',columns='method',values=col).reindex(index=query.index,columns=METHODS).to_numpy()
            cats=matrix(full,'category'); mr=matrix(full,'master_ratio'); ok=matrix(full,'OK_ratio')
            normal=(cats=='ok_like').sum(1)>=3; far=(ok>1).sum(1)>=3; near=(mr<=1).sum(1)>=3
            result=np.full(len(query),'review',object); suspect=near&far
            guard=pack['settings'].c10a_retrospective_guard and pos==2 and rows.source_file.iloc[0]=='C10A_49513-75270R.xlsx'
            ix=[i for i,f in enumerate(pack['features']) if f['block']==1 and f['frequency']=='30.0Hz']
            if guard:
                if len(ix)!=2: raise ValueError('C10A 보완 기준용 첫 블록 30Hz X/Y 구성이 다릅니다.')
                sub,extra=_distance_scope(pack,'B1_30Hz',ix); models+=extra; detail.append(sub)
                suspect|=far&((matrix(sub,'master_ratio')<=1).sum(1)>=3)
            result[normal&~suspect]='false_candidate'; result[suspect]='true_suspect'
            query['decision']=result; query['model']='거리 보완 기준' if guard else '거리 보수 기준'; query['experiment']='distance'
            query['positive_score']=np.nan; query['in_training']=False; query['seed']=pack['settings'].seed
            decisions.append(query.reset_index()); detail.append(full)
            artifacts[pos]={'models':models,'features':pack['features'],'guard':guard}
        except ValueError as e: notes.append(f'위치{pos} 거리 분석 건너뜀: {e}')
    return {'predictions':pd.concat(decisions,ignore_index=True) if decisions else pd.DataFrame(),
            'details':pd.concat(detail,ignore_index=True) if detail else pd.DataFrame(),'models':artifacts,'notes':notes}

def classifier(name,settings,y,checkpoint=None):
    if name=='RandomForest':
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(n_estimators=200,max_depth=4,min_samples_leaf=2,class_weight='balanced',random_state=settings.seed,n_jobs=2)
    if name=='XGBoost':
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=200,max_depth=2,learning_rate=.03,min_child_weight=1,reg_lambda=10,subsample=.8,colsample_bytree=.8,
                             scale_pos_weight=float((y==0).sum()/(y==1).sum()),objective='binary:logistic',eval_metric='logloss',tree_method='hist',base_score=.5,random_state=settings.seed,n_jobs=2)
    if name!='TabICLv2': raise ValueError(name)
    from tabicl import TabICLClassifier
    if not checkpoint or not Path(checkpoint).is_file(): raise ValueError('공식 TabICLv2 체크포인트를 준비하세요. 선택 가이드를 확인하세요.')
    return TabICLClassifier(n_estimators=4,batch_size=1,device='cpu',use_amp=False,use_fa3=False,n_jobs=2,random_state=settings.seed,
                           checkpoint_version='tabicl-classifier-v2-20260212.ckpt',model_path=str(Path(checkpoint).resolve()),verbose=False)

def train_models(packs, names=('RandomForest','XGBoost'), experiments=('master_proxy','company_direct'), checkpoint=None):
    predictions=[]; models={}; notes=[]; importance=[]
    for pos,pack in packs.items():
        r,X,s=pack['rows'],pack['X'],pack['settings']
        for experiment in experiments:
            mask=(r.company_train if experiment=='company_direct' else r.proxy_train).to_numpy()
            y=(r.field_label.eq('field_true') if experiment=='company_direct' else r.master_train).to_numpy(int)[mask]
            if len(np.unique(y))<2:
                notes.append(f'위치{pos} / {experiment}: 학습 데이터가 한 종류뿐이어서 생략했습니다.'); continue
            query=r.NG_query|r.test_OK_sample|(r.eligible&r.field_label.eq('NG_master')&~r.role.eq('train'))
            for name in names:
                clf=classifier(name,s,y,checkpoint); clf.fit(X[mask],y)
                f=r[query].copy(); positive=int(np.flatnonzero(np.asarray(clf.classes_)==1)[0]); prob=clf.predict_proba(X[query])[:,positive]
                f['positive_score']=prob; f['decision']=np.where(prob>=s.suspect_min,'true_suspect',np.where(prob<=s.false_max,'false_candidate','review'))
                f['in_training']=mask[np.flatnonzero(query)]; f['model']=name; f['experiment']=experiment; f['seed']=s.seed
                predictions.append(f)
                key=f'p{pos}_{experiment}_{name}'; models[key]={'estimator':clf,'features':pack['features'],'position':pos,'experiment':experiment,
                    'settings':asdict(s),'train_ids':r.loc[mask,'id'].tolist(),'train_positive':int(y.sum()),'train_negative':int((y==0).sum())}
                if hasattr(clf,'feature_importances_'):
                    for ft,v in zip(pack['features'],clf.feature_importances_): importance.append({'위치':pos,'학습 방식':experiment,'모델':name,**ft,'중요도':float(v)})
                print(f'위치 {pos} · {name} · {experiment}: 학습 {len(y):,}행 완료')
    return {'predictions':pd.concat(predictions,ignore_index=True) if predictions else pd.DataFrame(),'models':models,'notes':notes,'importance':pd.DataFrame(importance)}

def summarize(predictions):
    records=[]
    if predictions.empty: return pd.DataFrame()
    for (pos,exp,model),f in predictions.groupby(['position','experiment','model'],sort=False):
        for split,mask in [('전체 NG: 학습 포함',f.NG_evaluation),('시험 날짜 NG',f.NG_evaluation&f.role.eq('test')),
                           ('기업 진성: 학습 제외',f.NG_evaluation&f.field_label.eq('field_true')&~f.in_training),
                           ('기업 진성: 학습 포함',f.NG_evaluation&f.field_label.eq('field_true')&f.in_training)]:
            g=f[mask]; t=g.field_label.eq('field_true'); n=g.field_label.eq('field_false'); d=g.decision
            records.append({'위치':pos,'학습 방식':exp,'모델':model,'비교 구간':split,'진성 행':int(t.sum()),'진성 의심':int((t&d.eq('true_suspect')).sum()),
                '진성 보류':int((t&d.eq('review')).sum()),'진성을 가성 후보로':int((t&d.eq('false_candidate')).sum()),'가성 행':int(n.sum()),
                '가성 후보':int((n&d.eq('false_candidate')).sum()),'가성 보류':int((n&d.eq('review')).sum()),'가성을 진성 의심으로':int((n&d.eq('true_suspect')).sum())})
    return pd.DataFrame(records)

def predict_saved(bundle_path,csv_path):
    """Apply one trusted locally created model, without retraining or cross-position use."""
    from .data import load_csv
    bundle=joblib.load(bundle_path)  # Only load your own export; joblib is executable serialization.
    if not isinstance(bundle,dict) or not {'estimator','position','features','settings'}.issubset(bundle):
        raise ValueError('위치별 분류 모델(p1_... 또는 p2_... .joblib)을 선택하세요. distance_reference는 기준 보관용입니다.')
    df=load_csv(csv_path); r=df[df.position.eq(bundle['position'])].reset_index(drop=True)
    if r.empty: raise ValueError('모델과 같은 위치의 데이터가 없습니다.')
    schema=feature_schema(r)
    if schema!=bundle['features']: raise ValueError('학습 당시 주파수/블록/입력 컬럼이 다릅니다. 조건을 분리한 뒤 재학습하세요.')
    X=r[[f['column'] for f in schema]].to_numpy(float)
    valid=np.isfinite(X).all(1)&~r.yellow_any&r.max_value.notna()&r.max_value.ne(0)&~r.field_label.isin(['measurement_error','NG_master','color_on_OK_unverified','color_conflict','mapping_label_conflict','unmatched'])
    query=valid&r.equipment_label.eq('NG'); f=r.copy(); f['decision']='not_scored'; f['positive_score']=np.nan
    if query.any():
        clf=bundle['estimator']; p=clf.predict_proba(X[query])[:,int(np.flatnonzero(np.asarray(clf.classes_)==1)[0])]; s=bundle['settings']
        f.loc[query,'positive_score']=p; f.loc[query,'decision']=np.where(p>=s['suspect_min'],'true_suspect',np.where(p<=s['false_max'],'false_candidate','review'))
    f['판정']=f.decision.map({**DECISIONS,'not_scored':'분석 대상 아님'})
    return f[['id','date','time','position','equipment_label','field_label','positive_score','decision','판정']]

def export_run(output_dir,input_path,settings,packs,distance_result,ml_result,figures=None):
    """New timestamped folder, CSV for Excel, PNG for reports, model and audit manifest."""
    from datetime import datetime
    root=Path(output_dir); root.mkdir(parents=True,exist_ok=True)
    out=root/datetime.now().strftime('%Y%m%d_%H%M%S_%f'); out.mkdir()
    preds=pd.concat([x for x in [distance_result['predictions'],ml_result['predictions']] if not x.empty],ignore_index=True)
    table=summarize(preds); table.to_csv(out/'01_위치별_결과요약.csv',index=False,encoding='utf-8-sig')
    fields=['id','source_file','source_sheet','source_row','field_row','date','time','position','equipment_label','field_label','role','model','experiment','in_training','positive_score','decision']
    readable=preds[[c for c in fields if c in preds]].copy(); readable['판정']=readable.decision.map(DECISIONS)
    readable.to_csv(out/'02_행별_판정근거.csv',index=False,encoding='utf-8-sig')
    allrows=pd.concat([p['rows'] for p in packs.values()],ignore_index=True)
    allrows.loc[~allrows.eligible,['id','date','position','field_label','exclusion_reason']].to_csv(out/'03_제외행과_이유.csv',index=False,encoding='utf-8-sig')
    if not ml_result['importance'].empty: ml_result['importance'].to_csv(out/'04_모델별_입력중요도.csv',index=False,encoding='utf-8-sig')
    if not distance_result['details'].empty: distance_result['details'].to_csv(out/'05_거리기반_상세점수.csv',index=False,encoding='utf-8-sig')
    modeldir=out/'models'; modeldir.mkdir()
    for name,bundle in ml_result['models'].items(): joblib.dump(bundle,modeldir/(name+'.joblib'))
    if distance_result['models']: joblib.dump(distance_result['models'],modeldir/'distance_reference.joblib')
    for name,fig in (figures or {}).items(): fig.savefig(out/(name+'.png'),dpi=160,bbox_inches='tight',facecolor='white')
    manifest={'input_file':Path(input_path).name,'input_sha256':file_hash(input_path),'settings':asdict(settings),
              'versions':{p:importlib.metadata.version(p) for p in ['numpy','pandas','scikit-learn','xgboost','matplotlib','joblib']},
              'position_features':{str(pos):p['features'] for pos,p in packs.items()},
              'notes':distance_result['notes']+ml_result['notes'],
              'limitations':['진성 2행은 동일 날짜·카운터로 독립 제품 수 미확인.','시험 날짜에 기업 진성이 없어 진성 검출률을 평가할 수 없음.',
                             '30Hz 보완 기준은 기존 진성 확인 뒤 정한 사후 기준.','마스터 기반 모델은 마스터 유사성 학습이며 양산 진성/가성 일반화 미확정.',
                             '모델 점수는 보정된 실제 불량 확률이 아님. 후보 결과는 현장 재검토 필요.']}
    (out/'실행설정과_이력.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    import html
    body='<html lang="ko"><meta charset="utf-8"><title>ECT 실행 결과</title><style>body{font:16px/1.7 "Malgun Gothic",sans-serif;margin:35px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ddd}img{max-width:100%}</style><h1>ECT 위치별 분석 결과</h1><p>가성 후보·보류·진성 의심은 재검토 우선순위입니다. 전체 NG 수량에는 학습 데이터가 포함됩니다. 별도 날짜 시험 결과를 구분해서 보세요.</p>'
    body+=table.to_html(index=False,border=0)
    for name in (figures or {}): body+=f'<h2>{html.escape(name)}</h2><img src="{html.escape(name)}.png">'
    body+='<h2>해석 범위</h2><ul>'+''.join('<li>'+html.escape(v)+'</li>' for v in manifest['limitations'])+'</ul></html>'
    (out/'결과보고서.html').write_text(body,encoding='utf-8')
    print(f'저장 완료: {out.resolve()}')
    return out
