"""Use the same notebook locally and with a server-mounted CSV."""
from pathlib import Path
import os


def data_path(root, mode, product):
    if mode not in ('demo', 'company'):
        raise ValueError('DATA_MODE는 "demo" 또는 "company"입니다.')
    if mode == 'demo':
        return Path(root) / 'data/demo/연습용_ECT.csv.gz'
    configured = os.environ.get('ECT_CSV_PATH')
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else Path(root) / path
    return Path(root) / f'data/private/{product}.csv.gz'
