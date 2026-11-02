"""Real HTTP integration; launches only local processes with temporary databases."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import pytest
from math_engine.http_client import Client, RemoteError
from math_engine.worker import Worker
from math_engine.isolated import execute_isolated

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


@pytest.fixture(scope='module')
def stack(tmp_path_factory):
    directory = tmp_path_factory.mktemp('services')
    token = 'integration-test-token-not-for-deployment'
    env = os.environ | {'SERVICE_TOKEN': token, 'PYTHONPATH': str(ROOT / 'src'),
                        'PYTHONDONTWRITEBYTECODE': '1', 'JOB_DB': str(directory / 'jobs.db'),
                        'DATA_DB': str(directory / 'data.db'), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
    for key in list(env):
        if key.startswith('ORACLE_'):
            del env[key]
    processes, logs, clients = [], [], {}
    try:
        for name in ('jobs', 'data', 'compute'):
            number = port()
            log = (directory / (name + '.log')).open('w+')
            logs.append(log)
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', f'math_engine.services.{name}:app',
                                        '--host', '127.0.0.1', '--port', str(number)],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
            processes.append(process)
            client = Client(f'http://127.0.0.1:{number}', token, timeout=30)
            clients[name] = client
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    client.call('GET', '/health')
                    break
                except RemoteError as exc:
                    last_error = str(exc)
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail(log.read())
                    time.sleep(.1)
            else:
                log.seek(0)
                pytest.fail(f'{name} startup timeout: {last_error}\n{log.read()}')
        yield clients
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


@pytest.mark.parametrize('example,persist', [('calculation', False), ('allocation', True)])
def test_real_http_job_execution(stack, example, persist):
    jobs, data, compute = (stack[x] for x in ('jobs', 'data', 'compute'))
    request = json.loads((ROOT / 'examples' / (example + '.json')).read_text())
    assert compute.call('POST', '/v1/models/validate', request['model'])['valid']
    jobs.call('POST', '/v1/models', request['model'])
    snapshot = data.call('POST', '/v1/snapshots', request['dataset'])['snapshot_id']
    body = {'model_id': request['model']['model_id'], 'model_version': '1', 'snapshot_id': snapshot,
            'parameters': request.get('parameters', {}), 'persist': persist, 'idempotency_key': example}
    job = jobs.call('POST', '/v1/jobs', body)
    assert jobs.call('POST', '/v1/jobs', body)['job_id'] == job['job_id']
    worker = Worker(jobs, data, compute)
    assert worker.run_once()
    computed = jobs.call('GET', '/v1/jobs/' + job['job_id'])
    assert computed['state'] == ('COMPUTED' if persist else 'SUCCEEDED')
    if persist:
        assert worker.run_once()
        assert data.call('GET', '/v1/writebacks/' + job['job_id'])['outputs'] == [{'ALLOCATED': 4}, {'ALLOCATED': 2}]
    else:
        assert computed['result']['aggregates']['GRAND_TOTAL'] == 435
        with pytest.raises(RemoteError) as exc:
            data.call('GET', '/v1/writebacks/' + job['job_id'])
        assert exc.value.code == 404
    assert jobs.call('GET', '/v1/jobs/' + job['job_id'])['state'] == 'SUCCEEDED'
    assert data.call('GET', '/v1/snapshots/' + snapshot) == request['dataset']


def test_auth_validation_and_cancel(stack):
    with pytest.raises(RemoteError) as exc:
        Client(stack['jobs'].base, 'wrong').call('GET', '/health')
    assert exc.value.code == 401
    raw = json.loads((ROOT / 'examples' / 'calculation.json').read_text())
    stack['jobs'].call('POST', '/v1/models', raw['model'])
    raw['model']['formulas'][0]['expression'] = "__import__('os')"
    with pytest.raises(RemoteError) as exc:
        stack['compute'].call('POST', '/v1/models/validate', raw['model'])
    assert exc.value.code == 422
    body = {'model_id': 'invoice-calculation', 'model_version': '1', 'snapshot_id': 'unused', 'idempotency_key': 'cancel'}
    job = stack['jobs'].call('POST', '/v1/jobs', body)
    stack['jobs'].call('POST', '/v1/jobs/' + job['job_id'] + '/cancel')
    assert stack['jobs'].call('POST', '/internal/claims') is None
    with pytest.raises(RemoteError) as exc:
        stack['data'].call('POST', '/v1/snapshots/oracle', {'profile': 'test', 'scenario_code': 'TEST_01'})
    assert exc.value.code == 409


def test_process_wall_timeout():
    payload = json.loads((ROOT / 'examples' / 'allocation.json').read_text())
    assert execute_isolated(payload, timeout=0)['timeout'] is True


@pytest.mark.parametrize('name', ['poisson', 'negative_binomial'])
def test_fit_job_artifact_prediction_http(stack, name):
    jobs, data, compute = (stack[x] for x in ('jobs', 'data', 'compute'))
    raw = json.loads((ROOT / 'examples' / (name + '.json')).read_text())
    assert compute.call('POST', '/v1/models/validate', raw['model'])['predictor_shape'] == 'scalar'
    assert 'log' in compute.call('GET', '/v1/capabilities')['functions']
    jobs.call('POST', '/v1/models', raw['model'])
    snapshot = data.call('POST', '/v1/snapshots', raw['dataset'])['snapshot_id']
    job = jobs.call('POST', '/v1/jobs', {'model_id': raw['model']['model_id'], 'model_version': '1',
                                       'snapshot_id': snapshot, 'persist': True, 'idempotency_key': name})
    worker = Worker(jobs, data, compute)
    assert worker.run_once()
    state = jobs.call('GET', '/v1/jobs/' + job['job_id'])
    assert state['state'] == 'COMPUTED', state
    path = '/v1/jobs/' + job['job_id'] + '/fitted-artifact'
    artifact = jobs.call('GET', path)
    assert len(artifact['artifact_id']) == 64
    assert worker.run_once()
    assert jobs.call('GET', path) == artifact
    prediction = compute.call('POST', '/v1/predictions', {
        'artifact': artifact['artifact'], 'dataset': {'row_ids': ['future'], 'rows': [{}]}})
    assert prediction['outputs'][0] == state['result']['outputs'][0]
    assert prediction['fitted_artifact'] is None
    saved = data.call('GET', '/v1/writebacks/' + job['job_id'])
    assert saved['outputs'] == state['result']['outputs']
    with pytest.raises(RemoteError) as exc:
        compute.call('POST', '/v1/predictions', {'artifact': artifact['artifact'],
                                               'dataset': {'row_ids': ['future'], 'rows': [{'count': 1}]}})
    assert exc.value.code == 422


@pytest.mark.parametrize('name', ['scenario_balance', 'scenario_capacity', 'scenario_sampling', 'finite_price_optimization'])
def test_generic_scenario_job_http(stack, name):
    jobs, data, compute = (stack[x] for x in ('jobs', 'data', 'compute'))
    raw = json.loads((ROOT / 'examples' / (name + '.json')).read_text())
    validation = compute.call('POST', '/v1/models/validate', raw['model'])
    assert validation['kind'] == 'scenario_program'
    assert 'scenario_program' in compute.call('GET', '/v1/capabilities')['backends']
    jobs.call('POST', '/v1/models', raw['model'])
    snapshot = data.call('POST', '/v1/snapshots', raw['dataset'])['snapshot_id']
    job = jobs.call('POST', '/v1/jobs', {'model_id': raw['model']['model_id'], 'model_version': '1',
                                       'snapshot_id': snapshot, 'parameters': raw['parameters'],
                                       'persist': True, 'idempotency_key': name})
    worker = Worker(jobs, data, compute)
    assert worker.run_once()
    result = jobs.call('GET', '/v1/jobs/' + job['job_id'] + '/result')
    assert result['status'] == 'succeeded', result
    if name == 'scenario_balance':
        assert result['solution'] == {'level': 9}
        assert result['aggregates']['target_quantile'] == 9
    elif name == 'finite_price_optimization':
        assert result['solution'] == {'price_A': 8, 'price_B': 10}
        assert result['objective'] == pytest.approx(38.77374825146319)
    elif name == 'scenario_capacity':
        assert result['solution'] == {'units': 2}
    else:
        assert result['diagnostics']['scenario_count'] == 5000
        assert result['aggregates']['mean_total'] == pytest.approx(10, abs=.3)
    assert result['row_ids'] == raw['dataset']['row_ids']
    assert worker.run_once()
    saved = data.call('GET', '/v1/writebacks/' + job['job_id'])
    assert saved['row_ids'] == raw['dataset']['row_ids']
    assert jobs.call('GET', '/v1/jobs/' + job['job_id'])['state'] == 'SUCCEEDED'


@pytest.mark.parametrize('name,objective,decision,expected', [
    ('indexed_allocation', 14.2, 'allocation', [3, 3, 1]),
    ('indexed_replenishment', 9.5, 'order', [4, 0]),
    ('indexed_information', 6, 'choice', [3, 3, 2, 4]),
    ('indexed_transfer', 26, 'transfer', [0, 0, 6, 0, 0, 0, 0, 0]),
    ('indexed_assortment', 56.8629436111989, 'facings', [1, 1, 1]),
    ('indexed_markdown', 64.3, 'selling_price', [10, 10, 10]),
    ('indexed_supplier', 13, 'order', [6, 0, 0, 0]),
    ('indexed_profit', 22.3, 'order', [4, 0, 2, 0])])
def test_indexed_milp_job_http(stack, name, objective, decision, expected):
    jobs, data, compute = (stack[x] for x in ('jobs', 'data', 'compute'))
    raw = json.loads((ROOT / 'examples' / (name + '.json')).read_text())
    assert compute.call('POST', '/v1/models/validate', raw['model'])['backend'] == 'indexed_linear_milp'
    jobs.call('POST', '/v1/models', raw['model'])
    snapshot = data.call('POST', '/v1/snapshots', raw['dataset'])['snapshot_id']
    job = jobs.call('POST', '/v1/jobs', {'model_id': raw['model']['model_id'], 'model_version': '1',
                                       'snapshot_id': snapshot, 'parameters': raw.get('parameters', {}),
                                       'persist': True, 'idempotency_key': name})
    worker = Worker(jobs, data, compute)
    assert worker.run_once()
    result = jobs.call('GET', '/v1/jobs/' + job['job_id'] + '/result')
    assert result['status'] == 'succeeded', result
    assert result['objective'] == pytest.approx(objective)
    assert result['solution'][decision] == expected
    assert result['diagnostics']['solver'] == 'scipy-highs-milp'
    assert result['diagnostics']['mip_gap'] == 0
    assert result['diagnostics']['max_constraint_violation'] < 1e-7
    assert worker.run_once()
    assert jobs.call('GET', '/v1/jobs/' + job['job_id'])['state'] == 'SUCCEEDED'


def test_direct_mixed_integer_contract_http(stack):
    raw = {'model': {'kind': 'mixed_integer_program', 'model_id': 'integer-http', 'version': '1',
                     'decisions': {'quantity': {'domain': 'integer', 'upper': 4}},
                     'constraints': ['quantity <= 2.7'],
                     'objective': {'sense': 'maximize', 'expression': 'quantity'}},
           'dataset': {'row_ids': ['1'], 'rows': [{}]}}
    assert stack['compute'].call('POST', '/v1/executions', raw)['solution'] == {'quantity': 2}
    assert 'mixed_integer_program' in stack['compute'].call('GET', '/v1/capabilities')['backends']

def test_integration_job_http(stack):
    jobs, data, compute = (stack[x] for x in ('jobs', 'data', 'compute'))
    raw = json.loads((ROOT / 'examples' / 'integration.json').read_text())
    assert compute.call('POST', '/v1/models/validate', raw['model'])['kind'] == 'numerical_integration'
    assert 'numerical_integration' in compute.call('GET', '/v1/capabilities')['backends']
    jobs.call('POST', '/v1/models', raw['model'])
    snapshot = data.call('POST', '/v1/snapshots', raw['dataset'])['snapshot_id']
    job = jobs.call('POST', '/v1/jobs', {'model_id': raw['model']['model_id'], 'model_version': '1',
        'snapshot_id': snapshot, 'parameters': raw['parameters'], 'persist': True, 'idempotency_key': 'integral-job'})
    worker = Worker(jobs, data, compute)
    assert worker.run_once()
    result = jobs.call('GET', '/v1/jobs/' + job['job_id'] + '/result')
    assert result['status'] == 'succeeded'
    assert [o['integral'] for o in result['outputs']] == [8,-8]
    assert worker.run_once()
    assert data.call('GET', '/v1/writebacks/' + job['job_id'])['outputs'] == result['outputs']
