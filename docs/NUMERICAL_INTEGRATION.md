# Тоон интеграл — v0.6.0

`kind: numerical_integration` нь нэг хувьсагчийн, төгсгөлөг хязгаартай
тодорхой интегралыг SciPy quad / QUADPACK-аар тооцно. Бизнесийн домэйнээс
хамаарахгүй; CLI, Compute API, Model/Job/Worker урсгалд ижил contract ашиглана.

## Оролтын жишээ

```json
{
  "model": {
    "model_id": "polynomial-integral",
    "version": "1",
    "kind": "numerical_integration",
    "inputs": ["start", "end"],
    "parameters": ["scale"],
    "variable": "x",
    "expression": "scale*x**2",
    "lower": "start",
    "upper": "end",
    "absolute_tolerance": 1e-8,
    "relative_tolerance": 1e-8,
    "subdivision_limit": 100,
    "evaluation_limit": 100000
  },
  "parameters": {"scale": 3},
  "dataset": {
    "row_ids": ["example"],
    "rows": [{"start": 0, "end": 2}]
  }
}
```

Гаралт: `outputs[0].integral = 8`, `absolute_error_estimate` ойролцоогоор
8.88e-14. `diagnostics.rows` нь мөр бүрийн convergence, evaluation count,
subinterval count, message өгнө. Dataset-ийн мөр бүр тусдаа интеграл.

## Дүрэм

- Expression, lower, upper нь одоогийн safe AST ашиглана; дурын Python код биш.
- Expression нь scalar бөгөөд variable, inputs, parameters-ийг ашиглана.
- Lower/upper нь scalar, төгсгөлөг бөгөөд интегралчлах variable-аас хамаарахгүй.
- Баганын агрегат, vector, nested integration дэмжихгүй.
- Хязгаар эсрэг дараалалтай бол тэмдэг урвана. Ижил хязгаартай бол функц
  үнэлэхгүйгээр 0, error estimate 0 буцаана.
- Tolerance тус бүр 1e-12..1. Алдааны зорилт нь
  max(absolute_tolerance, relative_tolerance * abs(integral)).
- Subdivision limit: мөр тус бүрт 1..1000. Evaluation limit: хүсэлтийн бүх
  мөрийг нийлүүлсэн 1..1,000,000 функцийн үнэлгээ; default 100,000.
- QUADPACK nonconvergence эсвэл evaluation limit үед `status=failed`, output
  нийтлэхгүй. Өмнөх амжилттай мөрүүдийг ч partial success гэж хадгалахгүй.
- Синтакс/домэйн алдаа ModelError; API execution-д 422. Тооцооны convergence
  failure нь ExecutionResult-ийн failed төлөвтэй буцна; HTTP 200 өөрөө
  математик амжилтыг илэрхийлэхгүй. Job нь failed болно.
- API-ийн process isolation болон 90 секундийн wall timeout үйлчилнэ.
  CLI дээр энэ wall timeout үйлчлэхгүй; evaluation limit хэвээр.

## Нарийвчлалын тайлбар

Алдааны тоо нь numerical estimate болохоос баталгаат математик дээд хязгаар
биш. Adaptive quadrature нь маш нарийн оргил, хурдан хэлбэлзэл, мэдэгдээгүй
тасралтыг алдах боломжтой. Convergence нь тухайн алгоритмын шалгуур биелсэн
гэсэн үг; analytic proof биш. Танил аналитик хариу, нарийвчлалын өөр тохиргоо,
завсрыг хэсэгчлэн салгасан тооцоотой харьцуулж хэрэглэнэ.

Энэ хувилбар symbolic indefinite integral, хязгааргүй интервал, олон
хувьсагчийн интеграл, ODE, derivative/gradient, ерөнхий nonlinear optimizer
нэмээгүй. Шийдвэрээс хамаарах интегралыг LP/MILP-д шууд оруулахгүй.

## Ажиллуулах

```powershell
.\.venv\Scripts\python.exe -m math_engine examples/integration.json
.\.venv\Scripts\python.exe scripts/demo_job.py integration --persist
.\.venv\Scripts\python.exe -m pytest -q tests/test_integration.py
```

Demo job-д сервисүүд асаалттай, ижил SERVICE_TOKEN тохирсон байх ёстой.
`persist=true` үед integral/error estimate мөрийн artifact хадгалагдана;
Oracle руу бичихгүй. CLI/шууд compute result өөрөө DB хадгалалт хийхгүй.

Шалгалт: polynomial, exponential, log, absolute value, integrable endpoint
singularity, эсрэг/тэнцүү bounds, параметртэй олон мөр, зөвшөөрөөгүй AST,
variable-dependent bounds, nonconvergence, request-wide budget, API job ба
output persistence. Нэмэлт runtime dependency шаардахгүй.

2026-11-02 бүрэн regression: **201 passed in 97.46s**. Шинэ 21 тоон/validation
тест болон 1 HTTP job/persistence тест багтсан.
