import unittest
import pandas as pd
from ectlab.delivery import feature_frame

class DeliveryFeaturesTests(unittest.TestCase):
    def test_crack_reads_filter_values_without_inventing_xy(self):
        values={f'c{10+2*j}':['0','0'] for j in range(30)}
        values.update({f'c{11+2*j}':[0,0] for j in range(30)})
        values.update(c10=['100.0Hz','100.0Hz'],c11=[1.4,.5])
        x,features=feature_frame(pd.DataFrame(values),'crack')
        self.assertEqual(x.shape,(2,1))
        self.assertEqual(x.iloc[:,0].tolist(),[1.4,.5])
        self.assertEqual(features[0]['axis'],'측정값')

    def test_shaft_keeps_xy_and_separate_measured_value(self):
        values={f'c{9+4*j}':['0','0'] for j in range(24)}
        for j in range(24):
            for offset in (1,2,3):values[f'c{9+4*j+offset}']=[0,0]
        values.update(c9=['1x30.0Hz','1x30.0Hz'],c10=[32767,10],c11=[5,2],c12=[100,.2])
        x,features=feature_frame(pd.DataFrame(values),'shaft')
        self.assertEqual(x.shape,(2,3))
        self.assertEqual([f['axis'] for f in features],['X','Y','측정값'])
        self.assertEqual(x.iloc[0].tolist(),[32767,5,100])

    def test_frequency_changes_require_condition_separation(self):
        values={f'c{10+2*j}':['0','0'] for j in range(30)}
        values['c10']=['100Hz','200Hz']
        with self.assertRaisesRegex(ValueError,'주파수'):
            feature_frame(pd.DataFrame(values),'crack')
