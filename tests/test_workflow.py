"""Business-rule tests using synthetic data only. Run: python -m unittest discover -s tests -v"""
from pathlib import Path
import tempfile
import unittest
import numpy as np
import joblib
from ectlab.data import load_csv,feature_schema
from ectlab.pipeline import Settings,prepare,train_models,predict_saved,distance_analysis,summarize

ROOT=Path(__file__).resolve().parents[1]

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'results').mkdir(exist_ok=True)
        cls.df=load_csv(ROOT/'data/demo/연습용_ECT.csv.gz')
        cls.packs,_=prepare(cls.df,Settings())

    def test_positions_have_own_features_and_labels(self):
        self.assertEqual(len(self.packs[1]['features']),36)
        self.assertEqual(len(self.packs[2]['features']),42)
        self.assertEqual(int(self.packs[1]['rows'].field_label.eq('field_true').sum()),0)
        self.assertEqual(int(self.packs[2]['rows'].field_label.eq('field_true').sum()),2)
        changed=self.df.copy();changed.loc[changed.position.eq(2),'field_label']='unlabeled'
        other,_=prepare(changed,Settings())
        self.assertTrue(np.array_equal(self.packs[1]['rows'].proxy_train,other[1]['rows'].proxy_train))

    def test_time_and_true_event_exclusion(self):
        for p in self.packs.values():
            r=p['rows']; self.assertTrue(r.loc[r.proxy_train,'date'].le('2026-08-20').all())
            self.assertFalse((r.proxy_train&r.role.eq('test')).any())
            groups=set(r.loc[r.field_label.eq('field_true'),'event_group'])
            self.assertFalse(set(r.loc[r.proxy_train,'event_group']) & groups)

    def test_zero_yellow_never_trains(self):
        for p in self.packs.values():
            r=p['rows']; excluded=r.yellow_any|r.max_value.eq(0)
            self.assertTrue(excluded.any()); self.assertFalse(r.loc[excluded,'eligible'].any())
            self.assertFalse(r.loc[excluded,'proxy_train'].any())

    def test_frequency_drift_and_duplicate_csv_are_rejected(self):
        bad=self.packs[1]['rows'].copy();bad.loc[0,'freq_1']='999.0Hz'
        with self.assertRaisesRegex(ValueError,'주파수'):feature_schema(bad)
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            path=Path(temp)/'duplicated.csv';self.df.iloc[[0,0]].to_csv(path,index=False)
            with self.assertRaisesRegex(ValueError,'중복'):load_csv(path)

    def test_direct_one_class_skips_and_saved_model_matches(self):
        result=train_models(self.packs,names=('RandomForest',))
        self.assertTrue(any('위치1 / company_direct' in n for n in result['notes']))
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            path=Path(temp)/'p2.joblib';joblib.dump(result['models']['p2_master_proxy_RandomForest'],path)
            scored=predict_saved(path,ROOT/'data/demo/연습용_ECT.csv.gz')
            before=result['predictions']; before=before[before.position.eq(2)&before.experiment.eq('master_proxy')&before.NG_query].set_index('id')
            after=scored.set_index('id').loc[before.index]
            np.testing.assert_allclose(before.positive_score,after.positive_score,rtol=0,atol=1e-12)
            self.assertTrue((after.decision.to_numpy()==before.decision.to_numpy()).all())
            self.assertTrue(scored.loc[scored.equipment_label.eq('OK'),'decision'].eq('not_scored').all())
            bad=self.df.copy();bad.loc[bad.position.eq(2),'freq_1']='999.0Hz';target=Path(temp)/'drift.csv';bad.to_csv(target,index=False)
            with self.assertRaisesRegex(ValueError,'다릅니다'):predict_saved(path,target)

    def test_distance_results_reconcile(self):
        result=distance_analysis(self.packs)
        self.assertFalse(result['notes'])
        summary=summarize(result['predictions'])
        for _,row in summary.iterrows():
            self.assertEqual(row['진성 행'],row['진성 의심']+row['진성 보류']+row['진성을 가성 후보로'])
            self.assertEqual(row['가성 행'],row['가성 후보']+row['가성 보류']+row['가성을 진성 의심으로'])

    def test_excel_colors_do_not_spread_to_uncolored_rows(self):
        # A file containing an error row must not mark every uncolored row as error.
        import zipfile
        from ectlab.data import read_workbook,company_label
        ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        styles=f'<styleSheet xmlns="{ns}"><fills><fill><patternFill/></fill><fill><patternFill><fgColor rgb="FFFFC000"/></patternFill></fill><fill><patternFill><fgColor theme="0" tint="-0.25"/></patternFill></fill><fill><patternFill><fgColor theme="9"/></patternFill></fill></fills><cellXfs><xf fillId="0"/><xf fillId="1"/><xf fillId="2"/><xf fillId="3"/></cellXfs></styleSheet>'
        rows=[]
        for n,style,label,counter in [(3,0,'OK','10'),(4,1,'NG','11'),(5,2,'NG','12'),(6,0,'NG','NG마스터'),(7,3,'NG','13')]:
            cells=''.join(f'<c r="{col}{n}" s="{style if col=="F" else 0}" t="inlineStr"><is><t>{v}</t></is></c>' for col,v in [('A','2026-10-01'),('B','10:00:00'),('C',counter),('F',label),('G','1'),('H','1')])
            rows.append(f'<row r="{n}">{cells}</row>')
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            path=Path(temp)/'colors.xlsx'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('xl/styles.xml',styles)
                z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="10.1" r:id="r1"/></sheets></workbook>')
                z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns}"><sheetData>{"".join(rows)}</sheetData></worksheet>')
            frame=read_workbook(path)
            self.assertEqual(frame.apply(company_label,axis=1).tolist(),['unlabeled','field_true','measurement_error','NG_master','field_false'])

if __name__=='__main__':
    (ROOT/'results').mkdir(exist_ok=True)
    unittest.main()
