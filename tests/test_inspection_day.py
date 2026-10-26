import unittest
import pandas as pd
import numpy as np
from ectlab.inspection_day import crack_inspection_days,measurement_timestamp
from ectlab.sample_reports import reference_coordinates


class InspectionDayTests(unittest.TestCase):
    def test_overnight_tail_is_not_invented_as_master(self):
        frame=pd.DataFrame({'c0':['2026-10-21','2026-10-20','2026-10-20','2026-10-21','2026-10-20'],
            'c1':['01:30:00','06:05:00','01:30:00','06:00:00','06:00:00'],
            'source_sheet':['same']*5,'source_row':[7,5,3,8,4]})
        rows,master=crack_inspection_days(frame,6)
        self.assertEqual(set(rows.loc[master,'source_row']),{4,8})
        self.assertEqual(rows.loc[rows.source_row.eq(7),'c0'].iloc[0],'2026-10-20')
        self.assertEqual(rows.loc[rows.source_row.eq(3),'c0'].iloc[0],'2026-10-19')
        self.assertFalse(master[rows.source_row.eq(3)].any())
        self.assertEqual(rows.loc[rows.source_row.eq(7),'calendar_date'].iloc[0],'2026-10-21')

    def test_missing_time_is_not_silently_assigned_a_master(self):
        frame=pd.DataFrame({'c0':['2026-10-20'],'c1':['unknown'],'source_sheet':['s'],'source_row':[3]})
        with self.assertRaises(ValueError):crack_inspection_days(frame,6)
        result=measurement_timestamp(pd.Series(['2026-10-20']),pd.Series([.25]))
        self.assertEqual(str(result.iloc[0]),'2026-10-20 06:00:00')

    def test_reference_distance_excludes_the_query_itself(self):
        X=np.array([[0.,0.],[1.,0.],[0.,1.],[8.,8.]])
        valid=np.ones(4,bool);normal=np.array([1,1,1,0],bool);master=~normal
        coords,dm,do,ratios=reference_coordinates(X,valid,normal,master)
        self.assertTrue(np.isnan(dm[-1]))
        self.assertTrue((do[:3]>0).all())
        self.assertEqual(coords.shape,(4,3))


if __name__=='__main__':unittest.main()
