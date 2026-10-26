"""Private delivery exploration. Do not interpret master similarity as defect truth."""
from pathlib import Path
import json,datetime,shutil,html
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import RobustScaler
from sklearn.decomposition import PCA
from sklearn.covariance import LedoitWolf
from scipy.spatial.distance import cdist
from sklearn.metrics import roc_auc_score
import joblib
from ectlab.plots import style
from ectlab.pipeline import classifier,Settings,evenly_sample

COLORS={'설비 OK':'#8C9DAF','일반 NG (미확정)':'#DF952F','MASTER 기준시료 (식별·지침)':'#7951B0'}

def feature_frame(g,profile):
    features={};descriptions=[];drift=[]
    for slot in range(24 if profile=='shaft' else 30):
        fc=9+4*slot if profile=='shaft' else 10+2*slot
        freq=g[f'c{fc}'].astype(str)
        if freq.nunique()!=1:
            drift.append((slot+1,freq.value_counts().to_dict()));continue
        frequency=freq.iloc[0]
        if frequency in ('0','0.0','nan','None'):continue
        axes=[('X',fc+1),('Y',fc+2),('측정값',fc+3)] if profile=='shaft' else [('측정값',fc+1)]
        for axis,column in axes:
            name=f'B{slot//8+1}_{frequency}_{axis}' if profile=='shaft' else f'F{slot+1}_{frequency}'
            features[name]=pd.to_numeric(g[f'c{column}'],errors='coerce').to_numpy()
            descriptions.append({'feature':name,'slot':slot+1,'frequency':frequency,'axis':axis,'raw_column':f'c{column}'})
    if drift:raise ValueError('같은 위치에서 주파수 구성이 변경됨. 조건 분리가 필요함: '+str(drift))
    return pd.DataFrame(features,index=g.index),descriptions

def nearest(a,b):return cdist(a,b).min(axis=1)/np.sqrt(a.shape[1])

def run_delivery(input_folder,output_root,pca_only=False,on_progress=None,crack_day_start_hour=0,retain_figures=True):
    style();folder=Path(output_root)/('신규검증_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir(parents=True,exist_ok=False);(folder/'models').mkdir()
    inventory=[];master_table=[];pca_stats=[];predictions=[];modelstats=[];distance_rows=[];dropped=[];notes=[];figures={};lineage=[];feature_tables=[];sample_index=[];master_changes=[]
    for profile in ('crack','shaft'):
        source=Path(input_folder)/(profile+'_raw.csv.gz')
        if not source.is_file():continue
        raw=pd.read_csv(source,low_memory=False)
        schema=json.loads((Path(input_folder)/(profile+'_schema.json')).read_text(encoding='utf-8'));lineage.append(schema)
        raw['c6']=pd.to_numeric(raw.c6).astype(int)
        raw['c0']=pd.to_datetime(raw.c0).dt.strftime('%Y-%m-%d')
        for (line,product,position),group in raw.groupby(['c3','c4','c6'],sort=True):
            title=f'{"크랙" if profile=="crack" else "샤프트"}_{line}_{product}_위치{position}'
            title=title.replace('/','_').replace(chr(92),'_')
            if on_progress:on_progress('PCA 계산 중 · '+title)
            g=group.sort_values(['c0','source_sheet','source_row'],kind='stable').reset_index(drop=True).copy()
            if profile=='crack' and crack_day_start_hour:
                from ectlab.inspection_day import crack_inspection_days
                old_first=set(zip(g.groupby('c0').head(1).source_sheet,g.groupby('c0').head(1).source_row))
                g,master=crack_inspection_days(g,crack_day_start_hour)
                old=np.array([(row.source_sheet,row.source_row) in old_first for row in g.itertuples()])
                for i in np.flatnonzero(old!=master):
                    master_changes.append({'라인':line,'품번':product,'위치':position,'원본날짜':g.at[i,'calendar_date'],'시간':str(g.at[i,'c1']),'검사일':g.at[i,'c0'],'시트':g.at[i,'source_sheet'],'행':int(g.at[i,'source_row']),'기존MASTER':bool(old[i]),'수정MASTER':bool(master[i]),'설비판정':g.at[i,'c5']})
                first=np.flatnonzero(master)
                missing=set(g.c0)-set(g.loc[master,'c0'])
                if missing:notes.append(title+': '+','.join(sorted(missing))+' 검사일은 전일 말미 데이터만 있어 MASTER를 지정하지 않았습니다.')
            else:
                g['calendar_date']=g.c0
                first=g.groupby('c0').head(1).index.to_numpy();master=np.zeros(len(g),bool);master[first]=True
                if profile=='shaft':
                    master=g.c2.astype(str).str.contains('마스터|MASTER',case=False,regex=True).to_numpy()
                    first=np.flatnonzero(master)
            X,descriptions=feature_frame(g,profile)
            feature_tables.extend(dict(검사=profile,라인=line,품번=product,위치=position,**f) for f in descriptions)
            # The user's stated company instruction defines the first inspection as master.
            # Equipment OK and max=0 are preserved as conflicts, not overwritten as true labels.
            ok=g.c5.eq('OK').to_numpy()&~master;ng=g.c5.eq('NG').to_numpy()&~master
            labels=np.where(master,'MASTER 기준시료 (식별·지침)',np.where(ok,'설비 OK','일반 NG (미확정)'))
            saturation=np.isclose(X.to_numpy(),100,rtol=0,atol=1e-9)
            finite=np.isfinite(X).all(axis=1).to_numpy()&g.c7.ne(0).to_numpy()
            for i in first:
                master_table.append({'검사':profile,'라인':line,'품번':product,'위치':position,'날짜':g.at[i,'c0'],'원본날짜':g.at[i,'calendar_date'],'시간':str(g.at[i,'c1']),'시트':g.at[i,'source_sheet'],'행':int(g.at[i,'source_row']),'검사번호':str(g.at[i,'c2']),'설비판정':g.at[i,'c5'],'최대측정값':g.at[i,'c7'],'측정축100':int(saturation[i].sum()),'최대값100':bool(g.at[i,'c7']==100),'유효측정':bool(finite[i]),'마스터근거':'검사번호의 NG마스터 명시' if profile=='shaft' else str(crack_day_start_hour)+'시 검사일 경계 이후 첫 검사; 설비 OK/최대값0 충돌은 확인 필요'})
            base={'검사':profile,'라인':line,'품번':product,'위치':position}
            inventory.append(dict(base,측정행=len(g),검사일수=g.c0.nunique(),시작일=g.c0.min(),종료일=g.c0.max(),설비OK=int(g.c5.eq('OK').sum()),설비NG=int(g.c5.eq('NG').sum()),MASTER기준시료=int(master.sum()),일반NG=int(ng.sum()),입력수=X.shape[1],최대값0=int(g.c7.eq(0).sum()),최대값100=int(g.c7.eq(100).sum()),측정축100행=int(saturation.any(axis=1).sum()),X결측행=int((~finite).sum())))
            # Zero max does not invalidate nonzero shaft X/Y, unlike the older C10A export.
            if g.c7.eq(0).any():notes.append(title+': 최대값 0인 '+str(int(g.c7.eq(0).sum()))+'행은 판정 불명으로 PCA/ML에서 제외. 원본 X/Y는 보존하며 최대값 산출 방식 확인 필요.')
            if g.loc[first,'c5'].ne('NG').any():notes.append(title+': 첫 검사에 설비 OK가 있음. 기준시료 가정과 설비 판정 불일치를 확인해야 함.')
            variants=[('전체 측정값',np.ones(X.shape[1],bool))]
            if profile=='shaft':
                saturated_slots={f['slot'] for j,f in enumerate(descriptions) if f['axis']=='측정값' and saturation[finite,j].any()}
                clean=np.array([f['slot'] not in saturated_slots for f in descriptions])
                xy=np.array([f['axis'] in ('X','Y') for f in descriptions])
                extreme=np.isclose(np.abs(X.to_numpy()),32767,rtol=0,atol=1e-9)
                guarded_slots=saturated_slots|{f['slot'] for j,f in enumerate(descriptions) if extreme[finite,j].any()}
                guard=np.array([f['slot'] not in guarded_slots for f in descriptions])
                variants.extend([('100측정값 채널 전체 제외',clean),('X_Y만 사용',xy),('100·32767 채널 전체 제외',guard)])
                for col in X.columns[~clean]:dropped.append(dict(base,제외축=col,백값행수=int(saturation[:,X.columns.get_loc(col)].sum()),제외범위='전체 파일 탐색 PCA'))
            fig,axes=plt.subplots(2,2,figsize=(14,11.2),squeeze=False) if profile=='shaft' else plt.subplots(1,1,figsize=(7,5.6),squeeze=False)
            for ax,(variant,mask) in zip(axes.ravel(),variants):
                A=X.loc[:,mask].to_numpy();valid=np.isfinite(A).all(axis=1)&g.c7.ne(0).to_numpy()
                from ectlab.sample_reports import write_delivery_samples
                entry=write_delivery_samples(folder,title,variant,g,X,mask,valid,master,labels,profile,line,product,position)
                sample_index.append(entry)
                if A.shape[1]<2 or valid.sum()<3:
                    ax.text(.5,.5,f'PCA 불가: 남은 입력 {A.shape[1]}개',ha='center');continue
                fitok=ok&valid
                scaler=RobustScaler().fit(A[fitok] if fitok.sum()>=3 else A[valid]);Z=scaler.transform(A[valid]);pca=PCA(n_components=2).fit(Z);P=pca.transform(Z)
                labs=labels[valid]
                for label,color in COLORS.items():
                    ix=np.flatnonzero(labs==label);show=evenly_sample(ix,2000)
                    ax.scatter(P[show,0],P[show,1],s=130 if 'MASTER' in label else 14,marker='*' if 'MASTER' in label else 'o',c=color,alpha=1 if 'MASTER' in label else .55,label=f'{label} ({len(ix):,}행)')
                ax.set(title=f'{line} / 위치 {position} / {variant}\n입력 {A.shape[1]}개 · 2축 설명 비율 {pca.explained_variance_ratio_.sum()*100:.1f}%',xlabel='PC1',ylabel='PC2');ax.legend(fontsize=7);ax.grid(alpha=.15)
                pca_stats.append(dict(base,조건=variant,사용행=int(valid.sum()),입력수=A.shape[1],설명비율=float(pca.explained_variance_ratio_.sum()),MASTER행=int((master&valid).sum())))
                coords=g.loc[valid,['c0','c1','c2','source_sheet','source_row']].copy();coords['구분']=labs;coords['PC1']=P[:,0];coords['PC2']=P[:,1];coords.to_csv(folder/(title+'_'+variant+'_PCA좌표.csv'),index=False,encoding='utf-8-sig')
            fig.suptitle('MASTER 기준시료에 대한 탐색 — 일반 NG의 진성·가성 미확정',fontsize=12);fig.tight_layout();fig.savefig(folder/(title+'_PCA.png'),dpi=140,bbox_inches='tight');figures[title+'_PCA']=fig if retain_figures else folder/(title+'_PCA.png');plt.close(fig)
            if pca_only:continue
            days=sorted(g.c0.unique());testday=days[-1];train=g.c0.lt(testday).to_numpy();test=g.c0.eq(testday).to_numpy()
            # Train only on preceding dates. No random row splitting or reuse of held-out master.
            confirmed_reference=~(master & g.c5.ne('NG').to_numpy()) if profile=='crack' and crack_day_start_hour else np.ones(len(g),bool)
            trainmaster=master&train&finite&confirmed_reference;trainok=ok&train&finite;testmaster=master&test&finite&confirmed_reference
            train100=np.isclose(X.to_numpy()[train&finite],100,rtol=0,atol=1e-9).any(axis=0)
            mlvariants=[('전체 측정값',np.ones(X.shape[1],bool))]
            if profile=='shaft':
                train_saturated={f['slot'] for j,f in enumerate(descriptions) if f['axis']=='측정값' and train100[j]}
                clean=np.array([f['slot'] not in train_saturated for f in descriptions])
                extreme=np.isclose(np.abs(X.to_numpy()[train&finite]),32767,rtol=0,atol=1e-9).any(axis=0)
                guarded_slots=train_saturated|{f['slot'] for j,f in enumerate(descriptions) if extreme[j]}
                guard=np.array([f['slot'] not in guarded_slots for f in descriptions])
                mlvariants.extend([('학습일100채널 제외',clean),('X_Y만 사용',xy),('학습일100·32767채널 제외',guard)])
            for variant,mask in mlvariants:
                features=list(X.columns[mask]);A=X[features].to_numpy()
                if len(features)<2 or trainmaster.sum()<1 or trainok.sum()<3:
                    notes.append(title+'/'+variant+': 학습 MASTER·OK 또는 남은 입력 부족으로 ML 생략.');continue
                valid=np.isfinite(A).all(axis=1)&g.c7.ne(0).to_numpy()
                trainmaster=master&train&valid&confirmed_reference;trainok=ok&train&valid;testmaster=master&test&valid&confirmed_reference
                okindices=evenly_sample(np.flatnonzero(trainok),1500);indices=np.r_[np.flatnonzero(trainmaster),okindices]
                y=master[indices].astype(int);query=np.flatnonzero((ng|testmaster|(ok&test))&valid)
                if len(np.unique(y))<2:continue
                settings=Settings(c10a_retrospective_guard=False)
                for modelname in ('RandomForest','XGBoost'):
                    clf=classifier(modelname,settings,y);clf.fit(A[indices],y)
                    prob=clf.predict_proba(A[query])[:,list(clf.classes_).index(1)]
                    cats=np.where(prob>=.9,'기준시료 유사 높음',np.where(prob<=.1,'기준시료 유사 낮음','보류'))
                    new_saturation=np.zeros(len(query),bool)
                    if profile=='shaft' and variant=='학습일100·32767채널 제외':
                        for f in descriptions:
                            if f['feature'] not in features:continue
                            values=X[f['feature']].to_numpy()[query]
                            new_saturation |= np.isclose(np.abs(values),32767,rtol=0,atol=1e-9)
                            if f['axis']=='측정값':new_saturation |= np.isclose(values,100,rtol=0,atol=1e-9)
                        new_saturation &= test[query]
                        cats[new_saturation]='보류'
                    if profile=='crack' and crack_day_start_hour:cats[master[query]&g.c5.ne('NG').to_numpy()[query]]='보류'
                    out=g.iloc[query][['c0','c1','c2','c5','c7','source_sheet','source_row']].copy()
                    for k,v in base.items():out[k]=v
                    out['조건']=variant;out['모델']=modelname;out['구분']=labels[query];out['구간']=np.where(test[query],'마지막 날짜 시험','이전 날짜 (학습일 포함)');out['점수']=prob;out['결과']=cats;out['학습포함']=np.isin(query,indices);out['시험일_추가포화']=new_saturation
                    predictions.append(out)
                    p=prob[testmaster[query]];o=prob[ok[query]&test[query]];n=prob[ng[query]&test[query]]
                    pc=cats[testmaster[query]];oc=cats[ok[query]&test[query]];nc=cats[ng[query]&test[query]]
                    auc=roc_auc_score(np.r_[np.ones(len(p)),np.zeros(len(o))],np.r_[p,o]) if len(p) and len(o) else np.nan
                    modelstats.append(dict(base,조건=variant,모델=modelname,입력수=len(features),학습MASTER=int(trainmaster.sum()),학습OK=len(okindices),학습최종일=max(g.loc[train,'c0']),시험일=testday,시험MASTER=len(p),MASTER점수=float(np.mean(p)) if len(p) else np.nan,MASTER높음=int((pc=='기준시료 유사 높음').sum()),MASTER보류=int((pc=='보류').sum()),MASTER낮음=int((pc=='기준시료 유사 낮음').sum()),시험OK=len(o),OK중높음=int((oc=='기준시료 유사 높음').sum()),시험일반NG=len(n),NG높음=int((nc=='기준시료 유사 높음').sum()),NG보류=int((nc=='보류').sum()),NG낮음=int((nc=='기준시료 유사 낮음').sum()),MASTER대OK_AUC=auc))
                    joblib.dump({'estimator':clf,'features':features,'profile':profile,'position':int(position),'line':line,'product':product,'train_ids':g.iloc[indices][['source_sheet','source_row']].to_dict('records'),'target':'first inspection MASTER assumption vs equipment OK, not true/false defect','test_date':testday},folder/'models'/(title+'_'+variant+'_'+modelname+'.joblib'))
                # Existing four distance families, trained on prior-day OK and masters only.
                scaler=RobustScaler().fit(A[trainok]);Z=scaler.transform(A)
                normalref=Z[okindices];masterref=Z[trainmaster]
                pcam=PCA(n_components=.95,svd_solver='full').fit(Z[np.flatnonzero(trainok)])
                whiten=LedoitWolf().fit(Z[okindices]);ew,ev=np.linalg.eigh(whiten.covariance_);W=ev@np.diag(1/np.sqrt(np.maximum(ew,1e-8)))
                spaces={'robust_l2':Z,'shrink_mahal':Z@W,'pca95':pcam.transform(Z),'cosine':Z/np.maximum(np.linalg.norm(Z,axis=1)[:,None],1e-12)}
                q=np.flatnonzero((ng|testmaster|(ok&test))&valid)
                # A master-near threshold cannot be estimated from one training master.
                for method,F in spaces.items():
                    dm=nearest(F[q],F[trainmaster]);do=nearest(F[q],F[okindices]);cal=evenly_sample(np.flatnonzero(trainok),1000)
                    # Leave-one-out OK distances avoid trivial self-neighbour zero.
                    D=cdist(F[cal],F[okindices])/np.sqrt(F.shape[1]);D[cal[:,None]==okindices[None,:]]=np.inf;ot=max(float(np.quantile(D.min(axis=1),.99)),1e-8)
                    mi=np.flatnonzero(trainmaster);mc=[]
                    for i in mi:
                        other=mi[g.loc[mi,'c0'].ne(g.at[i,'c0']).to_numpy()]
                        if len(other):mc.append(nearest(F[[i]],F[other])[0])
                    mt=max(float(np.quantile(mc,.95)),1e-8) if len(mc)>=3 else np.nan
                    out=g.iloc[q][['c0','c1','source_sheet','source_row']].copy()
                    for k,v in base.items():out[k]=v
                    out['조건']=variant;out['기법']=method;out['구분']=labels[q];out['시험일여부']=test[q];out['MASTER거리']=dm;out['OK거리']=do;out['OK거리99기준']=ot;out['MASTER거리95기준']=mt
                    out['해석']=np.where(do<=ot,'OK분포 안/근처','OK분포 밖') if np.isnan(mt) else np.where(dm<=mt,'MASTER 근처',np.where(do>ot,'MASTER·OK 모두 멂','OK 근처/경계'))
                    out['확정진성가성']='미확정';distance_rows.append(out)
                print(title,variant,'MASTER train/test',trainmaster.sum(),testmaster.sum(),'NG',ng.sum(),flush=True)
    if not inventory:raise ValueError('분석할 크랙·샤프트 파일이 없습니다. Excel을 먼저 선택하세요.')
    if not retain_figures:
        # Finished group arrays and canvases need not coexist with final table copies.
        raw=group=g=X=A=Z=F=spaces=normalref=masterref=D=P=coords=fig=axes=ax=scaler=pca=pcam=whiten=W=ev=ew=clf=None
        from ectlab.memory import release_working_memory
        release_working_memory()
    ml_table=pd.concat(predictions,ignore_index=True) if predictions else pd.DataFrame()
    predictions.clear()
    distance_table=pd.concat(distance_rows,ignore_index=True) if distance_rows else pd.DataFrame()
    distance_rows.clear()
    tables={'01_데이터수량':pd.DataFrame(inventory),'02_MASTER가정_확인표':pd.DataFrame(master_table),'03_PCA요약':pd.DataFrame(pca_stats),'04_ML_마지막날짜시험':pd.DataFrame(modelstats),'05_ML_행별점수':ml_table,'06_거리4종_행별점수':distance_table,'07_100값_제외축':pd.DataFrame(dropped),'08_입력변수정의':pd.DataFrame(feature_tables)}
    tables['12_크랙_MASTER변경']=pd.DataFrame(master_changes)
    from ectlab.sample_reports import finish_delivery_samples
    finish_delivery_samples(folder,sample_index,tables['05_ML_행별점수'],crack_day_start_hour)
    for name,table in tables.items():table.to_csv(folder/(name+'.csv'),index=False,encoding='utf-8-sig')
    pd.DataFrame({'확인사항':notes}).to_csv(folder/'09_확인사항.csv',index=False,encoding='utf-8-sig')
    # Summary graph compares model scores, not claimed defect-detection accuracy.
    stats=tables['04_ML_마지막날짜시험']
    if not stats.empty:
        for profile in ('crack','shaft'):
            t=stats[stats['검사'].eq(profile)]
            if t.empty:continue
            fig,ax=plt.subplots(figsize=(12,max(4,len(t)*.25)))
            y=np.arange(len(t));names=t.apply(lambda r:f'{r["라인"]} P{r["위치"]} / {r["조건"]} / {r["모델"]}',axis=1)
            ax.barh(y,t['MASTER점수'],color=np.where(t['MASTER점수']>=.9,'#7951B0',np.where(t['MASTER점수']<=.1,'#DA9B30','#8C9DAF')));ax.set(yticks=y,yticklabels=names,xlim=(0,1),xlabel='마지막 날짜 MASTER 기준시료의 평균 모델 점수 (실제 불량 확률 아님)',title=('크랙' if profile=='crack' else '샤프트')+' · 이전 날짜로 학습한 뒤 마지막 날짜에서 확인');ax.axvline(.9,c='#7951B0',ls='--');ax.axvline(.1,c='#DA9B30',ls='--');fig.tight_layout();name=profile+'_ML_MASTER점수';fig.savefig(folder/(name+'.png'),dpi=140,bbox_inches='tight');figures[name]=fig if retain_figures else folder/(name+'.png');plt.close(fig)
    disclaimer='크랙은 '+str(crack_day_start_hour)+'시를 검사일 경계로 사용하며 경계 이후 첫 검사 건을 MASTER 후보로 가정합니다. 경계 이전 새벽 측정은 전일에 속하고 전일 말미 데이터만 있으면 MASTER를 지정하지 않습니다. 샤프트는 검사번호에 NG마스터로 명시된 행을 우선 사용합니다. 일반 NG의 진성·가성 라벨은 없습니다. RF·XGBoost 점수는 MASTER 대 설비 OK의 유사성 점수이며 실제 불량 확률이나 진성·가성 정확도가 아닙니다. 학습은 마지막 날짜 이전 자료만 사용했습니다. 시험 MASTER가 적고 동일 기준시료의 반복 측정일 수 있어 일반화 성능을 입증하지 못합니다. 32767 반복값은 포화·상한 의심값으로 보고 별도의 보수적 비교에서 해당 채널도 제외합니다. 확정된 장비 사양은 아닙니다. 샤프트 100 제외는 측정값이 +100인 주파수 채널의 X/Y/측정값을 함께 제외하는 보수적 비교입니다. 원시 X/Y에는 100을 넘는 정상 값도 있어 단순 100 이상 잘라내기를 하지 않습니다. 최대값 0행은 판정 불명으로 제외합니다. C10A 보완 기준과 기존 모델은 형식·품번이 달라 그대로 적용하지 않았습니다. 거리 4종은 기존과 같은 방법 계열이지만 마스터가 적어 기존의 95% 임계값 판정은 만들지 못한 경우가 있으며 참고 거리로 제공합니다.'
    body='<html lang="ko"><meta charset="utf-8"><title>10월 26일 신규 자료 검증</title><style>body{font:16px/1.8 sans-serif;margin:30px;color:#18283c}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #ccd4dd;padding:7px}img{max-width:100%}.note{background:#fff2d6;padding:16px}</style><h1>신규 크랙·샤프트 자료 검증</h1><p class="note">'+disclaimer+'</p>'
    for name in ('01_데이터수량','02_MASTER가정_확인표','04_ML_마지막날짜시험'):
        body+='<h2>'+html.escape(name)+'</h2>'+tables[name].to_html(index=False)
    body+='<h2>주요 확인사항</h2>'+''.join('<p>'+html.escape(n)+'</p>' for n in notes)
    for name in figures:body+='<h2>'+html.escape(name)+'</h2><img src="'+html.escape(name)+'.png">'
    (folder/'검증보고서.html').write_text(body,encoding='utf-8')
    (folder/'원본구조와해시.json').write_text(json.dumps(lineage,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'분석기준.json').write_text(json.dumps({'crack_day_start_hour':crack_day_start_hour,'limits':disclaimer,'notes':notes,'source_code_sha256':__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),'seed':42},ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copyfile(__file__,folder/'재현코드.py')
    archive=Path(shutil.make_archive(str(folder),'zip',root_dir=folder))
    return {'folder':folder,'zip':archive,'tables':tables,'figures':figures,'notes':notes,'sample_index':sample_index}
