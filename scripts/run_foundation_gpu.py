"""Frozen-date MASTER-vs-equipment-OK proxy experiment. No production defect truth."""
import os
os.environ.setdefault('WANDB_MODE','disabled')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY','1')
os.environ.setdefault('DO_NOT_TRACK','1')
from pathlib import Path
import argparse,json,hashlib,time,traceback,gc,subprocess
import numpy as np,pandas as pd
import torch
from sklearn.metrics import roc_auc_score,average_precision_score
from tabicl import TabICLClassifier,FinetunedTabICLClassifier

VERSION='tabicl-classifier-v2-20260212.ckpt'
def digest(path):
 h=hashlib.sha256()
 with open(path,'rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def score_record(info,modelname,p,y,cap):
 decision=np.where(p>=.9,'MASTER 유사 높음',np.where(p<=.1,'MASTER 유사 낮음','보류'))
 decision[cap]='보류'
 positive=y==1;normal=y==0;unknown=y==-1
 rec={k:info[k] for k in ('id','profile','line','product','position','condition','test_date','train_master','train_OK')}
 rec.update(model=modelname,reference_conflict_OK=bool(info.get('reference_conflict_OK',False)),test_master=int(positive.sum()),test_OK=int(normal.sum()),test_unknown_NG=int(unknown.sum()))
 for mask,prefix in ((positive,'MASTER'),(normal,'OK'),(unknown,'NG')):
  for key,category in (('high','MASTER 유사 높음'),('review','보류'),('low','MASTER 유사 낮음')):
   rec[prefix+'_'+key]=int((mask&(decision==category)).sum())
 rec['new_saturation_MASTER']=int((positive&cap).sum())
 if positive.any() and normal.any():
  labeled=positive|normal
  rec['proxy_auc']=float(roc_auc_score(positive[labeled],p[labeled]))
  rec['proxy_AP']=float(average_precision_score(positive[labeled],p[labeled]))
  rec['MASTER_percentile_min']=float(min((p[normal]<=v).mean() for v in p[positive]))
  rec['MASTER_score_min']=float(p[positive].min());rec['MASTER_score_mean']=float(p[positive].mean())
 return rec,decision

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--work-dir',default='.');parser.add_argument('--ids',default='');parser.add_argument('--epochs',type=int,default=5);parser.add_argument('--output',default='results');parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
 assert os.environ.get('SLURM_JOB_ID'),'GPU execution must be inside a Slurm allocation'
 assert torch.cuda.is_available(),'Allocated CUDA GPU unavailable'
 torch.set_num_threads(1);torch.manual_seed(42);np.random.seed(42)
 base=Path(args.work_dir).resolve();out=base/args.output;out.mkdir(parents=True,exist_ok=True)
 checkpoint=base/'checkpoints'/VERSION
 assert checkpoint.is_file()
 commit=subprocess.check_output(['git','-C',str(base/'tabicl'),'rev-parse','HEAD'],text=True).strip()
 plan={'source_commit':commit,'checkpoint':VERSION,'checkpoint_sha256':digest(checkpoint),'experiment_script_sha256':digest(Path(__file__)),'compute_precision':'float32','torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(),'job_id':os.environ['SLURM_JOB_ID'],'epochs_max':args.epochs,'seed':42,'n_estimators':4,'preprocessing_variants':['official_default_outlier_threshold_4','preserve_rare_signal_threshold_1e6'],'fine_tune':'Only earliest-prior-date training with >=2 MASTER rows and a distinct prior validation date; 5 fixed max epochs, LR 1e-5, freeze column/row, validation log-loss, 3-epoch patience; full prior context restored for final inference','test_policy':'Frozen last date, never used for checkpoint selection. No tuning to current test results. Unknown NG is not assigned true/false labels. New test saturation triggers abstention for shaft.','limits':'MASTER is a proxy and may be repeated measurements of the same specimen. Crack first-row equipment OK conflicts remain provisional.'}
 write_json(out/'experiment_plan.json',plan)
 datasets=json.loads((base/'inputs/datasets.json').read_text(encoding='utf-8'));selected=set(args.ids.split(',')) if args.ids else None
 records=[];errors=[];timings=[]
 for info in datasets:
  if selected and info['id'] not in selected:continue
  key=info['id'];npz=base/'inputs'/(key+'.npz');assert digest(npz)==info['npz_sha256']
  a=np.load(npz,allow_pickle=False);X=a['X_train'];y=a['y_train'];Q=a['X_test'];truth=a['y_test'];dates=a['train_dates'];caps=a['test_saturation'].astype(bool)
  assert (dates<info['test_date']).all()
  print('DATASET',key,info['profile'],info['line'],info['position'],'MASTER',int(y.sum()),'query',len(Q),flush=True)
  query=pd.read_csv(base/'inputs'/(key+'_query.csv.gz'))
  configs=[('TabICLv2_pretrained_default',4.0),('TabICLv2_pretrained_preserve',1e6)]
  def infer_and_save(model,name):
   start=time.monotonic();prob=model.predict_proba(Q)[:,list(model.classes_).index(1)]
   assert np.isfinite(prob).all() and len(prob)==len(Q)
   rec,decision=score_record(info,name,prob,truth,caps)
   records.append(rec);timings.append({'id':key,'model':name,'predict_seconds':time.monotonic()-start})
   f=query.copy();f['score']=prob;f['decision']=decision;f['model']=name
   for field in ('profile','line','product','position','test_date'):f[field]=info[field]
   f.to_csv(out/(key+'_'+name+'_predictions.csv.gz'),index=False)
   pd.DataFrame(records).to_csv(out/'model_summary.csv',index=False)
   print('DONE',key,name,'MASTER',rec['MASTER_high'],rec['MASTER_review'],rec['MASTER_low'],'OK_high',rec['OK_high'],flush=True)
  for name,threshold in configs:
   model=None
   try:
    model=TabICLClassifier(n_estimators=4,batch_size=1,model_path=str(checkpoint),allow_auto_download=False,checkpoint_version=VERSION,device='cuda',use_amp=False,use_fa3=False,offload_mode='gpu',n_jobs=1,random_state=42,outlier_threshold=threshold,verbose=False)
    model.fit(X,y)
    infer_and_save(model,name)
    model.save(out/(key+'_'+name+'.pkl'),save_model_weights=False,save_training_data=True,save_kv_cache=False)
   except Exception as error:
    errors.append({'id':key,'model':name,'error':repr(error),'traceback':traceback.format_exc()});print('ERROR',key,name,repr(error),flush=True)
   finally:
    del model;gc.collect();torch.cuda.empty_cache()
  days=sorted(np.unique(dates))
  if len(days)<2:
   errors.append({'id':key,'model':'TabICLv2_finetuned','skip':'No separate pre-test validation date; no random same-date split invented.'})
   continue
  train=dates<days[-1];validation=dates==days[-1]
  if int(y[train].sum())<2 or not (y[validation]==1).any():
   errors.append({'id':key,'model':'TabICLv2_finetuned','skip':'Fewer than two training MASTER rows after chronological validation split; official context/query fine-tuning needs both classes.'})
   continue
  model=None;adapted=None
  try:
   # Preserve every validation MASTER; use a fixed cap of validation OKs.
   pos=np.flatnonzero(validation&(y==1));neg=np.flatnonzero(validation&(y==0))
   neg=neg[np.unique(np.linspace(0,len(neg)-1,min(len(neg),max(32,10*len(pos))),dtype=int))]
   val=np.r_[pos,neg];folder=out/(key+'_finetuned');folder.mkdir(exist_ok=True)
   write_json(folder/'split.json',{'training_dates':sorted(np.unique(dates[train]).tolist()),'validation_date':days[-1],'test_date':info['test_date'],'train_master':int(y[train].sum()),'validation_master':len(pos),'validation_OK':len(neg),'context_rows_after_finetune':len(y)})
   model=FinetunedTabICLClassifier(epochs=args.epochs,learning_rate=1e-5,n_estimators_finetune=2,n_estimators_validation=2,n_estimators_inference=4,finetune_ctx_query_ratio=.5,max_data_size=10000,early_stopping=True,patience=3,eval_metric='log_loss',save_interval=0,freeze_col=True,freeze_row=True,freeze_icl=False,model_path=str(checkpoint),allow_auto_download=False,checkpoint_version=VERSION,device='cuda',amp=False,random_state=42,outlier_threshold=1e6,verbose=True,wandb_kwargs=None,extra_classifier_kwargs={'use_fa3':False,'use_amp':False,'batch_size':1,'offload_mode':'gpu','n_jobs':1})
   start=time.monotonic();model.fit(X[train],y[train],X_val=X[val],y_val=y[val],output_dir=folder)
   timings.append({'id':key,'model':'TabICLv2_finetuned','fit_seconds':time.monotonic()-start,'best_prior_validation_metric':float(model._best_metric_)})
   # Save weights in plain inference format as well; optimizer state is not needed to predict.
   ck=torch.load(folder/'best.ckpt',map_location='cpu',weights_only=False)
   original_state=torch.load(checkpoint,map_location='cpu',weights_only=False)['state_dict']
   max_delta=max(float((v-original_state[k]).abs().max()) for k,v in ck['state_dict'].items() if v.is_floating_point())
   steps=max((float(v.get('step',0)) for v in ck.get('optimizer_state',{}).get('state',{}).values()),default=0)
   write_json(folder/'adaptation_audit.json',{'gradient_steps':steps,'max_parameter_delta_from_pretrained':max_delta,'best_weights_changed':max_delta>0,'checkpoint_sha256':digest(folder/'best.ckpt'),'test_not_used_for_selection':True})
   del original_state
   slim={'config':ck['config'],'state_dict':ck['state_dict']}
   torch.save(slim,folder/'inference.ckpt');del ck,slim
   del model;model=None;gc.collect();torch.cuda.empty_cache()
   adapted=TabICLClassifier(n_estimators=4,batch_size=1,model_path=str(folder/'inference.ckpt'),allow_auto_download=False,checkpoint_version=VERSION,device='cuda',use_amp=False,use_fa3=False,offload_mode='gpu',n_jobs=1,random_state=42,outlier_threshold=1e6,verbose=False)
   adapted.fit(X,y);infer_and_save(adapted,'TabICLv2_finetuned')
   adapted.save(folder/'context.pkl',save_model_weights=False,save_training_data=True,save_kv_cache=False)
  except Exception as error:
   errors.append({'id':key,'model':'TabICLv2_finetuned','error':repr(error),'traceback':traceback.format_exc()});print('ERROR',key,'finetune',repr(error),flush=True)
  finally:
   del model,adapted;gc.collect();torch.cuda.empty_cache()
  write_json(out/'errors_and_skips.json',errors);write_json(out/'timings.json',timings)
 write_json(out/'errors_and_skips.json',errors);write_json(out/'timings.json',timings)
 summary=pd.DataFrame(records);summary.to_csv(out/'model_summary.csv',index=False)
 if not summary.empty:print(summary.groupby(['profile','model'])[['test_master','MASTER_high','MASTER_review','MASTER_low','test_OK','OK_high']].sum().to_string(),flush=True)
 write_json(out/'COMPLETED.json',{'datasets':len(set(summary.id)) if len(summary) else 0,'successful_evaluations':len(summary),'errors':sum('error' in e for e in errors),'skips':sum('skip' in e for e in errors),'job_id':os.environ['SLURM_JOB_ID']})
 print('EXPERIMENT_COMPLETE',flush=True)
if __name__=='__main__':main()
