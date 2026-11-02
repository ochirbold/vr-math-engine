# Server/API readiness review — 2026-11-02

## Decision

The platform has a working authenticated API and asynchronous job execution path.
It is a candidate for a controlled, single-server internal pilot after target-host
smoke testing. It is not yet verified for an internet-facing production deployment.
No target server was supplied or accessed, and no deployment was performed.

## Evidence and scope

- Reviewed compose.yaml, Dockerfile, constraints.txt, service applications,
  process isolation, HTTP client, worker, storage, and service/storage tests.
- Local Python environment: FastAPI 0.135.1, Uvicorn 0.41.0, Pydantic 2.12.5,
  NumPy 2.2.6, SciPy 1.15.3. `pip check`: no broken requirements.
- Full test suite: **179 passed in 116.98 seconds** on 2026-11-02, including real localhost HTTP, worker stages, storage recovery, mathematical verification and process timeout tests.
- Docker CLI is unavailable on this machine. Image build, Compose startup,
  Linux container execution, volume permissions and restart behavior in containers
  have not been exercised here. A Dockerfile is not deployment verification.
- Local HTTP tests start real Uvicorn services and exercise Worker.run_once().
  They do not constitute a long-running production worker/load/soak test.

## What is implemented

| Area | Evidence / behavior |
|---|---|
| API contracts | FastAPI/Pydantic, versioned model registration, snapshots, execution, prediction, jobs and results |
| Authentication | X-Service-Token, constant-time comparison, startup fails for missing/short token |
| Jobs | SQLite WAL, transaction-based claim, lease fencing, heartbeat and bounded retries |
| Duplicate handling | Model version immutability, idempotent job submission and output persistence |
| Recovery | Storage tests cover lease expiry, reopen/recovery and persistence retry without recomputation |
| Compute | Spawned process, 90-second wall limit, one compute slot per API process, 429 when busy |
| Containers | Non-root user, compute CPU/memory/PID limits, separate named data volumes |
| Networking | Compose publishes all API ports only on 127.0.0.1; worker uses internal service names |
| Startup | Worker depends on the three HTTP health checks |

## Before an internal pilot

1. Build and launch Compose on the actual server with a generated private token.
   The example token is accepted by the current code and must be replaced.
2. Verify health and end-to-end calculation, MILP and fitting/prediction calls;
   verify incorrect tokens are rejected. Run jobs with persistence enabled.
3. Restart containers and the host; confirm persisted snapshots, results and queued
   jobs survive. Exercise an interrupted worker and lease recovery on that host.
4. Provide a deliberate remote access path: current localhost bindings cannot be
   called from another machine directly. Use an authenticated HTTPS gateway or a
   controlled private tunnel; do not simply expose every service/internal route.
5. Establish SQLite-consistent backup and restore, retention/disk monitoring, and
   ownership of operations. Restore must be tested, not only backup creation.
6. Measure response times, memory, queue delay and failure recovery with the intended
   model sizes and expected traffic. Current tests do not establish a capacity SLA.

## Before internet-facing or multi-user production

- **Identity/authorization boundary:** all services use one shared token. A token
  holder can call both public routes and `/internal/*` claims/completion routes;
  there is no per-user/tenant ownership authorization. Separate worker/service
  privileges from caller privileges and restrict internal routes at the gateway.
- **TLS and ingress controls:** no HTTPS gateway, request body byte limit or general
  request rate/quota configuration is included. Pydantic row/shape limits apply
  after request parsing and are not a replacement for ingress size controls.
- **Documentation exposure:** `/docs`, `/redoc`, `/openapi.json` are unprotected
  built-in documentation routes. Business endpoints have token dependencies.
  Restrict documentation at ingress if schema exposure is not intended.
- **Readiness/operations:** `/health` returns service/version but does not check DB
  writability, storage capacity or worker liveness. Compose has no worker health
  check, and Docker marking a service unhealthy alone does not restart it.
- **Observability:** worker event logs exist; alerting, metrics, queue/worker health
  dashboards, and request/user audit attribution are not established.
- **Scale/availability:** service-owned SQLite files suit a controlled single-host
  pilot; multi-host failover and replicated database/queue operation are unverified.
  Increasing API workers also increases compute slots; review resource limits first.
- **Release verification:** CI test configuration exists but no CI run was verified
  in this review. Container build/scan and target-host acceptance remain outstanding.

## API usage paths

For immediate small executions, POST the example request JSON to
`http://127.0.0.1:8102/v1/executions` with `X-Service-Token` and application/json.
For queued work: register model on Jobs → create snapshot on Data → submit job
on Jobs → poll status/result. Prefer the queued path for normal server integration.
Clients calling synchronous execution need a timeout compatible with the 90-second
compute wall limit. Job persistence stores service artifacts, not Oracle writeback.

Relevant files: `POSTMAN_GUIDE.md`, `scripts/demo_job.py`, `compose.yaml`,
`tests/test_services.py`, `tests/test_storage.py`.

Mathematical scope is separate from deployment readiness: finite model limits,
finite price candidates and the incomplete large integrated retail model remain
as documented. Successful API deployment does not remove those limitations.
