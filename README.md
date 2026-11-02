# Math Engine Platform

**Өгөгдөл, томьёо, зорилгын функц, хязгаарлалтаар тодорхойлсон математик загваруудыг CLI болон HTTP API-аар ажиллуулах платформ.**

Хөдөлгүүр нь тооцоолол, шугаман болон холимог бүхэл тоон оновчлол, статистик fitting, scenario шинжилгээг нэг хувилбаржуулсан contract-аар хүлээн авна. Бизнесийн загварыг JSON-оор тодорхойлж, цөмийн кодыг өөрчлөхгүйгээр дэмжигдсэн математик бүтцэд багтаан ажиллуулна. Retail болон CVP нь хэрэглээний жишээнүүд; цөм нь эдгээр домэйны нэршлээс хамаарахгүй.

| Үзүүлэлт | Одоогийн төлөв |
|---|---|
| Хувилбар | **0.6.0** |
| README шинэчилсэн | 2026-11-02 |
| Сүүлийн бүрэн шалгалт | 2026-11-02: **202 тест давсан** (72.50 секунд); хадгалалтгүй compute шалгалт багтсан |
| Баталгаажсан орчин | Локал Python 3.10, бодит localhost HTTP сервисүүд |
| Байршуулалтын түвшин | Дотоод серверийн pilot-д шилжүүлэх суурь; target host шалгалт шаардлагатай |
| Production статус | Docker build/run, хамгаалалт, ачаалал, backup/restore бүрэн баталгаажаагүй |

Энэ хавтас нь хуучин CVP төслөөс тусдаа repository. Хуучин төслийг import хийхгүй, түүний API/DSL-ийн шууд орлуулалт биш.

## Баримт бичиг

- [Математик цөмийн гарын авлага — эндээс эхлэх](docs/CORE_ENGINE_GUIDE.md)

- [Серверт байрлах файлууд, үүрэг ба бэлэн байдал](docs/SERVER_FILES_AND_READINESS.md)
- [Сервер/API бэлэн байдлын шалгалт](docs/SERVER_READINESS_2026-11-02.md)
- [Postman гарын авлага](POSTMAN_GUIDE.md)
- [Индексжүүлсэн MILP, мэдээллийн нөхцөл](docs/INDEXED_MILP.md)
- [Тоон интеграл](docs/NUMERICAL_INTEGRATION.md)
- [Scenario загварууд](docs/SCENARIO_MODELS.md)
- [Статистик fitting, prediction ба demand pilot](docs/STATISTICS_AND_DEMAND.md)
- [Transfer / Assortment](docs/TRANSFER_ASSORTMENT.md) · [Markdown / Price](docs/FINITE_PRICING.md) · [Supplier / Profit](docs/SUPPLIER_PROFIT.md)

## Дэмждэг математик загварууд

| `kind` | Чадамж | Тооцоолох арга |
|---|---|---|
| `numerical_integration` | Нэг хувьсагчийн finite тодорхой интеграл, error estimate | SciPy quad / QUADPACK |
| `calculation` | Мөрийн томьёо, агрегат, дараах тооцоолол | Хязгаарлагдсан AST interpreter |
| `linear_program` | Тасралтгүй хувьсагчтай шугаман зорилго, нөхцөл | SciPy `linprog` / HiGHS |
| `mixed_integer_program` | Integer/binary шийдвэр, шугаман нөхцөл | SciPy `milp` / HiGHS |
| `indexed_program` | Индекс, хугацааны boundary, нийлбэр, scenario information partition | Finite expansion → LP/MILP |
| `statistical_fit` | Poisson/NB likelihood, exact/right-censored ажиглалт | L-BFGS-B; fitted artifact ба prediction |
| `scenario_program` | Weighted scenario, sampling, expectation/variance/quantile, finite candidate optimization | Finite measure ба enumeration |

Шийдвэрээс хамаарах дурын nonlinear томьёог LP/MILP гэж бодохгүй. `log`, `exp` зэрэг функц тоон тооцоололд байдаг нь ерөнхий nonlinear constraint solver байгаа гэсэн үг биш. `positive_part`-ийн affine оролтыг MILP-д хэрэглэхэд ил тод, төгсгөлөг bounds шаардлагатай.

### Томьёо ба contract

Оролтын үндсэн хэсгүүд нь `model`, `dataset`, `parameters`, шаардлагатай үед `solver`. Загвар бүр `model_id`, `version`, `kind`-тэй; бусад талбар нь төрлөөс хамаарна. Dataset нь давтагдашгүй `row_ids` болон тоон `rows` агуулна.

Calculation/LP урсгалын томьёо `row → aggregate → solve → post` үе шаттай. Агрегат болон solution-ийг мөрийн output-д бичих бол `post` томьёогоор ил тод онооно. Indexed solution-ийн байрлалыг `diagnostics.indexed_layout`-аар тайлбарлана.

| Ангилал | Функцүүд |
|---|---|
| Тоон | `abs`, `min`, `max`, `pow`, `sqrt`, `log`, `exp`, `positive_part` |
| Vector / агрегат | `vector`, `SUM`, `AVG`, `COUNT`, `DOT`, `NORM` |
| Dataset багана | `COLUMN`, `COLUMN_SUM`, `AGG_SUM`, `AGG_MIN`, `AGG_MAX` |
| Тархалтын тооцоо | `POISSON_CAPPED_MEAN(mean, cap)`, `NB_CAPPED_MEAN(mean, dispersion, cap)` |
| Indexed compiler | `SUM_OVER(axis, expression)` — зөвхөн indexed загварт |

`COLUMN_SUM('QTY')` нь баганын нэрийг string-ээр авна. `SUM` нь vector авна. Capped-mean функцүүд `E[min(X, cap)]`-г бодно; `min(E[X], cap)`-аар орлуулахгүй. NB2 параметрчлал нь `Var(X) = mean + dispersion × mean²`.

AST нь дурын Python/SQL ажиллуулахгүй. Үл мэдэгдэх нэр, хамаарлын цикл, буруу хэмжээ, NaN/Infinity болон NULL тоон оролтыг татгалзана. Функц бүр бүх backend-д адилхан зөвшөөрөгдөхгүй; runtime metadata-г `GET /v1/capabilities`-аас харна.

## Үндсэн deployment: хадгалалтгүй Compute API

Анхдагч `docker compose up --build -d` нь зөвхөн Compute API асаана.
Оролт, үр дүн, job history-г SQLite-д хадгалахгүй; үр дүнг шууд буцаана.
Дуудагч систем хадгалалт, retry, түүхээ хариуцна.

Jobs/Data/Worker хэрэгтэй бол `docker compose --profile jobs up --build -d`
ашиглана. [Deployment ба шилжилтийн заавар](docs/STATELESS_DEPLOYMENT.md).

## Архитектур

| Бүрэлдэхүүн | Үүрэг | Локал порт |
|---|---|---|
| Model & Job API | Өөрчлөгдөшгүй model version, job, queue, lease, result | 8100 |
| Data Integration API | Snapshot, эх үүсвэрийн metadata, output artifact | 8101 |
| Math Execution API | Validation, capabilities, process-д тусгаарласан execution/prediction | 8102 |
| Worker | Job claim, snapshot татах, compute дуудах, persistence ба retry | — |

```text
Client ── model/job ──> Jobs API ──> Job SQLite
Client ── dataset ────> Data API ──> Snapshot SQLite
Worker ── claim ──────> Jobs API
Worker ── snapshot ──> Data API
Worker ── execute ───> Compute API ──> Isolated process ──> Math Core
Worker ── result ────> Jobs API
Worker ── artifact ──> Data API       (persist=true)
```

Сервисүүд HTTP-ээр харилцана. Jobs/Data тус бүр өөр SQLite store эзэмшинэ; бусдын баазыг шууд уншихгүй. Math Core нь DB, HTTP, environment-оос хамаарахгүй. Одоогийн контейнерүүд ижил image build definition ашиглаж, өөр entrypoint ажиллуулдаг.

## Хурдан эхлэх

Доорх командуудыг **энэ repository-ийн үндсэн хавтсаас** ажиллуулна. Python 3.10+ шаардлагатай; хамгийн сүүлд баталгаажуулсан орчин 3.10.

### 1. Суулгах ба CLI ажиллуулах

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[test]"
.\.venv\Scripts\python.exe -m math_engine examples/calculation.json
.\.venv\Scripts\python.exe -m math_engine examples/indexed_profit.json
```

CLI нь сервис болон Oracle шаардахгүй. Calculation жишээ `GRAND_TOTAL=435`, жижиг Profit жишээ `objective=22.3` буцаана.

### 2. Локал Compute API асаах

```powershell
$env:SERVICE_TOKEN = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))")
.\.venv\Scripts\python.exe -m uvicorn math_engine.services.compute:app --host 127.0.0.1 --port 8102
```

Бүтэн jobs стек хэрэгтэй бол SQLite ашигладаг `scripts/dev_stack.py`-г асаана. Зөвхөн тэр стек ажиллаж байгаа үед өөр terminal-д **ижил token** тохируулж:

```powershell
.\.venv\Scripts\python.exe scripts/demo_job.py calculation
.\.venv\Scripts\python.exe scripts/demo_job.py indexed_profit --persist
```

`dev_stack.py`-г Ctrl+C-ээр зогсооно. Локал өгөгдөл `var/` дотор хадгалагдана. Token-ийг Git, README эсвэл application log-д хадгалахгүй.

### 3. API-г шууд дуудах

Сервисүүд асаалттай, тухайн terminal-д ижил `SERVICE_TOKEN` тохирсон үед:

```powershell
$headers = @{ 'X-Service-Token' = $env:SERVICE_TOKEN }
$body = Get-Content examples/calculation.json -Raw
Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8102/v1/executions' `
  -Headers $headers -ContentType 'application/json' -Body $body
```

Үндсэн интеграц нь шууд execution дуудлага. Optional jobs profile нь model → snapshot → job → status/result гэсэн асинхрон урсгалтай. Шууд execution нь синхрон; client timeout-ийг compute-ийн 90 секундийн wall limit-тэй нийцүүлнэ.

## API лавлах

Application endpoint-ууд `X-Service-Token` шаарддаг. `/docs`, `/redoc`, `/openapi.json` гэсэн built-in documentation route-ууд одоогоор хамгаалалтгүй.

| Сервис | Endpoint | Үүрэг |
|---|---|---|
| Бүгд | `GET /health` | Сервисийн нэр, хувилбар, liveness |
| Jobs | `POST /v1/models` | Model version бүртгэх |
| Jobs | `POST /v1/jobs` | Job үүсгэх |
| Jobs | `GET /v1/jobs/{id}` | Төлөв, result, error |
| Jobs | `GET /v1/jobs/{id}/result` | Тооцсон үр дүн |
| Jobs | `GET /v1/jobs/{id}/fitted-artifact` | Сурсан статистик загвар |
| Jobs | `POST /v1/jobs/{id}/cancel` | Job цуцлах |
| Data | `POST /v1/snapshots` | JSON оролт хадгалах |
| Data | `GET /v1/snapshots/{id}` | Snapshot унших |
| Data | `GET /v1/snapshots/{id}/metadata` | Эх үүсвэрийн metadata |
| Data | `POST /v1/snapshots/oracle` | Зөвшөөрсөн Oracle profile-оос snapshot авах |
| Data | `POST /v1/writebacks`, `GET /v1/writebacks/{job_id}` | Output artifact хадгалах/унших |
| Compute | `POST /v1/models/validate` | Загварын бүтэц шалгах |
| Compute | `GET /v1/capabilities` | Backend болон функцийн боломж |
| Compute | `POST /v1/executions` | Загвар бодох |
| Compute | `POST /v1/predictions` | Fitted artifact-аар prediction хийх |

Model validation амжилттай болох нь өгөгдөлтэй загварт шийдэл байна гэсэн баталгаа биш. Linearity, өгөгдлийн хэмжээ болон feasibility-г execution үед нэмж шалгана. Jobs-ийн `/internal/*` route-ууд зөвхөн trusted worker-д зориулагдсан боловч одоогоор application API-тай ижил token ашигладаг.

## Job lifecycle ба хадгалалт

```text
persist=false: QUEUED → RUNNING → SUCCEEDED
persist=true:  QUEUED → RUNNING → COMPUTED → PERSISTING → SUCCEEDED
Алдаа/цуцлалт: FAILED / CANCELLED
```

- Model version-ийг өөр агуулгаар дарж бүртгэхгүй. Ижил `idempotency_key` + ижил хүсэлт ижил job буцаана; зөрүүтэй хүсэлтэд 409 өгнө.
- Lease, heartbeat, transaction нь job-ийн эзэмшлийг хамгаална. Хугацаа дууссан lease-ийг шинэ worker авч болно; хуучин эзэмшигчийн result-ийг татгалзана.
- Compute болон persistence тус бүр 3 оролдлоготой. Persistence retry нь compute-ийг дахин хийхгүй. Compute завгүй үеийн 429 нь compute retry budget-ийг зарцуулахгүй.
- Cancel нь result нийтлэхийг зогсооно; эхэлсэн native тооцоо шууд тасрахгүй байж болно. `PERSISTING` шатанд cancel зөвшөөрөхгүй.
- Job API бүтэн result-ийг хадгална. `persist=true` нь Data API-д мөрийн output artifact хадгалах нэмэлт шат; **Oracle source writeback биш**.
- Indexed solution болон aggregate нь job result-д байна; Data API-ийн мөрийн output-д автоматаар хувиргахгүй.

Exactly-once гүйцэтгэл амлахгүй; давталтыг idempotency болон lease fencing-ээр зохицуулна.

## Ажиллах жишээнүүд

Бүх тоон үр дүн зохиомол өгөгдөлд хамаарна. Компанийн бодит өгөөжийн баталгаа биш.

| Файл (`examples/`) | Шалгасан хэрэглээ |
|---|---|
| `integration.json` | Тоон интеграл, forward/reverse bounds: 8 / −8 |
| `calculation.json` | Мөр → агрегат → post тооцоолол |
| `allocation.json` | LP, шийдэл [4, 2], objective 59 |
| `poisson.json`, `negative_binomial.json` | Fitting, censoring, fitted artifact |
| `scenario_balance.json`, `scenario_capacity.json`, `scenario_sampling.json` | Quantile, finite candidate, sampling |
| `indexed_allocation.json`, `indexed_replenishment.json` | Integer allocation, MOQ, lead time |
| `indexed_information.json` | Шийдвэр гаргах мөчийн мэдээллийн нөхцөл |
| `indexed_transfer.json`, `indexed_assortment.json` | Шилжүүлэг, finite facing/assortment |
| `indexed_markdown.json` | Үнийн хуваарь [10, 10, 10], objective 64.3 |
| `finite_price_optimization.json` | Үнэ A=8, B=10, ашиг ≈38.773748 |
| `indexed_supplier.json` | Нийлүүлэгч, finite-scenario үйлчилгээний нөхцөл, өртөг 13 |
| `indexed_profit.json` | Хамтарсан захиалга/хуваарилалт/үнэ/SKU, ашиг 22.3 |

Assortment жишээ нь анх өгсөн томьёог хадгалсан: сонгоогүй SKU-д орлуулалтын эрэлт үлдэж болно. Хүлээн авагч SKU-ийн сонголтоор бүх эрэлтийг хаадаг өөр томьёотой адил гэж үзэхгүй. Profit жишээ нь нэг SKU/нэг салбарын хязгаарлагдсан хувилбар; бүх retail шийдвэрийн бүрэн нэгдсэн загвар биш.

Нэг SKU × салбарын 7/30/90 хоногийн demand pilot-ийг `scripts/demand_pilot.py`-аар ажиллуулна. Энэ хэрэглээний feature, backtest, horizon нийлбэрлэх логик цөмөөс тусдаа. [Дэлгэрэнгүй contract ба үнэлгээ](docs/STATISTICS_AND_DEMAND.md).

## Серверт байрлуулах

Одоогийн Compose-оор source-оос build хийх бүрдэл:

```text
Dockerfile
compose.yaml
.dockerignore
pyproject.toml
constraints.txt
src/math_engine/
.env                 # эсвэл deployment environment дахь SERVICE_TOKEN
```

Docker суусан сервер дээр хувийн `SERVICE_TOKEN`-оо environment эсвэл `.env`-д тохируулсны дараа:

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail=100
```

Dockerfile нь `src/`, `pyproject.toml`, `constraints.txt`-ийг image-д хуулж package суулгана. Контейнер non-root хэрэглэгчээр ажиллана. Compose нь:

- API портуудыг зөвхөн `127.0.0.1` дээр нийтэлнэ;
- зөвхөн jobs profile-д Jobs/Data-ийн named volume ашиглана;
- Compute-д 768 MB memory, 2 CPU, 128 PID хязгаар тавина;
- API healthcheck, optional worker dependency, 10 MB × 3 log rotation тохируулна.

**Docker CLI энэ шалгалтын орчинд байхгүй тул image build/run баталгаажаагүй.** Сервер дээрх smoke test, volume permission, restart/recovery, backup/restore заавал тусдаа шалгалт болно. `/health` нь DB writability эсвэл worker liveness шалгахгүй.

Гаднын хэрэглэгчид нээхийн өмнө HTTPS gateway, public/internal эрхийн тусгаарлалт, request size/rate хязгаар, monitoring болон нөөцлөлтийг хэрэгжүүлнэ. Одоогийн нэг shared token-ийг олон хэрэглэгчийн эрхийн систем гэж үзэхгүй.

[Файл бүрийн үүрэг ба deployment бүрдэл](docs/SERVER_FILES_AND_READINESS.md) · [Бэлэн байдлын нотолгоо, үлдсэн ажил](docs/SERVER_READINESS_2026-11-02.md)

### Optional Oracle уншилт

Анхдагчаар идэвхгүй. JSON snapshot ашиглахад Oracle хэрэггүй. Уншилт идэвхжүүлэхэд `.[oracle]` extra, зөвшөөрсөн profile файл, Data сервисийн `ORACLE_READ_PROFILES_FILE`, `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN` шаардлагатай.

[Profile загвар](config/oracle-read-profiles.example.json) нь хүснэгт/баганыг урьдчилан зөвшөөрөх зориулалттай. Request нь profile нэр болон хоосон бус `scenario_code` өгнө; дурын SQL дамжуулахгүй. Reader SELECT-only, бодит Oracle холболт батлагдаагүй. Анхдагч Docker image optional driver агуулаагүй, Compose Oracle environment/mount тохируулаагүй.

## Хязгаар ба хөгжүүлэлтийн хүрээ

| Хэсэг | Одоогийн зааг |
|---|---|
| Indexed model | 4 axis, 1000 expanded variable, dense matrix хамгаалалтын хязгаартай |
| Dataset | 10,000 мөр; contract бүр нэмэлт хэмжээний хязгаартай |
| Scenario optimization | 10,000 хүртэл joint candidate; өгсөн finite measure доторх optimum |
| Тоон интеграл | Нэг хувьсагч, төгсгөлөг bounds; error estimate нь баталгаат дээд хязгаар биш |
| Price optimization | Finite price candidate; continuous nonlinear global solver байхгүй |
| Statistical fitting | Локал likelihood optimization; convergence нь forecast quality/global optimum батлахгүй |
| Prediction | Mean/variance; confidence interval, автомат feature/model selection байхгүй |
| Compute API | API process тутамд нэг slot, 90 секундийн wall timeout |
| Хадгалалт/scale | SQLite, нэг host pilot; multi-host HA, sparse matrix/decomposition батлагдаагүй |
| Бизнесийн хэрэглээ | Бодит өгөгдлийн аудит, causal validation, үйл ажиллагааны зөвшөөрөл тусдаа |
| Legacy integration | Хуучин KPI/DSL map-ийг шинэ contract-д хөрвүүлэх бүрэн adapter байхгүй |

Хөдөлгүүр ажилладаг нь тухайн бизнесийн загвар зөв, нөөцийн өгөгдөл найдвартай, эсвэл ашгийн өсөлт батлагдсан гэсэн үг биш. Model acceptance, хугацаагаар салгасан backtest, бодит өгөгдлийн чанарын шалгалтыг хэрэглээний түвшинд хийнэ.

## Хөгжүүлэлт ба шалгалт

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Тестүүд AST/contract, LP/MILP, statistical fitting, scenario, бие даасан enumeration, SQLite recovery, process timeout болон бодит localhost HTTP урсгалыг шалгана. Тестийн баазууд түр замд үүсэж, production Oracle ашиглахгүй. CI тохиргоо Python 3.10/3.12 дээр тест ажиллуулахаар бичигдсэн; CI run болон Docker build амжилтыг энэ README батлахгүй.

```text
src/math_engine/         Математик цөм, contract, storage, worker
src/math_engine/services/  Jobs / Data / Compute HTTP сервисүүд
src/math_engine/applications/  Demand pilot хэрэглээний логик
examples/                Дахин ажиллуулах JSON загварууд
scripts/                 Локал стек, demo client, туршилтын хэрэгслүүд
tests/                   Unit, mathematical, HTTP integration тестүүд
docs/                    Contract, жишээ, deployment тайлан
config/                  Optional Oracle profile загвар
```

Өөрчлөлтийн дүрмийг [AGENTS.md](AGENTS.md)-ээс үзнэ. Цөмд бизнесийн нэршил hard-code хийхгүй, сервисүүд бусдын store-ийг уншихгүй, credential/өгөгдлийн сан/virtual environment-ийг Git-д оруулахгүй.
