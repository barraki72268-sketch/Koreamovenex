from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest,hashlib
from unittest.mock import patch
import numpy as np,pandas as pd,joblib
from ectlab.company_results import classify_rows,ng_summary,detail_table,view_mask
from ectlab.workflow import prepare_training,fit_prepared,read_groups,predict_groups,pca_figure
from ectlab.chunk_upload import ChunkUpload
from scripts.make_delivery_demo import make_workbook


class CompanyResultsTests(unittest.TestCase):
    def test_renamed_excel_reuses_cache_and_keeps_current_source_filename(self):
        from ectlab import delivery_excel
        from ectlab.data import file_hash
        for profile in ('shaft','crack'):
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                first=make_workbook(root/'first.xlsx',profile)
                train=read_groups(first,profile,root,training=True)
                cache_root=root/'data/processed/새Excel_변환캐시'
                current=next(cache_root.iterdir())
                legacy_key=hashlib.sha256((profile+file_hash(first)+first.name+file_hash(Path(delivery_excel.__file__))).encode()).hexdigest()
                current.rename(cache_root/legacy_key)
                second=root/'uploaded_again.xlsx';second.write_bytes(first.read_bytes())
                with patch('ectlab.delivery_excel.convert_workbook',side_effect=AssertionError('Same Excel bytes reparsed')):
                    result=read_groups(second,profile,root,training=False)
                    again=read_groups(second,profile,root,training=False)
                for key,g in result.items():
                    np.testing.assert_equal(g['X'],train[key]['X'])
                    self.assertTrue(g['rows'].source_file.eq(second.name).all())
                    self.assertEqual(len(again[key]['rows']),len(g['rows']))

    def test_repeated_excel_read_uses_verified_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=make_workbook(root/'crack.xlsx','crack')
            train=read_groups(p,'crack',root,training=True)
            with patch('ectlab.delivery_excel.convert_workbook',side_effect=AssertionError('Unnecessary Excel reparse')):
                test=read_groups(p,'crack',root,training=False)
            self.assertEqual(sum(len(g['rows']) for g in train.values()),sum(len(g['rows']) for g in test.values()))

    def test_missing_product_does_not_silently_drop_source_ng_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=Path(__file__).resolve().parents[1]
            raw=pd.read_csv(repo/'data/demo/연습용_ECT.csv.gz').head(40)
            raw.loc[0,['line','product','equipment_label']]=[np.nan,np.nan,'NG']
            path=root/'missing.csv';raw.to_csv(path,index=False)
            groups=read_groups(path,'c10',root)
            rows=pd.concat([g['rows'] for g in groups.values()])
            self.assertEqual(len(rows),len(raw))
            self.assertEqual(int(rows.equipment_label.eq('NG').sum()),int(raw.equipment_label.eq('NG').sum()))
            self.assertTrue(rows['reason'].str.contains('라인 또는 품번 누락').any())

    def test_raw_ng_is_fully_accounted_even_when_view_excludes_zero_and_extremes(self):
        records=[]
        for i,(raw,pred,maximum,master) in enumerate([
            ('NG','진성불량 의심',10,True),('NG','가성불량 후보',2,False),
            ('NG','진성불량 의심',70,False),('NG','판정 보류',100,False),
            ('NG','입력 확인 필요',0,False),('NG','입력 확인 필요',3,False),
            ('OK','불량 의심 · FN 후보',8,False)]):
            records.append(dict(line='L',product='P',position=1,equipment_label=raw,예측=pred,max_value=maximum,
                                master=master,점수=.8,calendar_date='2026-10-29',time='05:07:21',counter=i,
                                max_frequency='1x80.0Hz',part_no=i,source_row=i+3))
        rows=classify_rows(pd.DataFrame(records));bundle={'models':{('L','P',1):{'pca':SimpleNamespace(explained_variance_ratio_=np.array([.4,.2]))}}}
        small=ng_summary(bundle,rows,5).iloc[0];whole=ng_summary(bundle,rows,'full').iloc[0]
        self.assertEqual(small['총 NG'],6);self.assertEqual(small['분류합계'],6)
        self.assertEqual(small['집계검증'],'일치');self.assertEqual(small['표시범위밖(NG)'],3)
        self.assertEqual(whole['총 NG'],small['총 NG']);self.assertEqual(small['기준자료0(NG)'],1)
        detail=detail_table(rows);self.assertEqual(detail.iloc[0]['MAX FRQ'],'1x80.0Hz')
        self.assertEqual(detail.iloc[1]['Part_No'],1);self.assertEqual(detail.iloc[2]['판정'],'진성불량 의심')
        self.assertTrue(np.isnan(detail.iloc[4]['가성유사점수(%)']))
        self.assertFalse(view_mask(rows,'all').iloc[3])

    def test_known_master_and_zero_reference_are_visible_without_refitting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=make_workbook(root/'crack.xlsx','crack')
            bundle=fit_prepared(prepare_training(p,'crack',root),root)
            before=joblib.hash(bundle['models']);groups=read_groups(p,'crack',root)
            key=next(iter(groups));g=groups[key]
            g['rows'].loc[1,['max_value','reason','equipment_label']]=[0,'최대값 0: 판정 불명','NG']
            result=predict_groups(bundle,groups)
            self.assertEqual(int(result['판정'].eq('MASTER').sum()),4)
            zero=result[result.max_value.eq(0)].iloc[0]
            self.assertEqual(zero['판정'],'기준자료 (최대값 0)');self.assertTrue(np.isnan(zero['점수']))
            self.assertTrue(np.isfinite(zero.PC1));self.assertEqual(joblib.hash(bundle['models']),before)
            part=result[result.position.eq(key[2])];fig=pca_figure(bundle,key,part,view_limit=5)
            self.assertTrue(any('기준자료' in obj.get_label() for obj in fig.axes[0].collections))
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_local_path_upload_preserves_unicode_original_and_reports_bad_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'새 검사 자료.CSV';data=b'a,b\n1,2\n';source.write_bytes(data)
            completed=[];upload=ChunkUpload(root/'upload',completed.append,extensions=('.csv',))
            copied=upload.import_local('"'+str(source)+'"')
            self.assertEqual(len(completed),1);self.assertEqual(copied.read_bytes(),data)
            self.assertEqual(source.read_bytes(),data);self.assertFalse(upload.error)
            upload.import_local(root/'missing.csv');self.assertTrue(upload.error);self.assertEqual(len(completed),1)


if __name__=='__main__':unittest.main()
