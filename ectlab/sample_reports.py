"""Portable per-measurement results and exploratory distances, never final labels."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.preprocessing import RobustScaler
from sklearn.decomposition import PCA
from ectlab.pipeline import evenly_sample


def reference_coordinates(A,valid,normal,master):
    ids=np.flatnonzero(valid)
    coords=np.full((len(A),3),np.nan);dm=np.full(len(A),np.nan);do=dm.copy()
    if not len(ids) or not A.shape[1]:return coords,dm,do,[]
    scaler=RobustScaler().fit(A[valid&normal] if (valid&normal).sum()>=3 else A[valid])
    Z=scaler.transform(A[valid]);n=min(3,*Z.shape)
    if n>=2:
        pca=PCA(n_components=n).fit(Z);coords[ids,:n]=pca.transform(Z)
        ratios=pca.explained_variance_ratio_.tolist()
    else:ratios=[]
    for target,out in ((normal,do),(master,dm)):
        ref=np.flatnonzero(target[ids])
        if target is normal:ref=evenly_sample(ref,512)
        if not len(ref):continue
        for start in range(0,len(ids),512):
            q=np.arange(start,min(start+512,len(ids)))
            D=cdist(Z[q],Z[ref])/np.sqrt(Z.shape[1])
            D[q[:,None]==ref[None,:]]=np.inf
            values=D.min(axis=1);values[~np.isfinite(values)]=np.nan
            out[ids[q]]=values
    return coords,dm,do,ratios


def write_delivery_samples(folder,title,variant,g,X,mask,valid,master,labels,profile,line,product,position):
    folder=Path(folder);(folder/'samples').mkdir(exist_ok=True)
    valid=valid & (int(np.asarray(mask).sum())>=2)
    coords,dm,do,ratios=reference_coordinates(X.loc[:,mask].to_numpy(),valid,g.c5.eq('OK').to_numpy()&~master,master&g.c5.eq('NG').to_numpy() if profile=='crack' else master)
    rows=pd.DataFrame({'샘플ID':[profile+'|'+str(sheet)+'|'+str(row)+'|P'+str(position) for sheet,row in zip(g.source_sheet,g.source_row)],
        '검사':profile,'라인':line,'품번':product,'위치':position,'원본날짜':g.calendar_date,'시간':g.c1.astype(str),'검사일':g.c0,
        '검사번호':g.c2.astype(str),'원본시트':g.source_sheet,'원본행':g.source_row,'설비판정':g.c5,'표시구분':labels,
        'MASTER여부':master,'MASTER판정충돌':master&g.c5.ne('NG').to_numpy(),'현장판정':'미확정','조건':variant,
        '분석가능':valid,'제외사유':np.where(g.c7.eq(0),'최대측정값 0',np.where(valid,'','결측/유효 입력 부족')),
        'PC1':coords[:,0],'PC2':coords[:,1],'PC3':coords[:,2],'NG_MASTER거리':dm,'OK거리':do})
    rows['거리참고']=np.where(~valid,'분석 제외',np.where(~np.isfinite(dm)|~np.isfinite(do),'비교 기준 부족',np.where(dm<do,'MASTER 쪽에 더 가까움','OK 쪽에 더 가까움')))
    name='samples/'+title+'_'+variant+'.csv.gz'
    rows.to_csv(folder/name,index=False,compression={'method':'gzip','compresslevel':3})
    return {'file':name,'profile':profile,'line':str(line),'product':str(product),'position':int(position),'condition':variant,
            'features':list(X.columns[mask]),'ratios':ratios,'rows':len(rows)}


def finish_delivery_samples(folder,index,predictions,start_hour):
    folder=Path(folder)
    mapping={'100측정값 채널 전체 제외':'학습일100채널 제외','100·32767 채널 전체 제외':'학습일100·32767채널 제외'}
    for entry in index:
        path=folder/entry['file'];rows=pd.read_csv(path,low_memory=False)
        for model,short in [('RandomForest','RF'),('XGBoost','XGBoost')]:
            rows[short+'점수']=np.nan;rows[short+'결과']='미계산'
            rows[short+'학습포함']=False;rows[short+'구간']='미계산'
            if predictions.empty:continue
            p=predictions[predictions['검사'].eq(entry['profile'])&predictions['라인'].astype(str).eq(entry['line'])&predictions['품번'].astype(str).eq(entry['product'])&predictions['위치'].eq(entry['position'])&predictions['조건'].eq(mapping.get(entry['condition'],entry['condition']))&predictions['모델'].eq(model)]
            if p.empty:continue
            p=p.set_index(['source_sheet','source_row'])
            key=pd.MultiIndex.from_frame(rows[['원본시트','원본행']])
            for source,dest in [('점수',short+'점수'),('결과',short+'결과')]:
                rows[dest]=p[source].reindex(key).to_numpy()
            rows[short+'결과']=rows[short+'결과'].fillna('미계산: 학습일 OK 또는 모델 조건 부족')
            rows[short+'학습포함']=p['학습포함'].reindex(key).fillna(False).to_numpy()
            rows[short+'구간']=p['구간'].reindex(key).fillna('미계산').to_numpy()
        rows.to_csv(path,index=False,compression={'method':'gzip','compresslevel':3})
    policy={'crack_day_start_hour':start_hour,'distance':'현재 파일의 유효 측정값을 OK 기준 RobustScaler로 변환한 뒤 최근접 유클리드 거리 / sqrt(입력수). 자기 자신은 기준에서 제외. OK 기준은 최대 512행. 전체 파일 탐색 거리이며 독립 시험 판정이 아님.',
            'decisions':'일반 NG의 진성·가성 미확정. RF·XGBoost는 MASTER 유사성. 학습일 OK 등에는 모델 점수가 없을 수 있음.',
            'reference_conflict':'크랙에서 MASTER 후보의 설비판정이 OK이면 탐색 거리 기준과 지도학습 양성 기준에서 제외합니다.',
            'sampling':'샘플 CSV는 제외행 포함 전체 측정행. 그림의 점 표시 제한과 구분.'}
    (folder/'샘플결과_목록.json').write_text(json.dumps({'entries':index,'policy':policy},ensure_ascii=False,indent=2),encoding='utf-8')
