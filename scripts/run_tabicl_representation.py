"""Frozen-day TabICLv2 representations, not a two-probability-column PCA."""
import os
os.environ.setdefault('WANDB_MODE','disabled')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY','1')
from pathlib import Path
import argparse,json,hashlib,subprocess,time,gc
import numpy as np,pandas as pd
import torch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import RobustScaler
from sklearn.manifold import TSNE
from sklearn.metrics import roc_auc_score,average_precision_score
from tabicl import TabICLClassifier

VERSION='tabicl-classifier-v2-20260212.ckpt'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reduce_space(X):
    pca=PCA(n_components=2,random_state=42).fit(X)
    return pca.transform(X),pca.explained_variance_ratio_.sum()


def tsne(X):
    if X.shape[1]>30:X=PCA(n_components=min(30,len(X)-1),random_state=42).fit_transform(X)
    return TSNE(n_components=2,perplexity=min(30,(len(X)-1)/3),max_iter=750,init='pca',learning_rate='auto',random_state=42,n_jobs=2).fit_transform(X)


def metrics(p,y,model,info):
    row={k:info[k] for k in ('id','line','product','position','test_date','train_master','train_OK')}
    row.update(model=model,test_MASTER=int((y==1).sum()),test_OK=int((y==0).sum()),unknown_NG=int((y==-1).sum()),conflict=int((y==-2).sum()))
    for code,name in [(1,'MASTER'),(0,'OK'),(-1,'NG')]:
        a=p[y==code]
        row[name+'_high']=int((a>=.9).sum());row[name+'_low']=int((a<=.1).sum());row[name+'_review']=int(((a>.1)&(a<.9)).sum())
        row[name+'_score_min']=float(a.min()) if len(a) else None
        row[name+'_score_max']=float(a.max()) if len(a) else None
    known=y>=0
    if (y==1).any() and (y==0).any():
        row['MASTER_OK_AUC']=float(roc_auc_score(y[known],p[known]))
        row['MASTER_OK_AP']=float(average_precision_score(y[known],p[known]))
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work-dir',required=True);parser.add_argument('--inputs',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();base=Path(args.work_dir);inputs=Path(args.inputs);output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    assert os.environ.get('SLURM_JOB_ID'),'Run GPU computation inside Slurm.'
    assert torch.cuda.is_available()
    torch.set_num_threads(2);torch.manual_seed(42);np.random.seed(42)
    checkpoint=base/'checkpoints'/VERSION
    assert sha(checkpoint)=='bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0'
    data=json.loads((inputs/'datasets.json').read_text(encoding='utf-8'))
    plan={'job_id':os.environ['SLURM_JOB_ID'],'gpu':torch.cuda.get_device_name(),'checkpoint':VERSION,'checkpoint_sha256':sha(checkpoint),'source_commit':subprocess.check_output(['git','-C',str(base/'tabicl'),'rev-parse','HEAD'],text=True).strip(),'script_sha256':sha(__file__),'representations':'Input to model_.icl_predictor.decoder[0], after the ICL transformer and final LayerNorm; query rows only; concatenated across ensemble members in their fixed order. Not probabilities or label vectors. Private PyTorch hook, pinned source.','protocol':'Same prior-day context IDs as RF. No query labels enter fit or feature extraction. Fixed 6am day boundary. Display subset: up to 1000 equipment OK plus all other last-day queries, same row IDs in all panels. PCA/tSNE fitted to display subset only for exploration, not classifier training. Seed42, perplexity30-or-less, 750 iterations. Both official clipping4 and preserve1e6 are pre-specified and reported, no best-looking view selection.','limits':'Test MASTER counts 0/1 per group; repeated specimen possible. General NG truth unknown. Conflicting equipment OK / MASTER candidates excluded from known-label metrics. Not defect accuracy. No additional gradient fine-tuning in this experiment.','skipped':data['skipped']}
    (output/'experiment_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[];audits=[]
    for info in data['datasets']:
        started=time.monotonic();key=info['id'];p=inputs/(key+'.npz');assert sha(p)==info['npz_sha256']
        a=np.load(p,allow_pickle=False);X=a['X_train'];y=a['y_train'];Q=a['X_test'];truth=a['y_test'];selected=a['plot_indices']
        assert (a['train_dates']<info['test_date']).all()
        query=pd.read_csv(inputs/(key+'_query.csv.gz'))
        for model,col in [('RandomForest','RF_score'),('XGBoost','XGBoost_score')]:rows.append(metrics(query[col].to_numpy(),truth,model,info))
        raw=RobustScaler().fit(X).transform(Q[selected]);raw_pca,raw_ratio=reduce_space(raw);raw_tsne=tsne(raw)
        for label,threshold in [('TabICLv2_default',4.),('TabICLv2_preserve',1e6)]:
            print('START',key,info['line'],info['position'],label,'context',len(X),'queries',len(Q),flush=True)
            model=TabICLClassifier(n_estimators=4,batch_size=1,model_path=str(checkpoint),allow_auto_download=False,checkpoint_version=VERSION,device='cuda',use_amp=False,use_fa3=False,offload_mode='gpu',n_jobs=2,random_state=42,outlier_threshold=threshold,verbose=False)
            model.fit(X,y);captured=[]
            def capture(module,args):
                tensor=args[0]
                assert tensor.ndim==3 and tensor.shape[1]==len(X)+len(Q),tensor.shape
                captured.append(tensor[:,-len(Q):,:].detach().float().cpu().numpy().copy())
            hook=model.model_.icl_predictor.decoder[0].register_forward_pre_hook(capture)
            try:prob=model.predict_proba(Q)[:,list(model.classes_).index(1)]
            finally:hook.remove()
            assert np.isfinite(prob).all()
            hidden=np.concatenate([member for block in captured for member in block],axis=1)
            assert hidden.shape[0]==len(Q) and hidden.shape[1]>2 and np.isfinite(hidden).all()
            # Verify instrumentation did not alter predictions, independently of plotting.
            check=model.predict_proba(Q[:min(16,len(Q))])[:,list(model.classes_).index(1)]
            np.testing.assert_allclose(check,prob[:len(check)],rtol=2e-3,atol=2e-4)
            hpca,hratio=reduce_space(hidden[selected]);htsne=tsne(hidden[selected])
            np.savez_compressed(output/(key+'_'+label+'_features.npz'),query_hidden=hidden,plot_indices=selected,raw_pca=raw_pca,raw_tsne=raw_tsne,hidden_pca=hpca,hidden_tsne=htsne)
            q=query.copy();q['TabICLv2_score']=prob;q['model']=label;q.to_csv(output/(key+'_'+label+'_scores.csv.gz'),index=False)
            rows.append(metrics(prob,truth,label,info))
            fig,axes=plt.subplots(2,2,figsize=(13,10))
            for ax,coords,title in zip(axes.ravel(),[raw_pca,raw_tsne,hpca,htsne],[f'Raw measurements / PCA ({raw_ratio:.1%})','Raw measurements / t-SNE',f'TabICLv2 hidden features / PCA ({hratio:.1%})',f'TabICLv2 hidden features / t-SNE ({hidden.shape[1]}D)']):
                for code,name,color,marker in [(0,'Equipment OK','#8C9DAF','o'),(-1,'NG (truth unknown)','#DF952F','o'),(1,'Held-out MASTER','#7951B0','*'),(-2,'MASTER/OK conflict','#D45B58','x')]:
                    mask=truth[selected]==code
                    if mask.any():ax.scatter(coords[mask,0],coords[mask,1],s=160 if code==1 else (75 if code==-2 else 18),c=color,marker=marker,alpha=.9 if code else .5,label=f'{name} ({int(mask.sum())})')
                ax.set_title(title);ax.set_xlabel('Axis 1');ax.set_ylabel('Axis 2');ax.legend(fontsize=8);ax.grid(alpha=.15)
            fig.suptitle(f'{info["line"]} / {info["product"]} / position {info["position"]} / {info["test_date"]}\n{label}: prior-day MASTER={info["train_master"]}; same held-out rows in every panel ({len(selected)}/{len(Q)})\nSeparation of reference samples is not true/false defect accuracy.',fontsize=11)
            fig.tight_layout();fig.savefig(output/(key+'_'+label+'_PCA_tSNE.png'),dpi=125,bbox_inches='tight');plt.close(fig)
            audit={'id':key,'model':label,'hidden_shape':list(hidden.shape),'forward_captures':len(captured),'hook_prediction_check_max_error':float(np.abs(check-prob[:len(check)]).max()),'query_labels_passed_to_model':False,'seconds':time.monotonic()-started};audits.append(audit)
            pd.DataFrame(rows).to_csv(output/'model_summary.csv',index=False)
            (output/'extraction_audit.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
            print('DONE',key,label,'hidden',hidden.shape,'MASTER',prob[truth==1].tolist(),flush=True)
            del model,captured,hidden;gc.collect();torch.cuda.empty_cache()
    print('ALL_DONE',len(data['datasets']),'datasets',len(audits),'representation runs',flush=True)


if __name__=='__main__':main()
