from pathlib import Path
import sys,json,tarfile,hashlib
import numpy as np,pandas as pd
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo))
from ectlab.delivery import feature_frame
import argparse
parser=argparse.ArgumentParser(description='06번 분석의 학습·시험 행을 고정해 GPU 입력을 만듭니다.')
parser.add_argument('--input-folder',required=True)
parser.add_argument('--analysis-folder',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(args.input_folder).resolve();prior=Path(args.analysis_folder).resolve()
dataout=Path(args.output).resolve();dataout.mkdir(parents=True,exist_ok=True)
frames={p:pd.read_csv(root/(p+'_raw.csv.gz'),low_memory=False) for p in ('crack','shaft')}
records=[]
for file in sorted((prior/'models').glob('*.metadata.json')):
 meta=json.loads(file.read_text(encoding='utf-8'))
 condition='전체 측정값' if meta['profile']=='crack' else '학습일100·32767채널 제외'
 if '_'+condition+'_' not in file.name:continue
 d=frames[meta['profile']]
 d=d[d.c3.eq(meta['line'])&d.c4.eq(meta['product'])&d.c6.eq(meta['position'])].sort_values(['c0','source_sheet','source_row'],kind='stable').reset_index(drop=True)
 x,features=feature_frame(d,meta['profile']);cols=meta['features']
 first=d.groupby('c0').head(1).index
 master=np.zeros(len(d),bool);master[first]=True
 if meta['profile']=='shaft':master=d.c2.astype(str).str.contains('마스터|MASTER',case=False,regex=True).to_numpy()
 lookup={(r.source_sheet,int(r.source_row)):i for i,r in d.iterrows()}
 train=np.array([lookup[(r['source_sheet'],int(r['source_row']))] for r in meta['train_ids']])
 valid=np.isfinite(x[cols]).all(axis=1).to_numpy()&d.c7.ne(0).to_numpy()
 test=np.flatnonzero(d.c0.eq(meta['test_date']).to_numpy()&valid)
 assert d.loc[train,'c0'].lt(meta['test_date']).all()
 y=master[train].astype(np.int64)
 yt=np.where(master[test],1,np.where(d.loc[test,'c5'].eq('OK'),0,-1)).astype(np.int64)
 a=x[cols].to_numpy()
 bad=np.zeros(len(d),bool)
 if meta['profile']=='shaft':
  for f in features:
   if f['feature'] not in cols:continue
   v=x[f['feature']].to_numpy()
   bad|=np.isclose(np.abs(v),32767,rtol=0,atol=1e-9)
   if f['axis']=='측정값':bad|=np.isclose(v,100,rtol=0,atol=1e-9)
 key=f'd{len(records):02d}'
 np.savez_compressed(dataout/(key+'.npz'),X_train=a[train].astype(np.float32),y_train=y,X_test=a[test].astype(np.float32),y_test=yt,train_dates=d.loc[train,'c0'].to_numpy(str),test_saturation=bad[test])
 t=d.iloc[test][['source_sheet','source_row','c0','c1','c2','c5','c7']].copy();t['reference_label']=yt;t['extra_saturation']=bad[test];t.to_csv(dataout/(key+'_query.csv.gz'),index=False)
 record={'id':key,'profile':meta['profile'],'line':meta['line'],'product':meta['product'],'position':meta['position'],'condition':condition,'features':cols,'test_date':meta['test_date'],'train_master':int(y.sum()),'train_OK':int((y==0).sum()),'test_master':int((yt==1).sum()),'test_OK':int((yt==0).sum()),'test_unknown_NG':int((yt==-1).sum()),'train_ids':meta['train_ids'],'master_rule':'explicit NG마스터' if meta['profile']=='shaft' else 'first inspection per date/position; conflicting equipment OK retained as provisional reference'}
 record['reference_conflict_OK']=bool((master&d.c5.eq('OK').to_numpy()).any())
 record['npz_sha256']=hashlib.sha256((dataout/(key+'.npz')).read_bytes()).hexdigest()
 records.append(record);print(key,record['profile'],record['line'],record['position'],'train master',y.sum(),'test',len(test),flush=True)
if not records:raise ValueError('GPU 입력으로 만들 모델이 없습니다. 06번 완료 후 models/*.metadata.json이 있는 결과 폴더를 지정하세요.')
(dataout/'datasets.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
for name in ('04_ML_마지막날짜시험.csv','10_모델비교_최종요약.csv'):
 (dataout/('baseline_'+name)).write_bytes((prior/name).read_bytes())
print('완료:',len(records),'개 조합 →',dataout)
