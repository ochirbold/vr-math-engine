"""SQLite stores owned by their services. No shared DB between services."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import Dataset, ExecutionResult, WritebackRequest


class Conflict(ValueError):
    pass


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class DataStore(Store):
    """Immutable input snapshots and idempotent result artifacts, NOT source DB writeback."""
    def __init__(self, path):
        super().__init__(path)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS writebacks(job_id TEXT PRIMARY KEY, body TEXT NOT NULL);
            """)

    def snapshot(self, dataset: Dataset, origin=None):
        body = {"dataset": dataset.model_dump(), "origin": origin}
        key = digest(body)
        with self.connection(True) as conn:
            conn.execute("INSERT OR IGNORE INTO snapshots VALUES (?, ?)", (key, encode(body)))
        return {"snapshot_id": key, "checksum": key}

    def envelope(self, snapshot_id):
        with self.connection() as conn:
            row = conn.execute("SELECT body FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        body = json.loads(row["body"])
        if digest(body) != snapshot_id:
            raise Conflict("Snapshot checksum mismatch")
        return body

    def read(self, snapshot_id):
        return self.envelope(snapshot_id)["dataset"]

    def writeback(self, request: WritebackRequest):
        snapshot = self.read(request.snapshot_id)
        if request.row_ids != snapshot["row_ids"] or len(request.outputs) != len(request.row_ids):
            raise Conflict("Writeback row IDs/order must match snapshot")
        # Output-only dataset: never mutate or overwrite the immutable inputs.
        Dataset(row_ids=request.row_ids, rows=request.outputs)
        body = encode(request.model_dump())
        with self.connection(True) as conn:
            old = conn.execute("SELECT body FROM writebacks WHERE job_id=?", (request.job_id,)).fetchone()
            if old and old["body"] != body:
                raise Conflict("Job already persisted with a different result")
            conn.execute("INSERT OR IGNORE INTO writebacks VALUES (?, ?)", (request.job_id, body))
        return {"job_id": request.job_id, "persisted": True, "destination": "result_artifact"}

    def read_writeback(self, job_id):
        with self.connection() as conn:
            row = conn.execute("SELECT body FROM writebacks WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return json.loads(row["body"])


class JobStore(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS models(id TEXT, version TEXT, body TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT, error TEXT,
                    lease TEXT, lease_until REAL NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
                    compute_attempts INTEGER NOT NULL DEFAULT 0, persist_attempts INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state,available_at,lease_until,created);
            """)

    def register(self, model):
        body = encode(model.model_dump())
        with self.connection(True) as conn:
            row = conn.execute("SELECT body FROM models WHERE id=? AND version=?", (model.model_id, model.version)).fetchone()
            if row and row["body"] != body:
                raise Conflict("Model versions are immutable; use a new version")
            conn.execute("INSERT OR IGNORE INTO models VALUES (?,?,?)", (model.model_id, model.version, body))
        return {"model_id": model.model_id, "version": model.version, "checksum": digest(model.model_dump())}

    def submit(self, request):
        body = request.model_dump()
        with self.connection(True) as conn:
            old = conn.execute("SELECT * FROM jobs WHERE idem=?", (request.idempotency_key,)).fetchone()
            if old:
                if old["request_hash"] != digest(body):
                    raise Conflict("Idempotency key reused with different request")
                return self.unpack(old)
            model = conn.execute("SELECT body FROM models WHERE id=? AND version=?", (request.model_id, request.model_version)).fetchone()
            if model is None:
                raise KeyError("Unknown model version")
            payload = {"request": body, "model": json.loads(model["body"])}
            key = str(uuid.uuid4())
            conn.execute("INSERT INTO jobs(id,idem,request_hash,payload,state,created) VALUES (?,?,?,?,?,?)",
                         (key, request.idempotency_key, digest(body), encode(payload), "QUEUED", time.time()))
            return self.unpack(conn.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone())

    @staticmethod
    def unpack(row):
        value = dict(row)
        value["payload"] = json.loads(value["payload"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def get(self, job_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return self.unpack(row)

    def claim(self, lease_seconds=120):
        now = time.time()
        with self.connection(True) as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE state IN ('QUEUED','RUNNING','COMPUTED','PERSISTING') AND lease_until<=? AND available_at<=? ORDER BY created", (now, now)).fetchall()
            for row in rows:
                persist = row["state"] in ("COMPUTED", "PERSISTING")
                counter = "persist_attempts" if persist else "compute_attempts"
                if row[counter] >= 3:
                    conn.execute("UPDATE jobs SET state='FAILED',error='Retry budget exhausted',lease=NULL WHERE id=?", (row["id"],))
                    continue
                token = str(uuid.uuid4())
                state = "PERSISTING" if persist else "RUNNING"
                conn.execute(f"UPDATE jobs SET state=?,lease=?,lease_until=?,{counter}={counter}+1 WHERE id=?",
                             (state, token, now + lease_seconds, row["id"]))
                return self.unpack(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
        return None

    def owned(self, conn, job_id, lease, state=None):
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        if row["lease"] != lease or row["lease_until"] <= time.time() or row["state"] not in ("RUNNING", "PERSISTING"):
            raise Conflict("Lease expired, replaced or job cancelled")
        if state and row["state"] != state:
            raise Conflict("Wrong job stage")
        return self.unpack(row)

    def renew(self, job_id, lease):
        with self.connection(True) as conn:
            self.owned(conn, job_id, lease)
            conn.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() + 120, job_id))
        return {"renewed": True}

    def computed(self, job_id, lease, result: ExecutionResult):
        with self.connection(True) as conn:
            job = self.owned(conn, job_id, lease, "RUNNING")
            request = job["payload"]["request"]
            if (result.model_id, result.model_version) != (request["model_id"], request["model_version"]):
                raise Conflict("Result model does not match pinned job model")
            pinned = job["payload"]["model"]
            if pinned["kind"] == "statistical_fit" and result.status == "succeeded":
                if result.fitted_artifact is None or result.fitted_artifact.model.model_dump() != pinned:
                    raise Conflict("Successful fit must contain an artifact for the pinned model")
                if result.fitted_artifact.fixed_parameters != request["parameters"]:
                    raise Conflict("Artifact fixed parameters do not match job")
            elif result.fitted_artifact is not None:
                raise Conflict("Unexpected fitted artifact")
            state = "FAILED" if result.status != "succeeded" else ("COMPUTED" if request["persist"] else "SUCCEEDED")
            conn.execute("UPDATE jobs SET state=?,result=?,lease=NULL,lease_until=0,error=? WHERE id=?",
                         (state, encode(result.model_dump()), result.status if state == "FAILED" else None, job_id))
        return {"state": state}

    def persisted(self, job_id, lease):
        with self.connection(True) as conn:
            self.owned(conn, job_id, lease, "PERSISTING")
            conn.execute("UPDATE jobs SET state='SUCCEEDED',lease=NULL,lease_until=0,error=NULL WHERE id=?", (job_id,))
        return {"state": "SUCCEEDED"}

    def fail(self, job_id, lease, message, retryable=True, busy=False):
        with self.connection(True) as conn:
            job = self.owned(conn, job_id, lease)
            persist = job["state"] == "PERSISTING"
            attempts = job["persist_attempts" if persist else "compute_attempts"]
            if busy and not persist:
                conn.execute("UPDATE jobs SET compute_attempts=compute_attempts-1 WHERE id=?", (job_id,))
                attempts -= 1
                retryable = True
            state = ("COMPUTED" if persist else "QUEUED") if retryable and attempts < 3 else "FAILED"
            conn.execute("UPDATE jobs SET state=?,error=?,lease=NULL,lease_until=0,available_at=? WHERE id=?",
                         (state, message[:2000], time.time() + min(2 ** attempts, 30), job_id))
        return {"state": state}

    def cancel(self, job_id):
        with self.connection(True) as conn:
            row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["state"] == "CANCELLED":
                return {"state": "CANCELLED"}
            if row["state"] not in ("QUEUED", "RUNNING", "COMPUTED"):
                raise Conflict("Cannot cancel a terminal job or an in-flight persistence operation")
            conn.execute("UPDATE jobs SET state='CANCELLED',lease=NULL,lease_until=0 WHERE id=?", (job_id,))
        return {"state": "CANCELLED"}
