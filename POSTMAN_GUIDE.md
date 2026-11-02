# Math Engine Platform — Postman / REST API Guide

Локал HTTP services-ийг Postman, curl эсвэл ямар ч REST клиентээр турших бүрэн жишээтэй гарын авлага.

---

## 1. Services асаах

```powershell
$env:SERVICE_TOKEN="local-demo-replace-this-token"
.\.venv\Scripts\python.exe scripts/dev_stack.py
```

Асаалттай болмогц:
- **Jobs:** http://127.0.0.1:8100
- **Data:** http://127.0.0.1:8101
- **Compute:** http://127.0.0.1:8102

Ctrl+C-ээр зогсооно.

---

## 2. Postman тохиргоо

Бүх хүсэлтэд дараах header-үүд шаардлагатай:

| Key | Value |
|---|---|
| `X-Service-Token` | `local-demo-replace-this-token` |
| `Content-Type` | `application/json` |

Postman-д: **Headers tab** → дээрх хоёрыг оруулна.

OpenAPI (Swagger) docs:
- http://127.0.0.1:8100/docs — Jobs API
- http://127.0.0.1:8101/docs — Data API
- http://127.0.0.1:8102/docs — Compute API

---

## 3. Шууд тооцоолол (Compute API)

Хамгийн хялбар арга — бүтэн `ExecutionRequest` (model + dataset + parameters) шууд илгээнэ.

### `POST http://127.0.0.1:8102/v1/executions`

**Calculation жишээ** — `examples/calculation.json`-ийг шууд body-д хуулна:

```json
{
  "model": {
    "model_id": "invoice-calculation", "version": "1", "kind": "calculation",
    "inputs": ["QTY", "UNIT_PRICE", "DISCOUNT"],
    "formulas": [
      {"target": "NET", "expression": "max(0, TOTAL - DISCOUNT)", "stage": "row"},
      {"target": "TOTAL", "expression": "QTY * UNIT_PRICE", "stage": "row"},
      {"target": "GRAND_TOTAL", "expression": "COLUMN_SUM('NET')", "stage": "aggregate"}
    ]
  },
  "dataset": {
    "row_ids": ["101", "102"],
    "rows": [{"QTY": 2, "UNIT_PRICE": 120, "DISCOUNT": 15}, {"QTY": 3, "UNIT_PRICE": 80, "DISCOUNT": 30}]
  }
}
```

**Хүлээгдэх хариу (200):**
```json
{
  "status": "succeeded",
  "outputs": [{"NET": 225.0, "TOTAL": 240.0, ...}, ...],
  "aggregates": {"GRAND_TOTAL": 435.0, ...}
}
```

**curl жишээ:**
```bash
curl -X POST http://127.0.0.1:8102/v1/executions \
  -H "X-Service-Token: local-demo-replace-this-token" \
  -H "Content-Type: application/json" \
  -d @examples/calculation.json
```

### LP (Linear Program) жишээ

`examples/allocation.json` — шууд body-д:

```json
{
  "model": {
    "model_id": "resource-allocation", "version": "1", "kind": "linear_program",
    "inputs": ["BENEFIT", "LIMIT"], "parameters": ["CAPACITY"],
    "decisions": {"allocation": {"size": "rows", "lower": 0}},
    "objective": {"sense": "maximize", "expression": "DOT(COLUMN('BENEFIT'), allocation) + 7"},
    "constraints": ["allocation <= COLUMN('LIMIT')", "SUM(allocation) <= CAPACITY"],
    "formulas": [{"target": "ALLOCATED", "expression": "allocation", "stage": "post"}]
  },
  "dataset": {"row_ids": ["A", "B"], "rows": [{"BENEFIT": 10, "LIMIT": 4}, {"BENEFIT": 6, "LIMIT": 5}]},
  "parameters": {"CAPACITY": 6}
}
```

### Scenario жишээ

`examples/scenario_balance.json` — weighted finite scenarios дээрх optimization:

```json
{
  "model": {
    "model_id": "asymmetric-balance", "version": "1", "kind": "scenario_program",
    "inputs": ["requirement", "weight"], "weight_column": "weight",
    "parameters": ["over_cost", "under_cost"],
    "formulas": [{"target": "loss", "expression": "over_cost * positive_part(level - requirement) + under_cost * positive_part(requirement - level)"}],
    "decisions": {"level": {"values": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}},
    "objective": {"expression": "loss", "operation": "expectation", "sense": "minimize"},
    "reductions": {"mean_requirement": {"expression": "requirement", "operation": "expectation"},
                   "target_quantile": {"expression": "requirement", "operation": "quantile", "probability": "under_cost / (over_cost + under_cost)"}}
  },
  "parameters": {"over_cost": 2, "under_cost": 8},
  "dataset": {"row_ids": ["low", "medium", "high"], "rows": [
    {"requirement": 2, "weight": 0.2}, {"requirement": 5, "weight": 0.5}, {"requirement": 9, "weight": 0.3}]}
}
```

### Бусад compute endpoints

| Method | Endpoint | Зориулалт |
|---|---|---|
| POST | `/v1/models/validate` | Model syntax/dependency шалгах (зөвхөн model object илгээнэ) |
| GET | `/v1/capabilities` | Дэмждэг функц, backend, distribution жагсаах |
| POST | `/v1/predictions` | Fitted artifact + dataset → prediction |

---

## 4. Job Pipeline (Model → Snapshot → Job → Result)

Бүрэн асинхрон урсгал: model бүртгэх → snapshot үүсгэх → job submit → result авах.

### 4.1 Model бүртгэх

`POST http://127.0.0.1:8100/v1/models`

Body: зөвхөн `model` object (dataset параметр шаардлагагүй):

```json
{
  "model_id": "invoice-calculation", "version": "1", "kind": "calculation",
  "inputs": ["QTY", "UNIT_PRICE", "DISCOUNT"],
  "formulas": [
    {"target": "NET", "expression": "max(0, TOTAL - DISCOUNT)", "stage": "row"},
    {"target": "TOTAL", "expression": "QTY * UNIT_PRICE", "stage": "row"},
    {"target": "GRAND_TOTAL", "expression": "COLUMN_SUM('NET')", "stage": "aggregate"}
  ]
}
```

### 4.2 Snapshot үүсгэх

`POST http://127.0.0.1:8101/v1/snapshots`

Body: зөвхөн `dataset` object:

```json
{
  "row_ids": ["101", "102"],
  "rows": [{"QTY": 2, "UNIT_PRICE": 120, "DISCOUNT": 15}, {"QTY": 3, "UNIT_PRICE": 80, "DISCOUNT": 30}]
}
```

Хариу: `{"snapshot_id": "...", "checksum": "..."}` — `snapshot_id`-г дараагийн job-д ашиглана.

### 4.3 Job submit

`POST http://127.0.0.1:8100/v1/jobs`

```json
{
  "model_id": "invoice-calculation",
  "model_version": "1",
  "snapshot_id": "<snapshot_id from step 4.2>",
  "parameters": {},
  "persist": false,
  "idempotency_key": "my-unique-key-001"
}
```

Хариу: `{"job_id": "...", "state": "QUEUED", ...}`

### 4.4 Job status / result

```
GET http://127.0.0.1:8100/v1/jobs/{job_id}
GET http://127.0.0.1:8100/v1/jobs/{job_id}/result
```

Worker job-ийг аваад compute хийж, result хадгална. `state` нь `QUEUED → RUNNING → SUCCEEDED`.

---

## 5. Curl жишээнүүд (бүртгэгдсэн pipeline)

```bash
# 1. Snapshot үүсгэх
curl -X POST http://127.0.0.1:8101/v1/snapshots \
  -H "X-Service-Token: local-demo-replace-this-token" \
  -H "Content-Type: application/json" \
  -d '{"row_ids":["1"],"rows":[{"x":5}]}'
# → {"snapshot_id": "abc123...", ...}

# 2. Model бүртгэх
curl -X POST http://127.0.0.1:8100/v1/models \
  -H "X-Service-Token: local-demo-replace-this-token" \
  -H "Content-Type: application/json" \
  -d '{"model_id":"double","version":"1","kind":"calculation","inputs":["x"],"formulas":[{"target":"Y2","expression":"x*2"}]}'

# 3. Job submit
curl -X POST http://127.0.0.1:8100/v1/jobs \
  -H "X-Service-Token: local-demo-replace-this-token" \
  -H "Content-Type: application/json" \
  -d '{"model_id":"double","model_version":"1","snapshot_id":"abc123...","idempotency_key":"demo-1"}'

# 4. Result авах
curl -H "X-Service-Token: local-demo-replace-this-token" \
  http://127.0.0.1:8100/v1/jobs/<job_id>/result
```

---

## 6. Алдааны код

| HTTP | Шалтгаан |
|---|---|
| 401 | `X-Service-Token` буруу эсвэл дутуу |
| 409 | Conflict: ижил idempotency_key өөр body-той, snapshot олдсонгүй, job terminal төлөвтэй |
| 422 | Model/dataset validation алдаа |
| 429 | Compute slot завгүй — дахин оролдоно |
| 504 | Execution wall timeout (90 сек) |
