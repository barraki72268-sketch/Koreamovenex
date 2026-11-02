from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
import numpy as np,joblib
from ectlab.workflow import prepare_training,fit_prepared,read_groups,predict_groups
from ectlab.company_results import ng_summary
from ectlab.tabicl_model import require_available,_verify


class FakeContext:
    def __init__(self,checkpoint):self.checkpoint=str(checkpoint)
    def fit(self,X,y):self.X_=np.array(X,copy=True);self.classes_=np.unique(y);return self
    def predict_proba(self,X,on_progress=None):return np.tile([.6,.4],(len(X),1))


class OptionalTabICLTests(unittest.TestCase):
    def test_cpu_sampling_scores_every_eligible_ng_and_marks_unscored_ok(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'c10.csv.gz';source.write_bytes((repo/'data/demo/연습용_ECT.csv.gz').read_bytes())
            prepared=prepare_training(source,'c10',root);groups=read_groups(source,'c10',root)
            with patch('ectlab.tabicl_model.require_available',return_value=root/'public.ckpt'),patch('ectlab.tabicl_model.TabICLContextClassifier',FakeContext):
                bundle=fit_prepared(prepared,root,'TabICLv2')
                before=joblib.hash(bundle['models']);result=predict_groups(bundle,groups)
                self.assertEqual(before,joblib.hash(bundle['models']))
                for key,g in result.groupby(['line','product','position']):
                    valid=g.reason.eq('')
                    self.assertTrue(g.loc[valid&g.equipment_label.eq('NG'),'AI평가여부'].all())
                    self.assertEqual(int(g.loc[valid&g.equipment_label.eq('OK'),'AI평가여부'].sum()),min(128,int((valid&g.equipment_label.eq('OK')).sum())))
                self.assertTrue((~result['AI평가여부']&result.equipment_label.eq('OK')).any())
                self.assertEqual(int(ng_summary(bundle,result)['총 NG'].sum()),int(result.equipment_label.eq('NG').sum()))
                full=fit_prepared(prepared,root,'TabICLv2',tabicl_all_ok=True)
                allrows=predict_groups(full,groups)
                self.assertTrue(allrows.loc[allrows.reason.eq('')&allrows.equipment_label.eq('OK'),'AI평가여부'].all())

    def test_missing_dependency_is_explicit_and_wrong_weight_file_is_rejected(self):
        with patch('ectlab.tabicl_model.importlib.util.find_spec',return_value=None):
            with self.assertRaisesRegex(ValueError,'선택 설치'):require_available()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.ckpt';path.write_bytes(b'wrong public weights')
            with self.assertRaisesRegex(ValueError,'해시'):_verify(str(path),path.stat().st_size,path.stat().st_mtime_ns)


if __name__=='__main__':unittest.main()
