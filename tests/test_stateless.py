"""Compute execution must not instantiate optional service stores."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_compute_without_storage(tmp_path):
    root = Path(__file__).resolve().parents[1]
    request = json.loads((root/'examples/calculation.json').read_text())
    script = tmp_path/'probe.py'
    script.write_text('''import json
from math_engine.contracts import ExecutionRequest
from math_engine.services.compute import execute
if __name__ == '__main__':
    result = execute(ExecutionRequest.model_validate(json.loads(input())))
    assert result['status'] == 'succeeded'
    assert result['aggregates']['GRAND_TOTAL'] == 435
''')
    env = os.environ | {'SERVICE_TOKEN':'stateless-test-private-token',
        'PYTHONPATH':str(root/'src'), 'PYTHONDONTWRITEBYTECODE':'1',
        'JOB_DB':str(tmp_path/'jobs.db'), 'DATA_DB':str(tmp_path/'data.db')}
    result = subprocess.run([sys.executable,str(script)],input=json.dumps(request),
        text=True,cwd=tmp_path,env=env,capture_output=True,timeout=100)
    assert result.returncode == 0, result.stderr
    assert {p.name for p in tmp_path.iterdir()} == {'probe.py'}
