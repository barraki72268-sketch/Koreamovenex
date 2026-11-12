from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ectlab.workflow_ui import show_workflow_app


class WorkflowVisibilityTests(unittest.TestCase):
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
