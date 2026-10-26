from pathlib import Path
import tempfile,unittest,json
import pandas as pd
from ectlab.unified import run_legacy
from ectlab.delivery_ui import analyze_files
from ectlab.sample_browser import comparison_figure,tsne_figure
from scripts.make_delivery_demo import make_workbook
import matplotlib.pyplot as plt


class UnifiedTests(unittest.TestCase):
    def test_existing_models_and_field_labels_remain_available(self):
        source=Path(__file__).resolve().parents[1]/'data/demo/연습용_ECT.csv.gz'
        with tempfile.TemporaryDirectory() as temp:
            result=run_legacy(source,temp)
            self.assertEqual(len(list((result['folder']/'models').glob('p*.joblib'))),6)
            entries=json.loads((result['folder']/'샘플결과_목록.json').read_text(encoding='utf-8'))['entries']
            tables=[pd.read_csv(result['folder']/e['file']) for e in entries]
            self.assertEqual(sum(len(t) for t in tables),len(pd.read_csv(source)))
            self.assertTrue(any(t.현장판정.eq('기업 진성').any() for t in tables))
            self.assertTrue(all('기존거리판정' in t and 'RF결과' in t for t in tables))

    def test_new_samples_support_all_rows_distances_and_alternative_views(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);book=make_workbook(root/'크랙.xlsx','crack')
            result=analyze_files({'crack':book},root,with_ml=True,crack_day_start_hour=6)
            entries=result['sample_index'];entry=entries[0]
            rows=pd.read_csv(result['folder']/entry['file'])
            self.assertEqual(len(rows),50)
            self.assertTrue(rows.NG_MASTER거리.notna().all())
            self.assertTrue(rows.RF점수.notna().any())
            self.assertFalse(rows.현장판정.eq('진성').any())
            fig=comparison_figure(rows,entry);self.assertEqual(len(fig.axes),4);plt.close(fig)
            fig,coordinates=tsne_figure(result['folder'],rows,entry)
            self.assertEqual(len(coordinates),len(rows));self.assertIn('TSNE1',coordinates);plt.close(fig)


if __name__=='__main__':unittest.main()
