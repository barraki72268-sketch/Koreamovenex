"""Auditable company-facing categories; raw NG counts never depend on view filters."""
import numpy as np
import pandas as pd

STYLES={
    'MASTER':('#7951b0','*'),
    '기준자료 (최대값 0)':('#24934b','o'),
    '검사기 합격':('#2474cf','o'),
    '진성불량 의심':('#d32f2f','o'),
    '가성불량 후보':('#f28c28','o'),
    'FN 후보':('#c62828','X'),
    '보류':('#828b94','D'),
    '입력 확인 필요':('#899198','x'),
    'NG 미판정':('#a0a7af','o'),
}


def classify_rows(frame):
    r=frame.copy();idx=r.index
    maximum=pd.to_numeric(r.get('max_value',pd.Series(np.nan,index=idx)),errors='coerce')
    equipment=r.equipment_label;prediction=r.get('예측',pd.Series('',index=idx))
    zero=maximum.eq(0);master=r.master.astype(bool)&equipment.eq('NG')&~zero
    r['판정']=np.select([zero,master,prediction.eq('불량 의심 · FN 후보'),equipment.eq('OK'),
                          equipment.eq('NG')&prediction.eq('진성불량 의심'),equipment.eq('NG')&prediction.eq('가성불량 후보'),
                          equipment.eq('NG')&prediction.eq('판정 보류')],
                         ['기준자료 (최대값 0)','MASTER','FN 후보','검사기 합격','진성불량 의심','가성불량 후보','보류'],default='입력 확인 필요')
    score=pd.to_numeric(r.get('점수',pd.Series(np.nan,index=idx)),errors='coerce')
    scored=equipment.eq('NG')&~master&~zero
    r['진성유사점수(%)']=(score*100).where(scored)
    r['가성유사점수(%)']=((1-score)*100).where(scored)
    return r


def view_mask(rows,limit='all'):
    maximum=pd.to_numeric(rows.get('max_value',pd.Series(np.nan,index=rows.index)),errors='coerce')
    if limit=='full':return pd.Series(True,index=rows.index)
    if limit=='all':return ~maximum.eq(100)
    return maximum.between(0,float(limit),inclusive='both')


def ng_summary(bundle,rows,limit='full'):
    rows=classify_rows(rows);records=[]
    for key,g in rows.groupby(['line','product','position'],dropna=False,sort=False):
        ng=g[g.equipment_label.eq('NG')];counts=ng['판정'].value_counts()
        record={'라인':key[0],'품번':key[1],'위치':key[2],'MASTER':int(counts.get('MASTER',0)),
                '가성불량(추정)':int(counts.get('가성불량 후보',0)),'진성불량(추정)':int(counts.get('진성불량 의심',0)),
                '총 NG':len(ng),'PCA설명비율':np.nan,'보류':int(counts.get('보류',0)),
                '기준자료0(NG)':int(counts.get('기준자료 (최대값 0)',0)),'입력확인(NG)':int(counts.get('입력 확인 필요',0))}
        model=bundle['models'].get(key)
        if model is not None:record['PCA설명비율']=float(model['pca'].explained_variance_ratio_.sum())
        accounted=sum(record[c] for c in ('MASTER','가성불량(추정)','진성불량(추정)','보류','기준자료0(NG)','입력확인(NG)'))
        record.update({'분류합계':accounted,'집계검증':'일치' if accounted==len(ng) else '확인 필요',
                       '표시범위밖(NG)':int((~view_mask(ng,limit)).sum()),'전체검사행':len(g),
                       'AI미평가OK':int((g.equipment_label.eq('OK')&pd.to_numeric(g.get('점수',pd.Series(np.nan,index=g.index)),errors='coerce').isna()).sum())})
        records.append(record)
    return pd.DataFrame(records)


def detail_table(rows):
    r=classify_rows(rows)
    columns={'calendar_date':'검사일자','time':'시간','counter':'검사수량','line':'라인','product':'품번','판정':'판정',
             'equipment_label':'설비판정(원본)','position':'위치','max_value':'최대검출값','max_frequency':'MAX FRQ',
             'part_no':'Part_No','가성유사점수(%)':'가성유사점수(%)','진성유사점수(%)':'진성유사점수(%)',
             'PC1':'PC1','PC2':'PC2','source_file':'원본파일','source_sheet':'원본시트','source_row':'원본행',
             '설명':'판정설명','학습기준':'학습기준','검증구분':'검증구분','sample_id':'샘플ID'}
    columns['AI평가여부']='AI평가여부'
    for name in columns:
        if name not in r:r[name]=''
    return r[list(columns)].rename(columns=columns)


def styled_details(frame):
    def paint(row):
        red=row.get('판정') in ('진성불량 의심','FN 후보')
        return ['color:#c62828;font-weight:600' if red else '' for _ in row]
    return frame.style.apply(paint,axis=1).format(precision=3,na_rep='—')
