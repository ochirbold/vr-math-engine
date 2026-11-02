import concurrent.futures
import time
import pytest
from math_engine.contracts import ModelSpec, JobRequest, Dataset, ExecutionResult, WritebackRequest
from math_engine.storage import Conflict, DataStore, JobStore


def setup(tmp_path, persist=False, key='first'):
    store = JobStore(tmp_path / 'jobs.db')
    store.register(ModelSpec(model_id='m', version='1'))
    job = store.submit(JobRequest(model_id='m', model_version='1', snapshot_id='s', idempotency_key=key, persist=persist))
    return store, job


def result():
    return ExecutionResult(model_id='m', model_version='1', status='succeeded', row_ids=['1'], outputs=[{'y': 2}])


def test_versions_and_idempotent_submit(tmp_path):
    store, job = setup(tmp_path)
    req = JobRequest(model_id='m', model_version='1', snapshot_id='s', idempotency_key='first')
    assert store.submit(req)['id'] == job['id']
    req.persist = True
    with pytest.raises(Conflict):
        store.submit(req)
    with pytest.raises(Conflict):
        store.register(ModelSpec(model_id='m', version='1', inputs=['x']))


def test_concurrent_claim_only_one_owner(tmp_path):
    store, job = setup(tmp_path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: store.claim(), range(8)))
    assert sum(x is not None for x in claimed) == 1


def test_restart_and_lease_fencing(tmp_path):
    store, job = setup(tmp_path)
    first = store.claim(lease_seconds=-1)
    restarted = JobStore(tmp_path / 'jobs.db')
    second = restarted.claim()
    assert second['lease'] != first['lease']
    with pytest.raises(Conflict):
        store.computed(job['id'], first['lease'], result())
    restarted.computed(job['id'], second['lease'], result())
    assert restarted.get(job['id'])['state'] == 'SUCCEEDED'
    assert restarted.get(job['id'])['persist_attempts'] == 0


def test_persist_retry_preserves_computed_result(tmp_path):
    store, job = setup(tmp_path, persist=True)
    compute = store.claim()
    store.computed(job['id'], compute['lease'], result())
    persistence = store.claim(lease_seconds=-1)
    recovered = JobStore(tmp_path / 'jobs.db').claim()
    assert recovered['state'] == 'PERSISTING'
    assert recovered['compute_attempts'] == 1
    assert recovered['result']['outputs'] == [{'y': 2}]
    store.persisted(job['id'], recovered['lease'])
    assert store.get(job['id'])['state'] == 'SUCCEEDED'


def test_cancel_and_retry_budget(tmp_path):
    store, job = setup(tmp_path)
    claimed = store.claim()
    store.cancel(job['id'])
    with pytest.raises(Conflict):
        store.computed(job['id'], claimed['lease'], result())
    assert store.claim() is None
    _, job2 = setup(tmp_path, key='second')
    for _ in range(3):
        assert store.claim(lease_seconds=-1)
    assert store.claim() is None
    assert store.get(job2['id'])['state'] == 'FAILED'


def test_snapshot_and_writeback_idempotency(tmp_path):
    store = DataStore(tmp_path / 'data.db')
    dataset = Dataset(row_ids=['a'], rows=[{'x': 1}])
    snapshot = store.snapshot(dataset)['snapshot_id']
    assert store.snapshot(dataset)['snapshot_id'] == snapshot
    request = WritebackRequest(job_id='j', snapshot_id=snapshot, row_ids=['a'], outputs=[{'y': 2}])
    store.writeback(request)
    store.writeback(request)
    assert store.read(snapshot) == dataset.model_dump()
    request.outputs = [{'y': 3}]
    with pytest.raises(Conflict):
        store.writeback(request)
    request.row_ids = ['wrong']
    with pytest.raises(Conflict):
        store.writeback(request)


def test_compute_overload_does_not_exhaust_retry_budget(tmp_path):
    store, job = setup(tmp_path)
    claim = store.claim()
    store.fail(job['id'], claim['lease'], 'busy', busy=True)
    updated = store.get(job['id'])
    assert updated['state'] == 'QUEUED'
    assert updated['compute_attempts'] == 0
