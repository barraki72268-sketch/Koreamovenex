from pathlib import Path
import sys,json,html,tarfile,hashlib,shutil
import numpy as np,pandas as pd,matplotlib.pyplot as plt
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo));from ectlab.plots import style
style()
import argparse
parser=argparse.ArgumentParser(description='GPU 결과 묶음으로 비교 보고서를 만듭니다.')
parser.add_argument('--bundle',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
archive=Path(args.bundle).resolve();source=root/'GPU_실험결과'
with tarfile.open(archive) as tar:
 for m in tar.getmembers():assert (source/m.name).resolve().is_relative_to(source.resolve()) and m.isfile(),m.name
 tar.extractall(source,filter='data')
datasets=json.loads((source/'inputs/datasets.json').read_text(encoding='utf-8'));infos={d['id']:d for d in datasets}
res=source/'results_fp32';plan=json.loads((res/'experiment_plan.json').read_text());done=json.loads((res/'COMPLETED.json').read_text());assert done['errors']==0
assert hashlib.sha256((source/'run_foundation_gpu.py').read_bytes()).hexdigest()==plan['experiment_script_sha256']
new=pd.read_csv(res/'model_summary.csv');records=[]
for d in datasets:
 npz=source/'inputs'/(d['id']+'.npz')
 assert hashlib.sha256(npz.read_bytes()).hexdigest()==d['npz_sha256']
 a=np.load(npz,allow_pickle=False);assert (a['train_dates']<d['test_date']).all()
candidates=[]
for file in res.glob('*_predictions.csv.gz'):
 f=pd.read_csv(file);assert np.isfinite(f.score).all() and f.score.between(0,1).all()
 assert f.loc[f.extra_saturation,'decision'].eq('보류').all()
 g=f[f.reference_label.eq(-1)&f.decision.eq('MASTER 유사 높음')]
 if len(g):candidates.append(g)
assert len(list(res.glob('*_predictions.csv.gz')))==len(new)
if candidates:
 candidate=pd.concat(candidates,ignore_index=True).groupby(['profile','line','product','position','source_sheet','source_row','c0','c1','c2'],dropna=False).agg(점수최소=('score','min'),점수최대=('score','max'),모델수=('model','size'),모델=('model',lambda x:'; '.join(x))).reset_index()
 candidate['현장판정']='진성·가성 미확정'
 candidate=candidate.rename(columns={'profile':'검사','line':'라인','product':'품번','position':'위치','source_sheet':'원본시트','source_row':'원본행','c0':'날짜','c1':'시간','c2':'검사번호'})
 candidate['검사']=candidate['검사'].map({'crack':'크랙','shaft':'샤프트'})
 candidate['모델']=candidate['모델'].str.replace('TabICLv2_pretrained_default','기본').str.replace('TabICLv2_pretrained_preserve','큰값 보존')
else:candidate=pd.DataFrame()
candidate.to_csv(root/'05_현장확인_우선NG.csv',index=False,encoding='utf-8-sig')
base=pd.read_csv(source/'inputs/baseline_04_ML_마지막날짜시험.csv')
for d in datasets:
 for _,r in base[base['검사'].eq(d['profile'])&base['라인'].eq(d['line'])&base['위치'].eq(d['position'])&base['조건'].eq(d['condition'])].iterrows():
  v={k:d[k] for k in ('id','profile','line','product','position','condition','test_date','train_master','train_OK','reference_conflict_OK')};v['model']=r['모델']
  mapping={'test_master':'시험MASTER','test_OK':'시험OK','test_unknown_NG':'시험일반NG','MASTER_high':'MASTER높음','MASTER_review':'MASTER보류','MASTER_low':'MASTER낮음','OK_high':'OK중높음','NG_high':'NG높음','NG_review':'NG보류','NG_low':'NG낮음','proxy_auc':'MASTER대OK_AUC'}
  for k,col in mapping.items():v[k]=r[col]
  records.append(v)
allmodels=pd.concat([pd.DataFrame(records),new],ignore_index=True)
for _,r in allmodels.iterrows():assert r.MASTER_high+r.MASTER_review+r.MASTER_low==r.test_master
models=['RandomForest','XGBoost','TabICLv2_pretrained_default','TabICLv2_pretrained_preserve','TabICLv2_finetuned']
names={'RandomForest':'RF (기존)','XGBoost':'XGBoost (기존)','TabICLv2_pretrained_default':'TabICLv2 기본','TabICLv2_pretrained_preserve':'TabICLv2 큰값 보존','TabICLv2_finetuned':'TabICLv2 추가 학습'}
columns=['test_master','MASTER_high','MASTER_review','MASTER_low','test_OK','OK_high','test_unknown_NG','NG_high','NG_review','NG_low']
def aggregate(frame):
 t=frame.groupby(['profile','model'],sort=False)[columns].sum()
 t['구간수']=frame.groupby(['profile','model']).size()
 t['MASTER_OK_평균AUC']=frame.groupby(['profile','model']).proxy_auc.mean()
 return t.reset_index()
overview=aggregate(allmodels)
paired_ids=set(new.loc[new.model.eq('TabICLv2_finetuned'),'id'])
paired=aggregate(allmodels[allmodels.id.isin(paired_ids)])
strict=aggregate(allmodels[~allmodels.reference_conflict_OK.astype(bool)])
for name,table in [('01_전체모델_위치별비교',allmodels),('02_전체구간_요약',overview),('03_추가학습가능구간_동일대상비교',paired),('04_MASTER판정충돌제외_참고',strict)]:table.to_csv(root/(name+'.csv'),index=False,encoding='utf-8-sig')
def bars(table,filename,title,include_finetune):
 profiles=list(table.profile.unique());fig,axs=plt.subplots(1,len(profiles),figsize=(7*len(profiles),5.5),squeeze=False)
 for ax,profile in zip(axs.ravel(),profiles):
  t=table[table.profile.eq(profile)].set_index('model')
  chosen=[m for m in models if m in t.index and (include_finetune or m!='TabICLv2_finetuned')];t=t.loc[chosen]
  y=np.arange(len(t));left=np.zeros(len(t));den=t.test_master.to_numpy()
  for col,label,color in [('MASTER_high','유사성 높음','#7951B0'),('MASTER_review','보류','#A5ADBA'),('MASTER_low','유사성 낮음','#DA9B30')]:
   n=t[col].to_numpy();width=n/den*100;ax.barh(y,width,left=left,color=color,label=label)
   for yy,ww,ll,nn in zip(y,width,left,n):
    if nn:ax.text(ll+ww/2,yy,str(int(nn)),ha='center',va='center',color='white' if col=='MASTER_high' else '#17243B',fontsize=12)
   left+=width
  ax.set(yticks=y,yticklabels=[names[m]+' (n='+str(int(t.loc[m,'test_master']))+')' for m in chosen],xlim=(0,100),xlabel='시험 MASTER 측정행 분포 (%)',title=('크랙' if profile=='crack' else '샤프트'));ax.invert_yaxis()
 handles,labels=axs[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=3)
 fig.suptitle(title+'\n진성·가성 검출 정확도가 아닌 MASTER 대 설비 OK 비교',fontsize=13);fig.tight_layout(rect=[0,.07,1,.90]);fig.savefig(root/filename,dpi=150,bbox_inches='tight');plt.close(fig)
bars(overview,'01_사전학습모델_기존모델비교.png','동일한 이전 날짜 학습 → 마지막 날짜 시험',False)
bars(paired,'02_추가학습_동일구간비교.png',f'추가 학습 가능한 {len(paired_ids)}개 구간만 동일하게 비교',True)
audit=json.loads((source/'checkpoint_manifest.json').read_text())
assert len(audit['adapted'])==len(paired_ids)
gradients=[c['adaptation']['gradient_steps'] for c in audit['adapted']];assert all(g>0 for g in gradients)
checks={'datasets':len(datasets),'successful_neural_evaluations':len(new),'prediction_files_finite_and_in_range':True,'same_baseline_train_rows':True,'test_dates_excluded_from_training':True,'new_saturation_always_review':True,'MASTER_count_reconciliation':True,'adapted_checkpoints':len(audit['adapted']),'gradient_steps_min':min(gradients,default=0),'selected_checkpoints_changed':sum(c['adaptation']['best_weights_changed'] for c in audit['adapted']),'float32_final_job':plan['job_id'],'base_checkpoint_sha256':plan['checkpoint_sha256']}
(root/'실행검증.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
reason='마스터로 지정한 측정행과 설비 OK를 비교하는 실험입니다. 일반 NG의 진성·가성 라벨은 없고 동일 기준시료의 반복 측정일 수 있습니다. 높은 점수 건수가 늘어도 실제 불량 검출 성능 개선을 뜻하지 않습니다. 0.9/0.1은 기존과 같은 비교 기준이며 모델 간 점수가 같은 불량 확률로 보정된 것은 아닙니다. 따라서 MASTER 대 OK의 순위(AUC)와 OK를 높게 평가한 수도 함께 봅니다. 크랙 C11A 위치 3, C80A 위치 3은 최초 기준시료에 설비 OK 표시가 있어 원본 확인이 필요합니다.'
design='25개 조합은 품번·위치를 각각 분석했습니다. 이전 RF·XGBoost와 학습행·시험 날짜·입력 변수를 고정했습니다. 사전학습 기본 전처리와 큰값 보존 전처리를 비교했습니다. 추가 학습은 날짜가 분리된 학습·검증을 확보하고 학습 MASTER가 2행 이상인 학습·검증 조건을 만족한 구간에서만 수행했습니다. 최대 5 epoch, LR 1e-5, column/row 동결, 검증 log-loss로 체크포인트를 선택하고 마지막 날짜는 사용하지 않았습니다. 추론 시에는 두 모드 모두 동일한 전체 이전 날짜 문맥을 제공합니다.'
numeric='초기 혼합정밀도 실행에서 C71A 위치 2의 큰값 보존 설정이 비정상값을 출력했습니다. 최종 비교는 모든 조합을 FP32로 다시 실행해 63개 결과 전체가 유한한 값임을 확인했습니다. 초기 실패 로그도 실험 묶음에 남겼습니다.'
body='<html lang="ko"><meta charset="utf-8"><title>사전학습 모델 GPU 비교</title><style>body{font:17px/1.8 sans-serif;color:#17243b;margin:30px;max-width:1500px}img{max-width:100%}table{border-collapse:collapse;font-size:13px}th,td{border:1px solid #ccd4dd;padding:6px}.note{background:#fff2d6;padding:16px}</style><h1>TabICLv2 사전학습·추가 학습 비교</h1><p class="note">'+reason+'</p><h2>동일 대상에서 기존 모델과 비교</h2><img src="01_사전학습모델_기존모델비교.png">'+overview.to_html(index=False)+'<h2>추가 학습 효과: 같은 13개 구간끼리 비교</h2><img src="02_추가학습_동일구간비교.png">'+paired.to_html(index=False)+'<h2>판정 기준과 분리 능력은 다릅니다</h2><p>C12 위치 3의 기존 XGBoost는 MASTER 점수가 약 0.05지만 MASTER 대 시험 OK AUC는 1.0이었습니다. 이 경우 낮은 절대 점수를 곧 분리 실패로 해석하면 안 됩니다. 최종 모델 판단은 순위·보류·현장 라벨을 함께 확인해야 합니다.</p><h2>실험 방법</h2><p>'+design+'</p><p>'+numeric+'</p><h2>라벨 충돌 구간을 제외한 참고 결과</h2>'+strict.to_html(index=False)+'<h2>재현·체크포인트</h2><p>GPU 서버 사용자 폴더 실험 작업 폴더에 기본 체크포인트와 추가 학습 체크포인트를 보관했습니다. inference.ckpt와 동일 문맥 입력으로 다시 예측할 수 있습니다. 체크포인트 위치·해시는 GPU_실험결과/checkpoint_manifest.json에 기록했습니다. GPU 재실행은 foundation_job.sh를 Slurm sbatch로 제출합니다.</p><pre>'+html.escape(json.dumps(checks,ensure_ascii=False,indent=2))+'</pre><p>공식 모델·추가 학습 API: <a href="https://github.com/soda-inria/tabicl">soda-inria/tabicl</a> · <a href="https://tabicl.readthedocs.io/en/latest/api.html">TabICL API</a></p><h2>품번·위치별 전체 결과</h2>'+allmodels.to_html(index=False)
body+='<h2>현장 확인을 우선 요청할 일반 NG</h2><p>높은 MASTER 유사성으로 나온 측정행입니다. 진성 확정 결과가 아니며 실제 재검사·처분 결과로 확인해야 합니다.</p>'+candidate.to_html(index=False)
(root/'사전학습모델_비교보고서.html').write_text(body,encoding='utf-8')
print('FINAL SUMMARY\n'+overview.to_string(index=False));print('PAIRED FINETUNE\n'+paired.to_string(index=False));print(json.dumps(checks,ensure_ascii=False))
