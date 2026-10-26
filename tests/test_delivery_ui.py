import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from scripts.make_delivery_demo import make_workbook
from ectlab.delivery_ui import analyze_files, save_upload
from ectlab.delivery_excel import convert_workbook
from ectlab.delivery import run_delivery
import pandas as pd
import json
from ectlab.chunk_upload import ChunkUpload


class DeliveryUIIntegration(unittest.TestCase):
    def test_http_upload_completion_selects_valid_excel_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=make_workbook(root/'연습.xlsx','crack')
            folder=root/'uploads';folder.mkdir()
            part=folder/('upload_'+'a'*32+'.part')
            part.write_bytes(source.read_bytes())
            selected=[]
            upload=ChunkUpload(folder,selected.append)
            upload.events.value=json.dumps({'action':'begin'})
            self.assertTrue(upload.busy)
            upload.events.value=json.dumps({'action':'finish','part':part.name,'name':'새자료.xlsx'})
            self.assertFalse(upload.busy)
            self.assertFalse(upload.error)
            self.assertEqual(len(selected),1)
            self.assertFalse(part.exists())
            self.assertEqual(selected[0].read_bytes(),source.read_bytes())
            upload.events.value=json.dumps({'action':'finish','part':'../연습.xlsx','name':'새자료.xlsx'})
            self.assertTrue(upload.error)
            self.assertTrue(source.exists())
            upload.disabled=True
            self.assertTrue(upload.events.disabled)

    def test_new_saturation_on_test_day_is_held_for_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            book=make_workbook(root/'샤프트.xlsx','shaft')
            convert_workbook('shaft',book,root/'input')
            path=root/'input/shaft_raw.csv.gz'
            frame=pd.read_csv(path)
            target=frame.c0.eq('2026-10-25') & frame.c6.eq(1) & frame.c2.eq('NG마스터')
            self.assertEqual(int(target.sum()),1)
            frame.loc[target,'c16']=32767
            frame.to_csv(path,index=False)
            result=run_delivery(root/'input',root/'result')
            scores=result['tables']['05_ML_행별점수']
            picked=scores[scores['조건'].eq('학습일100·32767채널 제외') & scores['위치'].eq(1) & scores.c2.eq('NG마스터') & scores.c0.eq('2026-10-25')]
            self.assertEqual(len(picked),2)
            self.assertTrue(picked['시험일_추가포화'].all())
            self.assertTrue(picked['결과'].eq('보류').all())
            stats=result['tables']['04_ML_마지막날짜시험']
            stats=stats[stats['조건'].eq('학습일100·32767채널 제외') & stats['위치'].eq(1)]
            self.assertTrue(stats.MASTER보류.eq(1).all())
            self.assertTrue(stats.MASTER높음.eq(0).all())

    def test_single_excel_pca_keeps_positions_and_saturation_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = make_workbook(root / '샤프트.xlsx', 'shaft')
            before = book.read_bytes()
            result = analyze_files({'shaft': book}, root)
            self.assertEqual(book.read_bytes(), before)
            counts = result['tables']['01_데이터수량']
            self.assertEqual(set(counts['위치']), {1, 2})
            self.assertEqual(set(counts['검사']), {'shaft'})
            pca = result['tables']['03_PCA요약']
            self.assertEqual(len(pca), 8)
            self.assertTrue((pca[pca['조건'].eq('100측정값 채널 전체 제외')]['입력수'] == 12).all())
            self.assertTrue(result['tables']['04_ML_마지막날짜시험'].empty)
            with ZipFile(result['zip']) as archive:
                self.assertIn('검증보고서.html', archive.namelist())
                self.assertIn('변환CSV/shaft_raw.csv.gz', archive.namelist())
            # A subsequent crack-only run must not reuse the shaft CSV.
            crack = make_workbook(root / '크랙.xlsx', 'crack')
            second = analyze_files({'crack': crack}, root, with_ml=True)
            self.assertEqual(set(second['tables']['01_데이터수량']['위치']), {3, 4})
            self.assertEqual(len(second['tables']['04_ML_마지막날짜시험']), 4)

    def test_wrong_profile_and_unsafe_upload_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            crack = make_workbook(root / '크랙.xlsx', 'crack')
            with self.assertRaises(ValueError):
                analyze_files({'shaft': crack}, root)
            with self.assertRaises(ValueError):
                save_upload(root, '../위험.xlsx', crack.read_bytes())
            with self.assertRaises(ValueError):
                save_upload(root, '파일.xlsx', b'not an excel workbook')
            saved = save_upload(root, '파일.xlsx', crack.read_bytes())
            saved2 = save_upload(root, '파일.xlsx', crack.read_bytes())
            self.assertNotEqual(saved, saved2)
            self.assertEqual(saved.read_bytes(), crack.read_bytes())


if __name__ == '__main__':
    unittest.main()
