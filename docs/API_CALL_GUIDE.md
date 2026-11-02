# API Call Guide

**Math Engine Platform · v0.6.0 · 2026-11-02**

Хадгалалтгүй Compute API-г дуудах гарын авлага. Математик цөмийн 7 төрлийн
загвар тус бүр нэг жижиг, бүтэн хүсэлттэй. Загвар бүр тусдаа endpoint биш:
бүгд `POST /v1/executions` ашиглаж, `model.kind`-аар ялгагдана.

## 1. Холболт

| Тохиргоо | Утга |
|---|---|
| Локал base URL | `http://127.0.0.1:8102` |
| Authentication | `X-Service-Token: <таны хувийн token>` |
| Content-Type | `application/json` |
| Гүйцэтгэл | Синхрон; JSON result шууд буцаана |
| Хадгалалт | Compute нь snapshot/job/result-ийг DB-д хадгалахгүй |

SERVICE_TOKEN тохируулсны дараа сервер дээр `docker compose up --build -d`
ажиллуулна. Docker deployment-ийг target host дээр баталгаажуулах шаардлага
хэвээр. 127.0.0.1 нь **дуудаж буй машины өөрийн хаяг**: өөр машинаас холбогдох
бол хамгаалалттай HTTPS gateway/tunnel-ийн хаягаар base URL-ийг солино.

| Method | Path | Body |
|---|---|---|
| GET | `/health` | Байхгүй |
| GET | `/v1/capabilities` | Байхгүй |
| POST | `/v1/models/validate` | Зөвхөн `model` объект |
| POST | `/v1/executions` | `model` + `dataset` + optional `parameters`, `solver` |
| POST | `/v1/predictions` | `artifact` + `dataset` |

Model урьдчилан бүртгэх, snapshot/job үүсгэх шаардлагагүй. `model_id`, `version`
нь шууд хүсэлтэд metadata; Compute өөрөө version бүртгэл хадгалахгүй.

## 2. Дуудах нийтлэг команд

Repository-ийн үндсэн хавтсаас ажиллуулна. Token-ийг environment-д тохируулсан
байна. Доорх командын JSON файлыг солиход дараагийн бүх жишээг дуудаж болно.

### PowerShell

```powershell
$baseUrl = 'http://127.0.0.1:8102'
$headers = @{ 'X-Service-Token' = $env:SERVICE_TOKEN }
$body = Get-Content 'examples/api/calculation.json' -Raw
$result = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/executions" `
  -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 110
$result | ConvertTo-Json -Depth 30
```

### curl — Bash/Linux

```sh
curl --fail-with-body --max-time 110 \
  -X POST http://127.0.0.1:8102/v1/executions \
  -H "X-Service-Token: $SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @examples/api/calculation.json
```

### Postman

1. Method: **POST**; URL: `{{baseUrl}}/v1/executions`.
2. Header: `X-Service-Token: {{serviceToken}}`; token-ийг хувийн environment-д өгнө.
3. Body → raw → JSON; доорх бүтэн JSON-оос хуулна.
4. Send дараад HTTP status-аас гадна response-ийн **status**-ийг шалгана.

## 3. Загвар тус бүрийн хүсэлт

Доорх JSON бүр бие даан дуудагдана. Буцаах утгын тайлбар нь response-ийн
онцлох хэсэг; engine/model version, row_ids, diagnostics зэрэг талбар мөн ирнэ.

### 3.1. Томьёоны тооцоолол

Тоо хэмжээ 2, нэгж өртөг 10.

Файл: [calculation.json](../examples/api/calculation.json)

```json
{
  "model": {
    "model_id": "api-calculation",
    "version": "1",
    "kind": "calculation",
    "inputs": [
      "quantity",
      "rate"
    ],
    "formulas": [
      {
        "target": "total",
        "expression": "quantity*rate",
        "stage": "row"
      }
    ]
  },
  "dataset": {
    "row_ids": [
      "one"
    ],
    "rows": [
      {
        "quantity": 2,
        "rate": 10
      }
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `outputs[0].total = 20`

### 3.2. Шугаман оновчлол — LP

0 ≤ x ≤ 4 нөхцөлд 3x-ийг хамгийн их болгоно.

Файл: [linear_program.json](../examples/api/linear_program.json)

```json
{
  "model": {
    "model_id": "api-linear-program",
    "version": "1",
    "kind": "linear_program",
    "decisions": {
      "x": {
        "lower": 0,
        "upper": 4
      }
    },
    "objective": {
      "sense": "maximize",
      "expression": "3*x"
    }
  },
  "dataset": {
    "row_ids": [
      "one"
    ],
    "rows": [
      {}
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `solution.x = 4`, `objective = 12`

### 3.3. Бүхэл тоон оновчлол — MILP

x бүхэл тоо, x ≤ 2.7. 3x-ийг хамгийн их болгоно.

Файл: [mixed_integer_program.json](../examples/api/mixed_integer_program.json)

```json
{
  "model": {
    "model_id": "api-mixed-integer-program",
    "version": "1",
    "kind": "mixed_integer_program",
    "decisions": {
      "x": {
        "domain": "integer",
        "lower": 0,
        "upper": 4
      }
    },
    "objective": {
      "sense": "maximize",
      "expression": "3*x"
    },
    "constraints": [
      "x <= 2.7"
    ]
  },
  "dataset": {
    "row_ids": [
      "one"
    ],
    "rows": [
      {}
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `solution.x = 2`, `objective = 6`

### 3.4. Индексжүүлсэн оновчлол

Хоёр өдөрт шаардлагатай хэмжээ 1, 2. Нийт хэмжээг хамгийн бага болгоно.

Файл: [indexed_program.json](../examples/api/indexed_program.json)

```json
{
  "model": {
    "model_id": "api-indexed-program",
    "version": "1",
    "kind": "indexed_program",
    "axes": {
      "t": [
        0,
        1
      ]
    },
    "inputs": [
      "t",
      "need"
    ],
    "tables": {
      "target": {
        "axes": [
          "t"
        ],
        "column": "need"
      }
    },
    "decisions": {
      "quantity": {
        "axes": [
          "t"
        ],
        "domain": "integer",
        "lower": 0,
        "upper": 5
      }
    },
    "objective": {
      "sense": "minimize",
      "terms": [
        {
          "over": [
            "t"
          ],
          "expression": "quantity[t]"
        }
      ]
    },
    "constraints": [
      {
        "over": [
          "t"
        ],
        "expression": "quantity[t] >= target[t]"
      }
    ]
  },
  "dataset": {
    "row_ids": [
      "day0",
      "day1"
    ],
    "rows": [
      {
        "t": 0,
        "need": 1
      },
      {
        "t": 1,
        "need": 2
      }
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `solution.quantity = [1, 2]`, `objective = 3`. Индексийн дараалал `diagnostics.indexed_layout.quantity.indices = [[0],[1]]`.

### 3.5. Статистик fitting

[1,2,3,4,5,3] тооллогоос Poisson-ийн тогтмол mean сургана.

Файл: [statistical_fit.json](../examples/api/statistical_fit.json)

```json
{
  "model": {
    "model_id": "api-statistical-fit",
    "version": "1",
    "kind": "statistical_fit",
    "inputs": [],
    "trainable": {
      "intercept": {
        "initial": 0,
        "lower": -10,
        "upper": 10
      }
    },
    "predictor": "intercept",
    "link": "log",
    "distribution": "poisson",
    "observation": {
      "response": "count"
    }
  },
  "dataset": {
    "row_ids": [
      "1",
      "2",
      "3",
      "4",
      "5",
      "6"
    ],
    "rows": [
      {
        "count": 1
      },
      {
        "count": 2
      },
      {
        "count": 3
      },
      {
        "count": 4
      },
      {
        "count": 5
      },
      {
        "count": 3
      }
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `solution.intercept ≈ 1.098612`, `outputs[*].mean ≈ 3`; `fitted_artifact` объект буцна. `objective` нь negative log-likelihood, ашгийн утга биш.

### 3.6. Scenario шинжилгээ

2 болон 6 гэсэн утгууд тус бүр 0.5 жинтэй. Хүлээгдэж буй утга бодно.

Файл: [scenario_program.json](../examples/api/scenario_program.json)

```json
{
  "model": {
    "model_id": "api-scenario-program",
    "version": "1",
    "kind": "scenario_program",
    "inputs": [
      "value",
      "weight"
    ],
    "weight_column": "weight",
    "reductions": {
      "mean_value": {
        "expression": "value",
        "operation": "expectation"
      }
    }
  },
  "dataset": {
    "row_ids": [
      "low",
      "high"
    ],
    "rows": [
      {
        "value": 2,
        "weight": 0.5
      },
      {
        "value": 6,
        "weight": 0.5
      }
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `aggregates.mean_value = 4`. Энэ жишээ reduction тул `solution` хоосон, `objective` null.

### 3.7. Тоон интеграл

∫₀³ x² dx-ийг тоогоор бодно.

Файл: [numerical_integration.json](../examples/api/numerical_integration.json)

```json
{
  "model": {
    "model_id": "api-numerical-integration",
    "version": "1",
    "kind": "numerical_integration",
    "variable": "x",
    "expression": "x**2",
    "lower": "0",
    "upper": "3"
  },
  "dataset": {
    "row_ids": [
      "one"
    ],
    "rows": [
      {}
    ]
  }
}
```

**Хүлээгдэх хариу:** `status = "succeeded"`; `outputs[0].integral ≈ 9`; `absolute_error_estimate` ба convergence diagnostics буцна. Алдаа нь тоон үнэлгээ, баталгаат дээд хязгаар биш.

## 4. Сурсан загвараар prediction хийх

Энэ нь найм дахь model kind биш; fitting-ийн artifact ашигладаг тусдаа API.
Эхлээд 3.5-ын хүсэлтийг ажиллуулаад буцсан artifact-ийг яг хэвээр дамжуулна.
Доорх PowerShell нь artifact-ийн placeholder шаардахгүй, бүтэн урсгал:

```powershell
$fitBody = Get-Content 'examples/api/statistical_fit.json' -Raw
$fit = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/executions" `
  -Headers $headers -ContentType 'application/json' -Body $fitBody -TimeoutSec 110
if ($fit.status -ne 'succeeded') { throw 'Fitting failed; inspect diagnostics' }
$predictionBody = @{
  artifact = $fit.fitted_artifact
  dataset = @{ row_ids = @('future'); rows = @(@{}) }
} | ConvertTo-Json -Depth 50
$prediction = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/predictions" `
  -Headers $headers -ContentType 'application/json' -Body $predictionBody -TimeoutSec 110
$prediction | ConvertTo-Json -Depth 30
```

Хүлээгдэх prediction: `status=succeeded`, `outputs[0].mean≈3`,
`outputs[0].variance≈3`. Энэ жишээ feature-гүй тул prediction мөр `{}` байна.
Feature-тэй загварт training-ийн inputs нэртэй багануудыг өгнө; response/censor
багана prediction-д шаардахгүй. Artifact-ийг цааш хэрэглэх бол дуудагч хадгална.

## 5. Model validation

Validation-д бүтэн execution request биш **зөвхөн model** өгнө:

```powershell
$request = Get-Content 'examples/api/linear_program.json' -Raw | ConvertFrom-Json
$modelBody = $request.model | ConvertTo-Json -Depth 30
Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/models/validate" `
  -Headers $headers -ContentType 'application/json' -Body $modelBody
```

Validation нь өгөгдөлтэй бодлогод шийдэл байхыг, convergence эсвэл бизнесийн
зөв байдлыг батлахгүй. Dataset-dependent алдаа execution үед илэрч болно.

## 6. Хариу ба алдааг боловсруулах

| Үр дүн | Утга / хийх үйлдэл |
|---|---|
| HTTP 200 + `status=succeeded` | Diagnostics-ийг шалгаад үр дүнг хэрэглэнэ |
| HTTP 200 + infeasible/unbounded/failed | Математик үр дүн амжилтгүй; solver/convergence diagnostics шалгана |
| HTTP 401 | Token дутуу/буруу |
| HTTP 422 | Contract, томьёо, domain эсвэл оролтын алдаа; хүсэлтээ засна |
| HTTP 429 | Compute slot завгүй; Retry-After header-ийг хүндэтгэж дахин оролдоно |
| HTTP 504 | Compute-ийн 90 секундийн wall timeout |
| HTTP 500 | Process/backend алдаа; log, хязгаар, орчныг шалгана |
| Client timeout / connection loss | Хариу алдагдсан эсэх тодорхойгүй; Compute-д job lookup байхгүй |

`outputs`, `aggregates`, `solution`, `objective` нь өөр өөр зориулалттай.
Calculation/integration голчлон outputs; scenario reduction aggregates;
optimizer solution/objective; fitting fitted_artifact буцаана.

Compute нь idempotency key, queue, үр дүн хайх job ID хадгалахгүй. Client retry
тооцоог дахин ажиллуулж болно. Request-д `persist` нэмэхгүй: энэ нь optional
Job API-ийн тохиргоо. Бүтэн job урсгал хэрэгтэй бол [сонголтот deployment](STATELESS_DEPLOYMENT.md)
ба [Postman лавлах](../POSTMAN_GUIDE.md)-ийг үзнэ.

## 7. Жишээнүүдийн баталгаажуулалт

Энэ гарын авлагын 7 JSON нь `examples/api/` дотор байна. HTTP тест
`tests/test_services.py::test_api_guide_examples_http` нь файл бүрийг бодит
локал Compute API-д илгээж дээрх тоон хариутай тулгана. Fitting-ийн artifact-ийг
prediction API-д мөн дамжуулж шалгана. Энэ нь Docker/production host-ийн
байршуулалтын баталгаа биш.

[Математик цөмийн гарын авлага](CORE_ENGINE_GUIDE.md) · [README](../README.md)

2026-11-02 шалгалт: **209 тест давсан (99.44 секунд)**. Үүнд энэ гарын
авлагын 7 HTTP хүсэлт болон fitting → prediction шалгалт багтсан.
