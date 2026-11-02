import os
from fastapi import HTTPException
from .common import application
from ..compiler import validate_model
from ..contracts import Contract, ExecutionResult, JobRequest, ModelSpec, StatisticalModelSpec, ScenarioModelSpec, IntegrationModelSpec, IndexedModelSpec
from ..storage import JobStore, digest

app = application("Model and Job")
store = JobStore(os.environ.get("JOB_DB", "var/jobs.db"))


class Lease(Contract):
    lease: str


class Computed(Lease):
    result: ExecutionResult


class Failure(Lease):
    message: str
    retryable: bool = True
    busy: bool = False


def public(job):
    return {"job_id": job["id"], "state": job["state"], "result": job["result"], "error": job["error"],
            "compute_attempts": job["compute_attempts"], "persist_attempts": job["persist_attempts"],
            "persist": job["payload"]["request"]["persist"], "created": job["created"]}


@app.post("/v1/models", status_code=201)
def register(model: ModelSpec | StatisticalModelSpec | ScenarioModelSpec | IndexedModelSpec | IntegrationModelSpec):
    validate_model(model)
    return store.register(model)


@app.post("/v1/jobs", status_code=202)
def submit(request: JobRequest):
    return public(store.submit(request))


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    return public(store.get(job_id))


@app.get("/v1/jobs/{job_id}/result")
def result(job_id: str):
    job = store.get(job_id)
    if job["result"] is None:
        raise HTTPException(409, "No computed result yet")
    return job["result"]


@app.get("/v1/jobs/{job_id}/fitted-artifact")
def fitted_artifact(job_id: str):
    result = store.get(job_id)["result"]
    if not result or result["status"] != "succeeded" or not result.get("fitted_artifact"):
        raise HTTPException(409, "No successful fitted artifact for this job")
    artifact = result["fitted_artifact"]
    return {"artifact_id": digest(artifact), "artifact": artifact}


@app.post("/v1/jobs/{job_id}/cancel")
def cancel(job_id: str):
    return store.cancel(job_id)


@app.post("/internal/claims")
def claim():
    return store.claim()


@app.post("/internal/jobs/{job_id}/renew")
def renew(job_id: str, request: Lease):
    return store.renew(job_id, request.lease)


@app.post("/internal/jobs/{job_id}/computed")
def computed(job_id: str, request: Computed):
    return store.computed(job_id, request.lease, request.result)


@app.post("/internal/jobs/{job_id}/persisted")
def persisted(job_id: str, request: Lease):
    return store.persisted(job_id, request.lease)


@app.post("/internal/jobs/{job_id}/fail")
def fail(job_id: str, request: Failure):
    return store.fail(job_id, request.lease, request.message, request.retryable, request.busy)
