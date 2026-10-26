"""Collect report inputs without embedding large checkpoint files."""
from pathlib import Path
import argparse,tarfile,json,hashlib
parser=argparse.ArgumentParser()
parser.add_argument('--work-dir',required=True)
parser.add_argument('--result-dir',default='results_fp32')
args=parser.parse_args()
root=Path(args.work_dir).resolve();result=root/args.result_dir
completion=json.loads((result/'COMPLETED.json').read_text())
assert completion['errors']==0,completion
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
checkpoints=[]
for p in sorted(result.glob('*/inference.ckpt')):
    checkpoints.append({'id':p.parent.name.split('_')[0],'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p),'adaptation':json.loads((p.parent/'adaptation_audit.json').read_text())})
base=root/'checkpoints/tabicl-classifier-v2-20260212.ckpt'
(root/'checkpoint_manifest.json').write_text(json.dumps({'adapted':checkpoints,'pretrained':str(base),'pretrained_sha256':sha(base)},indent=2))
with tarfile.open(root/'foundation_results.tar.gz','w:gz') as tar:
    for directory,archive_name in ((root/'inputs','inputs'),(result,'results_fp32')):
        for p in directory.rglob('*'):
            if p.is_file() and p.suffix not in ('.ckpt','.pkl'):
                tar.add(p,arcname=Path(archive_name)/p.relative_to(directory))
    for name in ('source_commit.txt','requirements.lock.txt','checkpoint_manifest.json'):
        tar.add(root/name,arcname=name)
    for name in ('run_foundation_gpu.py','pack_foundation_results.py'):
        tar.add(Path(__file__).with_name(name),arcname=name)
    plan=json.loads((result/'experiment_plan.json').read_text())
    log=root/('slurm-'+str(plan['job_id'])+'.log')
    if log.is_file():tar.add(log,arcname=log.name)
print(root/'foundation_results.tar.gz')
