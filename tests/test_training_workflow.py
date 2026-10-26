from pathlib import Path
import tempfile,unittest,hashlib
from unittest.mock import patch
import numpy as np,pandas as pd,joblib
from scripts.make_delivery_demo import make_workbook
from ectlab.workflow import prepare_training,fit_prepared,predict_file,predict_groups,read_groups


class TrainingWorkflowTests(unittest.TestCase):
    def test_new_batches_never_refit_pca_or_model_and_overlap_is_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);book=make_workbook(root/'crack.xlsx','crack')
            prepared=prepare_training(book,'crack',root,train_end='2026-10-24')
            bundle=fit_prepared(prepared,root)
            before=hashlib.sha256(joblib.hash(bundle['models']).encode()).hexdigest()
            with patch('sklearn.decomposition.PCA.fit',side_effect=AssertionError('PCA must stay frozen')):
                result=predict_file(bundle,book,root)
                again=predict_file(bundle,book,root)
            self.assertEqual(len(result['rows']),100)
            self.assertEqual(int(result['rows']['학습파일중복'].sum()),50)
            np.testing.assert_allclose(result['rows']['점수'],again['rows']['점수'],equal_nan=True)
            self.assertEqual(before,hashlib.sha256(joblib.hash(bundle['models']).encode()).hexdigest())
            self.assertFalse(result['record']['refitted']);self.assertFalse(result['record']['PCA_refitted'])

    def test_training_mask_is_fixed_and_new_saturation_or_unknown_product_is_held(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);book=make_workbook(root/'shaft.xlsx','shaft')
            prepared=prepare_training(book,'shaft',root,train_end='2026-10-24')
            bundle=fit_prepared(prepared,root)
            key=next(iter(bundle['models']));m=bundle['models'][key]
            self.assertTrue(all('100_' not in f for f in m['features']))
            groups=read_groups(book,'shaft',root)
            part=groups[key];part['X']=part['X'].copy();part['rows']=part['rows'].iloc[[1,2]].copy().reset_index(drop=True)
            part['X']=part['X'][[1,2]]
            slot=next(i for i,f in enumerate(part['descriptors']) if f['feature'] in m['features'] and f['axis']=='측정값')
            part['X'][0,slot]=100
            scored=predict_groups(bundle,{key:part})
            self.assertEqual(scored.iloc[0]['예측'],'판정 보류')
            other=predict_groups(bundle,{('NEW','PRODUCT',9):part})
            self.assertTrue(other['점수'].isna().all());self.assertTrue(other.예측.eq('입력 확인 필요').all())

    def test_c10_true_labels_are_used_where_available_and_source_changes_require_prepare(self):
        rootrepo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'c10.csv.gz';source.write_bytes((rootrepo/'data/demo/연습용_ECT.csv.gz').read_bytes())
            prepared=prepare_training(source,'c10',root)
            bundle=fit_prepared(prepared,root)
            self.assertTrue(any(m['direct_labels'] for m in bundle['models'].values()))
            self.assertTrue(any(not m['direct_labels'] for m in bundle['models'].values()))
            source.write_bytes(source.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'변경'):fit_prepared(prepared,root)

    def test_vector_batch_preserves_order_and_maps_ng_ok_to_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);book=make_workbook(root/'crack.xlsx','crack');bundle=fit_prepared(prepare_training(book,'crack',root),root)
            groups=read_groups(book,'crack',root);keys=list(bundle['models']);records=[]
            for number,key in enumerate([keys[1],keys[0],keys[1]]):
                m=bundle['models'][key];g=groups[key];index=next(i for i,row in g['rows'].iterrows() if row.equipment_label=='OK')
                values=dict(zip(g['features'],g['X'][index]));row={'sample_id':f'q{number}','line':key[0],'product':key[1],'position':key[2],'equipment_label':'NG' if number==0 else 'OK','date':'2026-11-01','time':'09:00:00','counter':number}
                row.update({'feature__'+f:values[f] for f in m['features']});records.append(row)
            path=root/'new.csv';pd.DataFrame(records).to_csv(path,index=False)
            result=predict_file(bundle,path,root)
            self.assertEqual(result['rows'].sample_id.tolist(),['q0','q1','q2'])
            self.assertFalse(result['rows'].학습파일중복.any())
            self.assertTrue(result['rows']['점수'].notna().all())


if __name__=='__main__':unittest.main()
