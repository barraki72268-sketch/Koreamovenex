"""Probe Jupyter locally without emitting its authentication token."""
from pathlib import Path
import json
import os
import sys
import urllib.request

for path in Path(os.environ.get('JUPYTER_RUNTIME_DIR', '/tmp/jupyter-runtime')).glob('jpserver-*.json'):
    try:
        info = json.loads(path.read_text())
        request = urllib.request.Request('http://127.0.0.1:8888/api/status',
                                         headers={'Authorization': 'token ' + info['token']})
        with urllib.request.urlopen(request, timeout=3) as response:
            if response.status == 200:
                sys.exit(0)
    except (OSError, ValueError, KeyError):
        continue
sys.exit(1)
