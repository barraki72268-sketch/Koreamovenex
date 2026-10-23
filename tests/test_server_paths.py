"""Deployment mistakes must fail before anyone analyzes the wrong data."""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch
from ectlab.runtime import data_path

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / 'docker/start.py'
if not START.exists():
    START = Path('/opt/ect/docker/start.py')
spec = importlib.util.spec_from_file_location('ect_docker_start', START)
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)


class ServerPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT/'results').mkdir(exist_ok=True)

    def test_demo_never_reads_company_mount(self):
        with patch.dict(os.environ, {'ECT_CSV_PATH': '/company/private.csv'}):
            self.assertEqual(data_path(Path('/project'), 'demo', 'C10A'), Path('/project/data/demo/연습용_ECT.csv.gz'))

    def test_company_uses_configured_csv_and_rejects_invalid_mode(self):
        with patch.dict(os.environ, {'ECT_CSV_PATH': '/nas/추가 데이터.csv'}):
            self.assertEqual(data_path('/project', 'company', 'C10A'), Path('/nas/추가 데이터.csv'))
            with self.assertRaises(ValueError):
                data_path('/project', 'typo', 'C10A')

    def test_missing_company_csv_does_not_fall_back_to_demo(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp, patch.dict(os.environ, {'ECT_DATA_MODE': 'company', 'ECT_CSV_PATH': ''}):
            with self.assertRaises(FileNotFoundError):
                start.prepare(Path(temp), Path(temp), Path(temp))

    def test_notebook_edits_and_output_survive_another_start(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'results') as temp, patch.dict(os.environ, {'ECT_DATA_MODE': 'demo', 'ECT_CSV_PATH': '/company.csv'}):
            root=Path(temp)/'project'; out=Path(temp)/'output'; templates=Path(temp)/'templates'
            templates.mkdir(); (templates/'test.ipynb').write_text('template', encoding='utf-8')
            start.prepare(root, out, templates)
            self.assertNotIn('ECT_CSV_PATH', os.environ)
            (root/'notebooks/test.ipynb').write_text('user edit', encoding='utf-8')
            (out/'results/report.html').write_text('result', encoding='utf-8')
            start.prepare(root, out, templates)
            self.assertEqual((root/'notebooks/test.ipynb').read_text(), 'user edit')
            self.assertEqual((out/'results/report.html').read_text(), 'result')
