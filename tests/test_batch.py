from pathlib import Path
import unittest,tempfile,json,hashlib,os
from ectlab.batch import read_batch_sources,run_batch,gallery_entries
from ectlab.sample_browser import load_sample_matrix
from scripts.make_delivery_demo import make_workbook
import pandas as pd


class BatchTests(unittest.TestCase):
    def test_manifest_never_silently_replaces_missing_real_data_with_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(ValueError):read_batch_sources(root)
            (root/'data/private').mkdir(parents=True)
            (root/'data/private/전체실행_자료.json').write_text(json.dumps({'sources':[]}),encoding='utf-8')
            with self.assertRaises(ValueError):read_batch_sources(root)

    def test_all_four_sources_keep_rows_and_export_same_condition_pca_tsne(self):
        legacy=Path(__file__).resolve().parents[1]/'data/demo/연습용_ECT.csv.gz'
        parent=('\\\\?\\'+str(Path(tempfile.gettempdir()).resolve())) if os.name=='nt' else None
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            root=Path(temp);crack=make_workbook(root/'crack.xlsx','crack');shaft=make_workbook(root/'shaft.xlsx','shaft')
            jobs=[{'key':key,'label':key,'path':p} for key,p in [('C10A',legacy),('C80B',legacy),('crack',crack),('shaft',shaft)]]
            # Both synthetic legacy files have the demo's original training dates.
            for j in jobs:j['train_end']='2026-08-20'
            before={str(j['path']):hashlib.sha256(j['path'].read_bytes()).hexdigest() for j in jobs}
            panels=[];result=run_batch(root,jobs=jobs,with_ml=False,on_panel=panels.append)
            self.assertFalse(result['errors']);self.assertEqual(len(panels),8)
            self.assertEqual(len(result['tables']['전체실행']),4)
            self.assertEqual(len(result['sample_index']),14)
            index=json.loads((result['folder']/'샘플결과_목록.json').read_text(encoding='utf-8'))
            self.assertEqual({e['dataset'] for e in index['entries']},{'C10A','C80B','crack','shaft'})
            for key in ('C10A','C80B','crack','shaft'):
                es=[e for e in result['sample_index'] if e['dataset']==key]
                self.assertEqual(sum(e['rows'] for e in gallery_entries(es)),len(pd.read_csv(legacy)) if key in ('C10A','C80B') else 100)
                e=es[0];rows=pd.read_csv(result['folder']/e['file'])
                matrix=load_sample_matrix(result['folder'],e,rows.head(3))
                self.assertEqual(matrix.shape,(3,len(e['features'])))
            self.assertTrue(result['zip'].is_file());self.assertTrue((result['folder']/'전체자료_보고서.html').is_file())
            for p in panels:self.assertTrue(Path(p['file']).with_suffix('.csv.gz').is_file())
            for job in jobs:self.assertEqual(hashlib.sha256(job['path'].read_bytes()).hexdigest(),before[str(job['path'])])


if __name__=='__main__':unittest.main()
