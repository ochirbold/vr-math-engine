import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from math_engine.http_client import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('example', choices=['integration', 'calculation', 'allocation', 'poisson', 'negative_binomial',
                                          'scenario_balance', 'scenario_capacity', 'scenario_sampling',
                                          'indexed_allocation', 'indexed_replenishment', 'indexed_information',
                                          'indexed_transfer', 'indexed_assortment', 'indexed_markdown', 'finite_price_optimization', 'indexed_supplier', 'indexed_profit'])
    parser.add_argument('--persist', action='store_true', help='Save output artifact in Data service; never writes Oracle')
    args = parser.parse_args()
    token = os.environ['SERVICE_TOKEN']
    jobs = Client(os.environ.get('JOB_URL', 'http://127.0.0.1:8100'), token)
    data = Client(os.environ.get('DATA_URL', 'http://127.0.0.1:8101'), token)
    raw = json.loads((ROOT / 'examples' / (args.example + '.json')).read_text())
    jobs.call('POST', '/v1/models', raw['model'])
    snapshot = data.call('POST', '/v1/snapshots', raw['dataset'])['snapshot_id']
    job = jobs.call('POST', '/v1/jobs', {'model_id': raw['model']['model_id'], 'model_version': raw['model']['version'],
                                      'snapshot_id': snapshot, 'parameters': raw.get('parameters', {}),
                                      'persist': args.persist, 'idempotency_key': str(uuid.uuid4())})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = jobs.call('GET', '/v1/jobs/' + job['job_id'])
        if state['state'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            if state['state'] == 'SUCCEEDED' and raw['model']['kind'] == 'statistical_fit':
                artifact = jobs.call('GET', '/v1/jobs/' + job['job_id'] + '/fitted-artifact')
                compute = Client(os.environ.get('COMPUTE_URL', 'http://127.0.0.1:8102'), token)
                state['prediction_demo'] = compute.call('POST', '/v1/predictions', {
                    'artifact': artifact['artifact'], 'dataset': {'row_ids': ['future'], 'rows': [{}]}})
            print(json.dumps(state, indent=2))
            raise SystemExit(0 if state['state'] == 'SUCCEEDED' else 1)
        time.sleep(.5)
    raise SystemExit('Demo timed out; inspect job ' + job['job_id'])


if __name__ == '__main__':
    main()
