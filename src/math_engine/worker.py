"""Lease-based worker. Computation and persistence retry independently."""
import json
import os
import threading
import time
from .http_client import Client, RemoteError


class Worker:
    def __init__(self, jobs, data, compute):
        self.jobs, self.data, self.compute = jobs, data, compute

    def run_once(self):
        job = self.jobs.call("POST", "/internal/claims")
        if job is None:
            return False
        prefix = f"/internal/jobs/{job['id']}"
        lease = {"lease": job["lease"]}
        stopped, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not stopped.wait(15):
                try:
                    self.jobs.call("POST", prefix + "/renew", lease)
                except RemoteError:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            request = job["payload"]["request"]
            if job["state"] == "RUNNING":
                dataset = self.data.call("GET", "/v1/snapshots/" + request["snapshot_id"])
                result = self.compute.call("POST", "/v1/executions", {
                    "model": job["payload"]["model"], "dataset": dataset,
                    "parameters": request["parameters"], "solver": request["solver"]})
                if not lost.is_set():
                    self.jobs.call("POST", prefix + "/computed", lease | {"result": result})
            else:
                # Reconfirm ownership immediately before crossing the persistence boundary.
                self.jobs.call("POST", prefix + "/renew", lease)
                if lost.is_set():
                    return True
                self.data.call("POST", "/v1/writebacks", {
                    "job_id": job["id"], "snapshot_id": request["snapshot_id"],
                    "row_ids": job["result"]["row_ids"], "outputs": job["result"]["outputs"]})
                if not lost.is_set():
                    self.jobs.call("POST", prefix + "/persisted", lease)
            print(json.dumps({"job_id": job["id"], "stage": job["state"], "event": "stage_finished"}), flush=True)
        except RemoteError as exc:
            print(json.dumps({"job_id": job["id"], "stage": job["state"], "error": str(exc)}), flush=True)
            if not lost.is_set():
                try:
                    self.jobs.call("POST", prefix + "/fail", lease | {
                        "message": str(exc), "retryable": exc.code >= 500,
                        "busy": exc.code == 429 and job["state"] == "RUNNING"})
                except RemoteError:
                    pass  # Completion may already be committed; otherwise lease expiry recovers work.
        finally:
            stopped.set()
            thread.join(timeout=2)
        return True


def main():
    token = os.environ["SERVICE_TOKEN"]
    worker = Worker(Client(os.environ.get("JOB_URL", "http://127.0.0.1:8100"), token),
                    Client(os.environ.get("DATA_URL", "http://127.0.0.1:8101"), token),
                    Client(os.environ.get("COMPUTE_URL", "http://127.0.0.1:8102"), token))
    while True:
        try:
            busy = worker.run_once()
        except RemoteError as exc:
            print(json.dumps({"event": "claim_failed", "error": str(exc)}), flush=True)
            busy = False
        if not busy:
            time.sleep(1)


if __name__ == "__main__":
    main()
