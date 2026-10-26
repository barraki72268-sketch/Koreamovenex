from pathlib import Path
import unittest,tempfile,json,base64
import pandas as pd
from ectlab.crack_view import attach_crack_view,panel_for_crack,CACHE
from ectlab.data import file_hash


class CrackViewTests(unittest.TestCase):
    def make_fixture(self,root):
        source=root/'crack.xlsx';source.write_bytes(b'private input A')
        folder=root/'report';folder.mkdir();(folder/'samples').mkdir()
        sample=pd.DataFrame({'원본시트':['10.25']*4,'원본행':[1,2,3,4],'RF점수':[.4,.5,.6,.7]})
        sample.to_csv(folder/'samples/c.csv.gz',index=False)
        entry={'profile':'crack','line':'C','product':'P','position':3,'file':'samples/c.csv.gz'}
        result={'folder':folder,'sample_index':[entry],'tables':{}}
        cache=root/'notebooks'/CACHE;cache.mkdir(parents=True)
        score=pd.DataFrame({'source_sheet':['10.25']*3,'source_row':[2,3,4],'TabICLv2_score':[.99,.01,.2],'reference_label':[1,0,-2]})
        score.to_csv(cache/'scores.csv.gz',index=False)
        pd.DataFrame({'model':['TabICLv2_default'],'test_MASTER':[1]}).to_csv(cache/'summary.csv',index=False)
        (cache/'plot.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII='))
        group={'line':'C','product':'P','position':3,'status':'ready','plot':'plot.png','comparison_plot':'plot.png','scores_default':'scores.csv.gz','scores_preserve':'scores.csv.gz','query_rows':3,'plot_rows':3}
        manifest={'source_sha256':file_hash(source),'crack_day_start_hour':6,'job_id':'test','groups':[group],
                  'files':{p.name:file_hash(p) for p in cache.iterdir()},'summary_plot':'plot.png','summary_csv':'summary.csv'}
        (cache/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        return source,result,entry,cache

    def test_saved_scores_join_original_rows_without_relabelling_conflict_or_rf(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source,result,entry,cache=self.make_fixture(root)
            view=attach_crack_view(result,root,source,6)
            self.assertEqual(view['status'],'matched');self.assertTrue(Path(panel_for_crack(result,entry)['file']).is_file())
            self.assertTrue(Path(panel_for_crack(result,entry)['comparison_file']).is_file())
            rows=pd.read_csv(result['folder']/entry['file'])
            self.assertTrue(pd.isna(rows.loc[0,'TabICLv2점수']))
            self.assertEqual(rows.loc[1,'TabICLv2점수'],.99)
            self.assertIn('충돌',rows.loc[3,'TabICLv2결과'])
            self.assertEqual(rows.RF점수.tolist(),[.4,.5,.6,.7])
            shaft=dict(entry,profile='shaft')
            self.assertIsNone(panel_for_crack(result,shaft))

    def test_new_source_different_day_boundary_or_changed_asset_cannot_reuse_gpu_view(self):
        for kind,expected in [('source','source_mismatch'),('boundary','boundary_mismatch'),('asset','invalid')]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);source,result,entry,cache=self.make_fixture(root)
                if kind=='source':source.write_bytes(b'private input B')
                if kind=='asset':(cache/'plot.png').write_bytes(b'changed artifact')
                view=attach_crack_view(result,root,source,5 if kind=='boundary' else 6)
                self.assertEqual(view['status'],expected)
                self.assertNotIn('TabICLv2점수',pd.read_csv(result['folder']/entry['file']))
                self.assertIsNone(panel_for_crack(result,entry))


if __name__=='__main__':unittest.main()
