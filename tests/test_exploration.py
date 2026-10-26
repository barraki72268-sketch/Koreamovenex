from pathlib import Path
import tempfile
import unittest
import matplotlib.pyplot as plt
from ectlab.data import load_csv,file_hash
from ectlab.exploration import explore_csv,download_href

ROOT=Path(__file__).resolve().parents[1]

class ExplorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'results').mkdir(exist_ok=True)

    def fixture(self,path):
        df=load_csv(ROOT/'data/demo/연습용_ECT.csv.gz')
        df.source_file='SYNTHETIC_SHAFT.xlsx'
        first=df.sort_values('source_row').groupby(['date','position']).head(1).index
        df.loc[first,'equipment_label']='NG';df.loc[first,'field_label']='NG_master'
        df.loc[first,'yellow_any']=False;df.loc[first,'max_value']=1
        pos1=first[df.loc[first,'position'].eq(1)]
        df.loc[pos1,'x_1']=100;df.loc[pos1,'y_9']=100
        df.to_csv(path,index=False)
        return df

    def test_saturation_axes_drop_not_master_rows_and_positions_remain_separate(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            path=Path(temp)/'new.csv';df=self.fixture(path);before=file_hash(path)
            result=explore_csv(path,Path(temp)/'out','shaft',True)
            counts=result['counts'].set_index(['위치','조건'])
            self.assertEqual(counts.loc[(1,'원본 X/Y'),'X/Y축'],36)
            self.assertEqual(counts.loc[(1,'100이 있는 X/Y축 제외'),'X/Y축'],34)
            self.assertEqual(counts.loc[(2,'100이 있는 X/Y축 제외'),'X/Y축'],42)
            for pos in (1,2):
                self.assertEqual(counts.loc[(pos,'원본 X/Y'),'사용가능마스터'],counts.loc[(pos,'100이 있는 X/Y축 제외'),'사용가능마스터'])
            self.assertEqual(set(result['removed_axes']['위치']),{1})
            self.assertEqual(set(result['points']['표시구분']),{'첫 측정 MASTER NG','설비 OK (참고)','일반 NG (진성·가성 미확정)'})
            self.assertNotIn('decision',result['points'])
            self.assertTrue(result['zip'].is_file())
            self.assertEqual(before,file_hash(path))
            for f in result['figures'].values():plt.close(f)

    def test_first_ok_is_not_forced_into_master(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            path=Path(temp)/'new.csv';df=self.fixture(path)
            index=df.query('position==1').sort_values(['date','source_row']).index[0]
            df.loc[index,'equipment_label']='OK';df.to_csv(path,index=False)
            result=explore_csv(path,Path(temp)/'out','crack',True)
            self.assertTrue(any('첫 측정행 중 OK' in n for n in result['notes']))
            self.assertEqual(len(result['counts']),2)
            self.assertTrue((~result['masters']['마스터지정']).any())
            for f in result['figures'].values():plt.close(f)

    def test_download_copy_stays_inside_static_root_and_preserves_nas_result(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp:
            folder=Path(temp);nas=folder/'nas';nas.mkdir()
            archive=nas/'PCA_test.zip';archive.write_bytes(b'example zip bytes')
            webroot=folder/'workspace';webroot.mkdir()
            href=download_href(archive,webroot)
            self.assertTrue(href.startswith('/files/downloads/'))
            staged=next((webroot/'downloads').glob('*/PCA_test.zip'))
            self.assertEqual(staged.read_bytes(),archive.read_bytes())
            self.assertTrue(staged.resolve().is_relative_to(webroot.resolve()))
