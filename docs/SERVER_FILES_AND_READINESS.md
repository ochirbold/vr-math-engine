# Серверт байрлах файлууд, үүрэг ба бэлэн байдлын тайлан

Огноо: 2026-11-02. Хувилбар: 0.6.0.
Эх үүсвэр: `math-engine-platform` бие даасан repository.

## Дүгнэлт

API ба job боловсруулах ажиллагаа локал HTTP орчинд баталгаажсан: хамгийн
v0.6.0 шалгалтаар 201 тест 97.46 секундэд давсан. Өмнөх v0.5.0 readiness шалгалтын `pip check` зөрчилгүй.
Дотоод серверийн pilot-д шилжүүлэх суурь бэлэн. Docker image build/run,
зорилтот серверийн restart, backup/restore, ачааллын шалгалт хийгдээгүй.
Интернэтэд шууд нийтлэх production бэлэн байдал батлагдаагүй.
Энэ тайланд файлуудын бүрдлийг шалгасан; тестийг дахин ажиллуулаагүй,
серверт байршуулалт хийгээгүй.

## 1. Сервер дээр source-оос build хийхэд өгөх яг бүрдэл

```text
math-engine-platform/
  Dockerfile
  compose.yaml
  .dockerignore
  pyproject.toml
  constraints.txt
  src/
    math_engine/
      ... доорх хүснэгтийн бүх Python файл ...
  .env                       # сервер дээр шинээр үүсгэх нууц тохиргоо
```

Энэ нь одоогийн Compose-ийн `build: .` урсгалын бүрдэл. `.env` файлын оронд
SERVICE_TOKEN-ийг deployment environment-оос өгч болно. `.env.example` нь
зөвхөн загвар; серверийн бодит secret биш. Хуучин CVP төслийн `main.py`,
`formula/`, Oracle writeback код хэрэггүй.

| Файл | Үүрэг | Бэлэн байдал |
|---|---|---|
| `Dockerfile` | Python 3.10 image, dependency/package суулгалт, non-root engine хэрэглэгч | Бичигдсэн; Docker build/run баталгаажаагүй |
| `compose.yaml` | jobs/data/compute/worker, network, volume, healthcheck, restart, compute resource limits | Бичигдсэн; target host дээр шалгах |
| `.dockerignore` | .git, .venv, var, .env, тест болон cache-ийг build context-оос хасна | Байгаа; deployment багцад оруулна |
| `pyproject.toml` | Package metadata, runtime dependencies, setuptools build | Локал package ажилласан |
| `constraints.txt` | Суулгах dependency хувилбаруудыг тогтооно | Локал шалгасан; base image болон build-tool бүрэн lock биш |
| `.env` эсвэл environment | SERVICE_TOKEN нууц утгыг Compose-д өгнө | Сервер дээр хувийн утгаар шинээр тохируулна |

CI дээр урьдчилан image build/push хийж түгээх хувилбар сонговол runtime
серверт source, Dockerfile шаардахгүй байж болно. Гэхдээ одоогийн Compose нь
registry image биш `build: .` ашигладаг; ийм урсгалд Compose-ийг өөрчилнө.

## 2. Docker image дотор яг юу ордог вэ?

Одоогийн Dockerfile-ийн COPY үйлдэл:

| Host source | Image дотор |
|---|---|
| `pyproject.toml` | `/app/pyproject.toml` |
| `constraints.txt` | `/app/constraints.txt` |
| `src/` бүхэлдээ | `/app/src/` |

Дараа нь `pip install -c constraints.txt .` package болон dependency-уудыг
Python site-packages-д суулгана. Image-д source болон суусан package хоёулаа
байна. Compose-ийн дөрвөн сервис ижил source/build definition ашигладаг;
тус бүр зөвхөн өөр entrypoint ажиллуулна. Код нь дөрвөн жижиг image болгон
салсан биш, харин процесс ба өгөгдлийн эзэмшил нь тусгаарлагдсан.

`compose.yaml`, `.env`, `docs/`, `examples/`, `config/`, `scripts/`-ийг Dockerfile
image рүү COPY хийдэггүй. Build context-д байх нь image-д суусан гэсэн үг биш.

## 3. API, worker, өгөгдлийн файлууд

Доорх замууд бүгд `src/math_engine/`-ээс эхэлнэ.

| Файл | Үүрэг |
|---|---|
| `services/common.py` | Token шалгалт, FastAPI үүсгэлт, алдааны HTTP хөрвүүлэлт, /health |
| `services/jobs.py` | Model version бүртгэл, job submit/status/result/cancel; worker-ийн internal API |
| `services/data.py` | Snapshot үүсгэх/унших, гаралтын artifact хадгалах, optional Oracle snapshot |
| `services/compute.py` | Validate, capabilities, execution, prediction; нэг compute slot ба 429 |
| `services/__init__.py` | Services package-ийн бүтэц |
| `worker.py` | Job claim, heartbeat, snapshot татах, compute дуудах, persistence/retry |
| `http_client.py` | Сервис хооронд JSON HTTP дуудлага, token, timeout, RemoteError |
| `storage.py` | SQLite store, model/snapshot/job/result, WAL transaction, lease, idempotency |
| `isolated.py` | Тусдаа process-д тооцох, 90 секундийн wall timeout, process зогсоох |
| `oracle_reader.py` | Сонголтот, зөвшөөрсөн profile/scenario-оор SELECT-only Oracle уншилт |

Эдгээрийн HTTP/job/store ажиллагаа локал тесттэй. Энэ нь бүх failure mode,
аюулгүй байдлын аудит, production ачаалал батлагдсан гэсэн утга биш.
Oracle reader-ийн бодит серверийн холболт батлагдаагүй.

## 4. Математик цөмийн файлууд

| `src/math_engine/` доторх файл | Үүрэг |
|---|---|
| `contracts.py` | Оролт/гаралт, model, solver, job, dataset-ийн typed contract |
| `engine.py` | Загварын төрлөөр backend сонгох, нийтлэг execution |
| `compiler.py` | Загварын validation, хамаарал болон тооцооллын шатлал |
| `expressions.py` | Аюулгүй AST interpreter, зөвшөөрсөн функцүүд |
| `expression_types.py` | Scalar/vector хэлбэр, функцийн боломжийн metadata |
| `linear.py` | LP/MILP matrix, affine дүрэм, bounded positive-part, HiGHS solver |
| `indexed.py` | Индекс, SUM_OVER, boundary, scenario information-ийг finite model болгон задлах |
| `integration.py` | Нэг хувьсагчийн finite тоон интеграл, convergence ба error estimate |
| `statistics.py` | Poisson/NB fitting, censoring likelihood, artifact, prediction |
| `uncertainty.py` | Weighted finite measure, sampling, capped-count expectation |
| `scenarios.py` | Scenario томьёо, reduction, finite candidate optimization |
| `__init__.py` | Package хувилбар |
| `__main__.py` | CLI entrypoint; HTTP-д зайлшгүй биш ч одоогийн image-д орно |

0.5.0 суурь нь 179 тестийн цуглуулгаар шалгагдсан; 0.6.0 интегралын шинэ шалгалтын дүнг README-ээс үзнэ. Математик хязгаарууд
хэвээр: indexed model 4 axis, 1000 expanded variable; үнэний finite candidate
хувилбар нь continuous nonlinear global optimization биш.

## 5. Image-д ордог боловч API-ийн суурь ажиллагаанд зайлшгүй биш файлууд

| Файл | Үүрэг |
|---|---|
| `applications/__init__.py` | Application package |
| `applications/demand.py` | Demand pilot-ийн application түвшний ажиллагаа |
| `applications/synthetic_demand.py` | Demand туршилтын зохиомол өгөгдөл |

Одоогийн Dockerfile `src/`-ийг бүхэлд нь хуулдаг тул эдгээр орно. Жижиг image
болгох зорилгоор энэ шалгалтаар файл устгаж, package бүтэц өөрчлөөгүй.

## 6. Сервер ажиллах үед үүсэх өгөгдөл

| Өгөгдөл | Байрлал / эзэмшигч | Хадгалах шаардлага |
|---|---|---|
| Job DB | jobs контейнерийн `/data/jobs.db`, `job-data` named volume | Model version, job, үр дүн, queue төлөв |
| Snapshot DB | data контейнерийн `/data/data.db`, `snapshot-data` named volume | Оролтын snapshot, metadata, output artifact |
| SQLite WAL/SHM | DB-ийн хажууд ажиллах үед үүсэж болно | Идэвхтэй DB backup хийхэд consistency-г тооцно |
| Log | Container stdout/stderr | Docker/host log rotation, retention хэрэгтэй |

Хоёр контейнерт `/data/` нэр ижил боловч хоёр тусдаа volume. Compute нь
эдгээр SQLite файлыг шууд уншихгүй. Worker HTTP-ээр холбогдоно.
Named volume-ийн host дээрх бодит замыг Docker удирдана; `/app/var` гэж
үзэж болохгүй. Volume устгавал өгөгдөл алдагдана. Зүгээр image rebuild хийх
нь backup/restore шалгалтыг орлохгүй. Хөгжүүлэлтийн `var/`-ыг сервер рүү
хуулж production өгөгдөл болгохгүй.

## 7. Optional Oracle холболтын нэмэлт бүрдэл

`config/oracle-read-profiles.example.json` нь зөвхөн жишээ. Oracle ашиглах бол:

1. `oracledb` dependency суулгасан image бэлдэнэ. Одоогийн `pip install .`
   нь optional `oracle` extra-г суулгахгүй.
2. Бодит зөвшөөрөгдсөн profile файлыг data service-д read-only mount хийнэ.
3. Data service-д ORACLE_READ_PROFILES_FILE, ORACLE_USER, ORACLE_PASSWORD,
   ORACLE_DSN тохируулна. Одоогийн Compose эдгээрийг дамжуулаагүй.
4. Зөвшөөрөгдсөн scenario дээр холболт/уншилтыг тусад нь баталгаажуулна.

Ийм тохиргоогүй үед Oracle уншилт disabled. Харин JSON snapshot-аар API
ажиллуулахад Oracle шаардлагагүй. Oracle writeback энэ бүрдэлд байхгүй.

## 8. Runtime серверт заавал хүргэхгүй файлууд

| Файл/хавтас | Хэрэглээ |
|---|---|
| `tests/` | CI болон release шалгалт; image-д COPY хийгдэхгүй |
| `examples/` | Smoke test/API request-ийн жишээ; шалгагч машинаас илгээж болно |
| `scripts/dev_stack.py` | Локал хөгжүүлэлтийн асаалт; Compose deployment-д хэрэггүй |
| `scripts/demo_job.py` | API smoke test client; шалгагч машинд хэрэгтэй |
| `docs/`, `README.md`, `POSTMAN_GUIDE.md` | Оператор/хөгжүүлэгчийн баримт |
| `.github/workflows/test.yml` | CI тестийн тохиргоо |
| `.env.example` | Secret тохиргооны загвар; бодит token биш |
| `.venv/`, `var/`, `.git/`, `__pycache__/` | Runtime deployment багцад хуулж өгөхгүй |

## 9. Сервисүүд хэрхэн асах вэ?

| Сервис | Entry point | Host холболт |
|---|---|---|
| jobs | uvicorn math_engine.services.jobs:app | 127.0.0.1:8100 → container:8000 |
| data | uvicorn math_engine.services.data:app | 127.0.0.1:8101 → container:8000 |
| compute | uvicorn math_engine.services.compute:app | 127.0.0.1:8102 → container:8000 |
| worker | python -m math_engine.worker | Host port байхгүй; internal HTTP |

Бүх application API дуудлага X-Service-Token шаардана. Built-in /docs,
/redoc, /openapi.json нь одоогоор token dependency-гүй. Нэг токен бүх
сервис болон /internal/* эрхийг нээдэг тул гаднын хэрэглэгчид түгээхгүй.

## 10. Бэлэн байдлын үнэлгээ

| Шалгуур | Төлөв | Үлдсэн ажил |
|---|---|---|
| Package, dependency | Локал батлагдсан | Image дотор install батлах |
| API / worker / result | Локал HTTP тест давсан | Target host end-to-end шалгах |
| DB retry/recovery | Storage тест давсан | Container/host restart, бодит restore |
| Docker build/Compose | Тохиргоо байгаа | Docker орчинд build, up, health шалгах |
| Remote access | Localhost-only | HTTPS gateway эсвэл private tunnel |
| Хэрэглэгч/worker эрх | Нэг shared token | Internal/public route эрх тусгаарлах |
| Monitoring, backup | Бүрэн ажиллагааны шийдэлгүй | Alert, worker health, retention, restore |
| Production capacity | Хэмжээгүй | Бодит хэмжээтэй load/soak test |

Дотоод pilot: target host шалгалтын дараа ашиглаж болно.
Нээлттэй production: дээрх ажиллагаа, хамгаалалтын ажлууд дууссаны дараа
дахин бэлэн байдлыг үнэлнэ. Серверийн хаяг, OS, domain, ачааллын зорилт
өгөөгүй тул тодорхой серверт тохирсон баталгаа өгөөгүй.

Дэлгэрэнгүй эрсдэл ба шалгалтын нотолгоо:
[SERVER_READINESS_2026-11-02.md](SERVER_READINESS_2026-11-02.md).
