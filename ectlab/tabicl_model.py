"""Optional CPU-only TabICLv2 inference with fixed context and bounded memory."""
from pathlib import Path
from functools import lru_cache
import gc,hashlib,importlib.util,os,urllib.request
import numpy as np

VERSION='tabicl-classifier-v2-20260212.ckpt'
REVISION='4dcd344ece2c00be9e831fdd35bed57b5ad83e19'
SHA256='bdc7dbd5e4ff21f8f0456fcf90c6b7cdf72dbea960f2d05b19bec19f9b3d4ed0'
CODE_COMMIT='c91f00df184a5097e584cb376f7e699e9f3444c4'
CONTEXT_OK_LIMIT=256
QUERY_OK_LIMIT=128
QUERY_BATCH=64


def default_checkpoint():
    return Path.home()/'.mvx/models/tabicl'/VERSION


@lru_cache(maxsize=8)
def _verify(path,size,mtime):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=SHA256:raise ValueError('TabICLv2 체크포인트 해시가 다릅니다. 01번에서 TabICLv2 설치를 다시 진행하세요.')
    return Path(path)


def checkpoint_path(root=None):
    candidates=[]
    if os.environ.get('ECT_TABICL_CHECKPOINT'):candidates.append(Path(os.environ['ECT_TABICL_CHECKPOINT']))
    if root is not None:candidates.append(Path(root)/'checkpoints'/VERSION)
    candidates.append(default_checkpoint())
    for p in candidates:
        if p.is_file():
            stat=p.stat();return _verify(str(p.resolve()),stat.st_size,stat.st_mtime_ns)
    raise ValueError('TabICLv2 모델 파일이 없습니다. 01_설치.cmd에서 TabICLv2 추가 설치를 선택한 뒤 02번을 다시 실행하세요.')


def download_checkpoint():
    target=default_checkpoint();target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file():
        try:return checkpoint_path()
        except ValueError:pass
    partial=target.with_suffix('.partial')
    url=f'https://huggingface.co/jingang/TabICL/resolve/{REVISION}/{VERSION}'
    request=urllib.request.Request(url,headers={'User-Agent':'Movenex-public-model-download'})
    print('공식 TabICLv2 모델 다운로드 중 (약 110MB) ...',flush=True)
    with urllib.request.urlopen(request,timeout=120) as response,partial.open('wb') as stream:
        for block in iter(lambda:response.read(1024*1024),b''):stream.write(block)
    stat=partial.stat();_verify(str(partial),stat.st_size,stat.st_mtime_ns)
    partial.replace(target)
    return checkpoint_path()


def require_available(root=None):
    if importlib.util.find_spec('torch') is None or importlib.util.find_spec('tabicl') is None:
        raise ValueError('TabICLv2는 선택 설치 모델입니다. 01_설치.cmd에서 TabICLv2 추가 설치를 선택하고 02번을 다시 실행하세요. RF·XGBoost는 기존대로 사용할 수 있습니다.')
    return checkpoint_path(root)


class TabICLContextClassifier:
    """Keep context only; weights are loaded once per predict call, never fine-tuned.

    Repeated batches use identical context/weights. Rebuilding the official inference
    context is not learning from the query batch. Discarding the engine avoids
    storing 110MB of duplicate weights for every product/position in a saved ZIP.
    """
    def __init__(self,checkpoint):self.checkpoint=str(checkpoint)

    def fit(self,X,y):
        self.X_=np.array(X,dtype=np.float32,copy=True)
        self.y_=np.array(y,dtype=np.int64,copy=True)
        self.classes_=np.unique(self.y_)
        if len(self.classes_)!=2:raise ValueError('TabICLv2 비교에도 두 종류의 기준 라벨이 필요합니다.')
        self.n_features_in_=self.X_.shape[1]
        return self

    def predict_proba(self,X,on_progress=None):
        import torch
        from tabicl import TabICLClassifier
        torch.set_num_threads(2)
        p=Path(self.checkpoint)
        if not p.is_file():p=checkpoint_path()
        stat=p.stat();_verify(str(p.resolve()),stat.st_size,stat.st_mtime_ns)
        engine=TabICLClassifier(n_estimators=1,batch_size=1,kv_cache='repr',device='cpu',use_amp=False,
            use_fa3=False,n_jobs=1,random_state=42,model_path=str(p),checkpoint_version=VERSION,
            allow_auto_download=False,verbose=False)
        results=[]
        try:
            engine.fit(self.X_.copy(),self.y_.copy())
            query=np.array(X,dtype=np.float32,copy=True)
            for start in range(0,len(query),QUERY_BATCH):
                results.append(np.asarray(engine.predict_proba(query[start:start+QUERY_BATCH])))
                if on_progress:on_progress(f'TabICLv2 CPU · {min(start+QUERY_BATCH,len(query)):,}/{len(query):,}행 평가')
            return np.concatenate(results,axis=0) if results else np.empty((0,len(self.classes_)))
        finally:
            del engine;gc.collect()
