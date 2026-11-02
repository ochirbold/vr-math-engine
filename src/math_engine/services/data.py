import os
from fastapi import HTTPException
from .common import application
from ..contracts import Contract, Dataset, WritebackRequest
from ..oracle_reader import OracleReader
from ..storage import DataStore

app = application("Data Integration")
store = DataStore(os.environ.get("DATA_DB", "var/data.db"))
oracle = OracleReader.from_environment()


class OracleSnapshot(Contract):
    profile: str
    scenario_code: str


@app.post("/v1/snapshots/oracle", status_code=201)
def oracle_snapshot(request: OracleSnapshot):
    if oracle is None:
        raise HTTPException(409, "Oracle reader is disabled")
    try:
        dataset, origin = oracle.read(request.profile, request.scenario_code)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return store.snapshot(dataset, origin)


@app.get("/v1/snapshots/{snapshot_id}/metadata")
def metadata(snapshot_id: str):
    return {"snapshot_id": snapshot_id, "origin": store.envelope(snapshot_id)["origin"]}


@app.post("/v1/snapshots", status_code=201)
def snapshot(dataset: Dataset):
    return store.snapshot(dataset)


@app.get("/v1/snapshots/{snapshot_id}")
def read(snapshot_id: str):
    return store.read(snapshot_id)


@app.post("/v1/writebacks")
def writeback(request: WritebackRequest):
    return store.writeback(request)


@app.get("/v1/writebacks/{job_id}")
def result(job_id: str):
    return store.read_writeback(job_id)
