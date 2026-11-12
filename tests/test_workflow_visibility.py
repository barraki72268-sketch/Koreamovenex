from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ectlab.workflow_ui import show_workflow_app
from scripts.make_delivery_demo import make_workbook


class WorkflowVisibilityTests(unittest.TestCase):
    def test_stage3_error_unlocks_controls_and_progress_is_above_file_picker(self):
        with tempfile.TemporaryDirectory() as folder,patch('ectlab.workflow_ui.display'):
            root=Path(folder)
            book=make_workbook(root/'shaft.xlsx','shaft')
            with patch('ectlab.workflow_ui.available_files',return_value=[book]):
                app=show_workflow_app(root)
                app['family'].value='shaft'
                app['train'].value=str(book)
                app['prepare'].click()
                app['fit'].click()
            self.assertIsNotNone(app['state']['bundle'],app['status'][1].value)
            def fail(*args,**kwargs):
                self.assertTrue(app['test'].disabled)
                self.assertTrue(app['upload_test'].disabled)
                self.assertTrue(app['predict'].disabled)
                raise ValueError('regression: invalid inspection input')
            with patch('ectlab.workflow_ui.predict_file',side_effect=fail):
                app['predict'].click()
            self.assertFalse(app['state']['busy'])
            self.assertFalse(app['test'].disabled)
            self.assertFalse(app['upload_test'].disabled)
            self.assertFalse(app['predict'].disabled)
            self.assertIn('invalid inspection input',app['status'][2].value)
            children=list(app['app'].children)
            self.assertLess(children.index(app['status'][2]),children.index(app['upload_test']))
            app['predict'].click()
            self.assertIsNotNone(app['state']['result'],app['status'][2].value)
            self.assertTrue(app['state']['result']['record']['ng_reconciled'])
            self.assertTrue(app['state']['result']['zip'].is_file())
            self.assertFalse(app['predict'].disabled)
            self.assertFalse(app['upload_test'].disabled)

    def test_conditional_controls_do_not_hide_file_and_result_selectors(self):
        with tempfile.TemporaryDirectory() as folder, patch('ectlab.workflow_ui.display'):
            app = show_workflow_app(Path(folder))
            always_visible = ['family', 'train', 'test', 'model', 'learned', 'tested', 'inspection_date', 'view', 'end']
            layouts = [app[name].layout for name in always_visible + ['drop', 'tabicl_all_ok']]
            self.assertEqual(len(layouts), len({id(layout) for layout in layouts}))
            for profile in ['c10', 'shaft', 'crack', 'shaft']:
                app['family'].value = profile
                self.assertEqual(app['drop'].layout.display != 'none', profile == 'shaft')
                self.assertEqual(app['drop'].value, profile == 'shaft')
                for model in ['RandomForest', 'TabICLv2', 'XGBoost']:
                    app['model'].value = model
                    self.assertEqual(app['tabicl_all_ok'].layout.display != 'none', model == 'TabICLv2')
                    self.assertEqual(app['drop'].layout.display != 'none', profile == 'shaft')
                    for name in always_visible:
                        self.assertNotEqual(app[name].layout.display, 'none', (profile, model, name))


if __name__ == '__main__':
    unittest.main()
