# Математик цөмийн гарын авлага

**Math Engine Platform · v0.6.0 · 2026-11-02**

Энэ гарын авлага математик загвар бэлтгэх, ажиллуулах, үр дүнг тайлбарлахад
зориулагдсан. Сервер, өгөгдлийн сан болон API-ийн тохиргоо шаардахгүйгээр
цөмийг шууд ашиглах аргаас эхэлнэ.

> **Үндсэн зарчим:** та өгөгдөл, томьёо, шийдвэрийн хувьсагч, зорилго,
> хязгаарлалтаа тодорхойлно. Хөдөлгүүр дэмждэг математик аргаар түүнийг тооцно.
> Бизнесийн нөхцөл, томьёог автоматаар таахгүй.

## Агуулга

1. [Загварын төрлөө сонгох](#1-загварын-төрлөө-сонгох)
2. [Оролтын бүтэц](#2-оролтын-бүтэц)
3. [Анхны тооцоолол](#3-анхны-тооцоолол)
4. [Зорилго ба хязгаарлалттай бодлого](#4-зорилго-ба-хязгаарлалттай-бодлого)
5. [Тоон интеграл](#5-тоон-интеграл)
6. [Бусад загварын хэрэглээ](#6-бусад-загварын-хэрэглээ)
7. [Бэлэн функцүүд](#7-бэлэн-функцүүд)
8. [Гүйцэтгэл ба гаралт](#8-гүйцэтгэл-ба-гаралт)
9. [Алдаа ба чадамжийн зааг](#9-алдаа-ба-чадамжийн-зааг)
10. [Загвар бэлтгэх шалгах хуудас](#10-загвар-бэлтгэх-шалгах-хуудас)

## 1. Загварын төрлөө сонгох

| Хийх ажил | `kind` | Таны тодорхойлох гол зүйл |
|---|---|---|
| Өгөгдсөн тоонуудаар томьёо бодох | `calculation` | Оролт, томьёо, тооцооллын үе шат |
| Тасралтгүй хэмжээнүүдийн хамгийн сайн хувилбар олох | `linear_program` | Шугаман зорилго, шийдвэр, хязгаарлалт |
| Бүхэл тоо болон тийм/үгүй шийдвэр гаргах | `mixed_integer_program` | Integer/binary хувьсагч, шугаман нөхцөл |
| Хугацаа, бүлэг, scenario зэрэг индексээр загвар байгуулах | `indexed_program` | Axes, tables, indexed decisions, boundary |
| Тооллогын өгөгдлөөс параметр сургах | `statistical_fit` | Predictor, trainable parameters, distribution, observation |
| Боломжит хувилбаруудын эрсдэл, дундаж, сонголтыг тооцох | `scenario_program` | Scenario, жин, томьёо, сонголтын багц |
| Тодорхой завсар дахь интеграл бодох | `numerical_integration` | Функц, хувьсагч, хязгаар, нарийвчлал |

Шугаман бодлогод шийдвэрийн хувьсагчийг тогтмол тоогоор үржүүлж, хооронд нь
нэмж болно. Хоёр үл мэдэгдэхийг үржүүлэх, эсвэл үл мэдэгдэхийн `log`, `exp`-ийг
авах нь ерөнхийдөө шугаман биш. Тоон функц байдаг нь түүнийг бүх solver-ийн
шийдвэрийн хувьсагч дээр хэрэглэж болно гэсэн үг биш.

## 2. Оролтын бүтэц

Цөм `ExecutionRequest` хүлээн авна. JSON файл ба Python объект ижил бүтэцтэй.

| Хэсэг | Агуулга |
|---|---|
| `model` | Загварын тодорхойлолт: ID, version, kind болон тухайн төрлийн талбарууд |
| `dataset.row_ids` | Мөр бүрийн давтагдашгүй string ID |
| `dataset.rows` | Тоон оролтын мөрүүд; ID-тайгаа ижил дараалал, ижил тоотой |
| `parameters` | Бүх мөрд нийтлэг тогтмол параметрийн утга |
| `solver` | Оновчлолын backend-д хамаарах хугацаа, tolerance зэрэг сонголт |

`model.inputs` нь мөрийн баганын **нэр**, `model.parameters` нь параметрийн
**нэр**. Харин dataset болон request.parameters нь тэдгээрийн **утга** юм.

| Ойлголт | Жишээ | Хэн утгыг тогтоох вэ? |
|---|---|---|
| Input | Нэг ажлын цагийн хэрэгцээ | Хэрэглэгчийн өгөгдөл |
| Parameter | Нийт боломжит цаг | Хэрэглэгч |
| Decision | Аль ажилд хэдэн цаг өгөх | Optimizer |
| Trainable parameter | Статистик загварын коэффициент | Fitting backend |
| Formula target | Тооцсон нийт зардал | Томьёоны гүйцэтгэл |

Нэрүүдийг `QTY`, `capacity`, `allocation` гэх мэт латин үсгээр эхэлсэн
үсэг/тоо/доогуур зураастай өгнө. Функцийн нэрийг хувьсагчийн нэр болгож
давхардуулахгүй. Тоон NULL, NaN, Infinity зөвшөөрөхгүй. Оролтгүй загвар ч
`{"row_ids":["one"],"rows":[{}]}` гэсэн нэг хоосон мөртэй dataset авч болно.

Statistical fitting-д response/censor баганууд observation хэсгээр заагддаг;
тэдгээрийг predictor-ийн inputs-тай андуурахгүй.

## 3. Анхны тооцоолол

Хоёр төрлийн ажлын тоо ба нэгж өртөг өгөгдсөн гэж үзье.

| row_id | QTY | RATE | Тооцох TOTAL |
|---|---:|---:|---:|
| A | 2 | 10 | 20 |
| B | 3 | 8 | 24 |
| **Нийлбэр** | | | **44** |

Доорх хүсэлтийг `model.json` нэртэй UTF-8 файлд хадгална.

```json
{
  "model": {
    "model_id": "simple-total",
    "version": "1",
    "kind": "calculation",
    "inputs": ["QTY", "RATE"],
    "formulas": [
      {"target": "TOTAL", "expression": "QTY * RATE", "stage": "row"},
      {"target": "TOTAL_ALL", "expression": "COLUMN_SUM('TOTAL')", "stage": "aggregate"}
    ]
  },
  "dataset": {
    "row_ids": ["A", "B"],
    "rows": [{"QTY": 2, "RATE": 10}, {"QTY": 3, "RATE": 8}]
  }
}
```

Repository-ийн үндсэн хавтсаас:

```powershell
.\.venv\Scripts\python.exe -m math_engine model.json
```

Хүлээгдэх утгууд:

```text
status                  succeeded
outputs[0].TOTAL        20
outputs[1].TOTAL        24
aggregates.TOTAL_ALL    44
```

### Тооцооллын үе шат

Calculation/LP загварын томьёог дараах байдлаар байрлуулна.

| `stage` | Хэзээ | Жишээ |
|---|---|---|
| `row` | Мөр бүр дээр | `QTY * RATE` |
| `aggregate` | Тооцсон бүх мөрөөс | `COLUMN_SUM('TOTAL')` |
| `post` | Агрегат/шийдэл гарсны дараа мөр бүр дээр | `TOTAL / TOTAL_ALL` |

Хамааралтай томьёоны зөв дарааллыг compiler тогтооно. Харин A нь B-ээс,
B нь A-аас хамаарвал цикл гэж татгалзана. `row` шатанд хараахан гараагүй
aggregate эсвэл solver-ийн шийдлийг ашиглахгүй.

## 4. Зорилго ба хязгаарлалттай бодлого

Нийт 6 нэгж нөөцийг A ба B ажилд хуваарилъя.

| Ажил | Нэгжийн өгөөж BENEFIT | Дээд хэмжээ LIMIT |
|---|---:|---:|
| A | 10 | 4 |
| B | 6 | 5 |

Хамгийн их болгох зүйл: `10 × allocation_A + 6 × allocation_B`.
Хоёр хуваарилалтын нийлбэр 6-аас ихгүй, тус бүр өөрийн LIMIT-ээс ихгүй.

```json
{
  "model": {
    "model_id": "simple-allocation",
    "version": "1",
    "kind": "linear_program",
    "inputs": ["BENEFIT", "LIMIT"],
    "parameters": ["capacity"],
    "decisions": {"allocation": {"size": "rows", "lower": 0}},
    "objective": {
      "sense": "maximize",
      "expression": "DOT(COLUMN('BENEFIT'), allocation)"
    },
    "constraints": [
      "allocation <= COLUMN('LIMIT')",
      "SUM(allocation) <= capacity"
    ],
    "formulas": [
      {"target": "ALLOCATED", "expression": "allocation", "stage": "post"}
    ]
  },
  "dataset": {
    "row_ids": ["A", "B"],
    "rows": [{"BENEFIT": 10, "LIMIT": 4}, {"BENEFIT": 6, "LIMIT": 5}]
  },
  "parameters": {"capacity": 6}
}
```

**Шийдэл:** A=4, B=2; objective=52. `solution.allocation` нь `[4,2]`,
`outputs` нь мөр тус бүрийн `ALLOCATED` утгыг агуулна.

`size: "rows"` нь мөр бүрт нэг шийдвэр үүсгэнэ. Decision дээр `size` орхивол
scalar; тоон size өгвөл тогтмол урттай vector болно.

Бүхэл тоон шийдвэр хэрэгтэй бол `kind: "mixed_integer_program"`, тухайн
decision-д `domain: "integer"` өгнө. Тийм/үгүй сонголтод `domain: "binary"`
ашиглана. Зөвхөн continuous LP бодоод дараа нь round хийх нь integer
оновчлолыг орлохгүй.

## 5. Тоон интеграл

`∫₀² 3x² dx`-г бодъё. Аналитик хариу нь **8**.

```json
{
  "model": {
    "model_id": "simple-integral",
    "version": "1",
    "kind": "numerical_integration",
    "variable": "x",
    "expression": "3*x**2",
    "lower": "0",
    "upper": "2",
    "absolute_tolerance": 1e-8,
    "relative_tolerance": 1e-8
  },
  "dataset": {"row_ids": ["one"], "rows": [{}]}
}
```

`outputs[0].integral = 8`; `absolute_error_estimate` нь ойролцоогоор
8.88e-14. Нарийн утга орчноос хамааран бага зэрэг өөр байж болно.

- Lower/upper нь тоо бичсэн expression эсвэл мөр/параметрийн илэрхийлэл.
- Хязгаар эсрэг дараалалтай бол тэмдэг урвана; тэнцүү бол 0.
- Мөр бүрт нэг интеграл бодно; нийт үнэлгээний лимит хүсэлт даяар үйлчилнэ.
- Алдаа нь **тоон үнэлгээ**, баталгаат дээд хязгаар биш.
- Convergence хангаагүй бол `failed`; partial output нийтлэхгүй.

Энэ нь symbolic ерөнхий интеграл биш. Хязгааргүй завсар, олон хувьсагчийн
интеграл, derivative болон ODE энэ хувилбарт байхгүй.
[Интегралын нарийвчилсан contract](NUMERICAL_INTEGRATION.md).

## 6. Бусад загварын хэрэглээ

### 6.1. Индексжүүлсэн загвар

Олон хугацаа, бүлэг, scenario-д ижил нөхцөл тавихад `indexed_program` сонгоно.

| Талбар | Үүрэг |
|---|---|
| `axes` | `t: [0,1,2]` зэрэг индексийн олонлог |
| `tables` | Dataset-ийн багануудыг тогтмол indexed өгөгдөлтэй холбох |
| `decisions` | `quantity[t]`, `stock[t,w]` зэрэг шийдвэр |
| `boundary` | `t=-1` зэрэг үндсэн axis-оос өмнөх мэдэгдэж буй утга |
| `SUM_OVER` | Нэг axis-ийн дагуух нийлбэр |
| `information` | Scenario-уудын аль шийдвэр ижил байх ёстойг тодорхойлох |

Жишээ илэрхийлэл: `stock[t,w] == stock[t-1,w] + quantity[t] - demand[t,w]`.
Энэ мөрийг дангаар ажиллуулахгүй: axis, table, decision, boundary-г хамт
зарлана. Scenario-specific гэдэг нь автоматаар зөв мэдээллийн бодлого биш;
ирээдүйг мэдсэн мэт шийдвэр гаргуулахгүй байх бүлгийг хэрэглэгч өгнө.

Бүрэн загвар: [indexed_information.json](../examples/indexed_information.json).
[Indexed contract](INDEXED_MILP.md).

### 6.2. Scenario тооцоолол

Scenario бол боломжит нэг нөхцөл, жин нь түүний харьцангуй магадлал.

| Scenario | Ачаалал | Жин |
|---|---:|---:|
| Бага | 3 | 0.25 |
| Дунд | 7 | 0.50 |
| Их | 11 | 0.25 |

`scenario_program` нь нөхцөл тус бүрийн томьёог бодоод expectation, variance,
quantile гаргана. `values: [1,2,3]` гэсэн decision өгвөл сонголт бүрийг
харьцуулж, өгсөн scenario measure дээр хамгийн сайн хувилбарыг олно.

[scenario_capacity.json](../examples/scenario_capacity.json)-д 1/2/3 төхөөрөмжөөс
**2**-ыг сонгоно. Нэг төхөөрөмжийн хүчин чадал 5; тогтмол зардал 4;
илүүдэл ачааллын квадрат торгуультай. Сонгосон хувилбарын expected cost=8.25.

Энд constraint нь эерэг жинтэй scenario бүрт биелнэ; expectation constraint
эсвэл chance constraint гэж автоматаар тайлбарлахгүй. Candidate grid-ээс
гадуурх хамгийн сайн шийдлийг батлахгүй. [Дэлгэрэнгүй](SCENARIO_MODELS.md).

### 6.3. Статистик fitting ба prediction

`statistical_fit` нь өгөгдлөөс `trainable` параметрийг сургана. Одоогоор
Poisson болон Negative Binomial, exact/right-censored ажиглалт дэмжинэ.

[poisson.json](../examples/poisson.json)-д `[1,2,3,4,5,3]` тооллогоор тогтмол
mean сургахад mean≈3, log-link-ийн intercept≈log(3) гарна.

Амжилттай fitting нь `fitted_artifact` үүсгэнэ. Дараа нь artifact + feature
өгөгдлөөр prediction хийхэд дахин fitting хийхгүй. Prediction mean/variance
буцаана. Convergence нь прогнозын нарийвчлал эсвэл causal нөлөөг батлахгүй.
[Статистикийн дэлгэрэнгүй](STATISTICS_AND_DEMAND.md).

## 7. Бэлэн функцүүд

Эдгээр нь expression доторх функцүүд. Жишээ утгууд нь ердийн тоон тооцоонд
хамаарна; solver-ийн үл мэдэгдэх дээр хэрэглэх боломж тусдаа дүрэмтэй.

| Функц | Утга | Жишээ |
|---|---|---|
| `abs(x)` | Абсолют утга | `abs(-3)` → 3 |
| `min(...)`, `max(...)` | Хамгийн бага/их | `max(0, -2)` → 0 |
| `pow(x, p)` буюу `x**p` | Зэрэг | `pow(2, 3)` → 8 |
| `sqrt(x)` | Квадрат язгуур, x≥0 | `sqrt(9)` → 3 |
| `log(x)` | Натурал логарифм, x>0 | `log(1)` → 0 |
| `exp(x)` | e-ийн зэрэг | `exp(0)` → 1 |
| `positive_part(x)` | max(x,0) | `positive_part(-2)` → 0 |
| `vector([…])` | Vector үүсгэх | `vector([2,3])` |
| `SUM(v)` | Нийлбэр | `SUM([2,3])` → 5 |
| `AVG(v)` | Арифметик дундаж | `AVG([2,4])` → 3 |
| `COUNT(v)` | Элементийн тоо | `COUNT([2,4])` → 2 |
| `DOT(a,b)` | Scalar үржвэр | `DOT([2,3],[4,5])` → 23 |
| `NORM(v)` | Евклидийн норм | `NORM([3,4])` → 5 |
| `COLUMN('X')` | Бүх мөрийн X баганыг vector авах | `COLUMN('QTY')` |
| `COLUMN_SUM('X')`, `AGG_SUM('X')` | Баганын нийлбэр | `COLUMN_SUM('QTY')` |
| `AGG_MIN('X')`, `AGG_MAX('X')` | Баганын бага/их | `AGG_MAX('RATE')` |
| `POISSON_CAPPED_MEAN(mean,cap)` | Poisson X-ийн E[min(X,cap)] | Нөөцөөр хязгаарласан тооллого |
| `NB_CAPPED_MEAN(mean,dispersion,cap)` | NB2 X-ийн E[min(X,cap)] | Var(X)=mean+dispersion×mean² |

`SUM_OVER(axis, expression)` нь indexed compiler-ийн тусгай нийлбэр;
бүх төрлийн expression-д ажиллах энгийн функц биш.

### Функц хэрэглэх зааг

- Тоон `log(2)`, `sqrt(9)` ажиллана. LP-ийн decision `x` дээр `log(x)`
  ажиллуулахгүй.
- MILP-ийн `positive_part(affine)`-д хувьсагчдын explicit finite bounds хэрэгтэй.
- Capped-mean функцүүд scalar тоон аргументтай. `E[min(X,c)]` ба
  `min(E[X],c)` ерөнхийдөө тэнцүү биш.
- `sin`, `cos`, дурын library function, Python import, attribute access
  нь энэ AST-ийн бүртгэлтэй функцүүд биш.
- Үйлдлүүд: `+`, `-`, `*`, `/`, `**`; constraint: `<=`, `>=`, `==`.
  Хатуу `<`, `>`, дурын `if`, loop, lambda дэмжихгүй.

## 8. Гүйцэтгэл ба гаралт

### Python-оос шууд ашиглах

Repository-ийн орчинд package суусан байна:

```python
import json
from pathlib import Path
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute

payload = json.loads(Path("model.json").read_text(encoding="utf-8"))
request = ExecutionRequest.model_validate(payload)
result = execute(request)
print(result.model_dump())
```

Model-ийн бүтцийг урьдчилан шалгах бол `math_engine.compiler.validate_model`
ашиглана. Validation амжилттай болсон нь өгөгдөлтэй бодлого шийдэлтэй,
эсвэл тооцоолол converge болно гэсэн баталгаа биш.

### Үр дүнг унших

| Талбар | Тайлбар |
|---|---|
| `status` | succeeded / infeasible / unbounded / failed |
| `row_ids` | Оролтын мөрийн дараалал |
| `outputs` | Мөр тус бүрийн тооцсон гаралт |
| `aggregates` | Нийт өгөгдөл/scenario дээрх reduction утгууд |
| `solution` | Optimizer-ийн шийдвэрийн утгууд |
| `objective` | Оновчлолын зорилгын утга; бусад төрлүүдэд null байж болно |
| `diagnostics` | Solver, tolerance/gap, convergence зэрэг төрлөөс хамаарах мэдээлэл |
| `fitted_artifact` | Statistical fit амжилттай үед хадгалж болох model artifact |

Эхлээд status, дараа нь diagnostics, эцэст нь тоон шийдлийг хэрэглэнэ.
`infeasible` нь нөхцөлүүдийг зэрэг хангах шийдэлгүй, `unbounded` нь зорилго
өгсөн хязгаарлалтаар тогтоогдоогүй гэсэн утгатай. Failed үед output байна
гэж таамаглахгүй. Буруу contract/AST/domain нь result биш exception болж болно.

Цөмийн `execute()` нь **өөрөө өгөгдлийн санд хадгалахгүй**, HTTP/Oracle
дуудахгүй. API ба job нь цөмийг хүрээлсэн тусдаа ажиллагааны давхарга.
`persist=true` нь Data API artifact хадгалалт; эх Oracle хүснэгтэд бичихгүй.
Шууд CLI/Python нь API-ийн 90 секундийн process timeout-ийг өвлөхгүй.

## 9. Алдаа ба чадамжийн зааг

| Шинж | Шалгах зүйл |
|---|---|
| Үл мэдэгдэх нэр | inputs/parameters/decisions-ийн зарлал, үсгийн том жижиг |
| Буруу үе шат | row дотор aggregate/solution ашигласан эсэх |
| Vector хэмжээ зөрсөн | Dataset мөрийн тоо, decision size, DOT-ийн урт |
| Nonlinear expression | LP/MILP decision хоорондын үржвэр, log/exp зэрэг |
| Domain error | log-ийн эерэг оролт, sqrt-ийн сөрөг бус оролт, 0-д хуваалт |
| Infeasible | Доод/дээд bounds, нөөц, minimum нөхцөлүүд зөрчилдсөн эсэх |
| Unbounded | Шийдвэрт шаардлагатай дээд/доод хязгаар дутсан эсэх |
| Convergence/limit failure | Нарийвчлал, subdivision/evaluation/time limit, өгөгдлийн масштаб |

**Одоогийн хүрээ:** dataset 10,000 хүртэл мөр; indexed model 4 axis,
1000 expanded variable; finite candidate grid 10,000 хүртэл хамтарсан сонголт.
Contract болон AST-д бусад хэмжээний хязгаар мөн бий.

**Одоогоор байхгүй:** ерөнхий symbolic algebra, arbitrary nonlinear constrained
optimization, derivative/ODE, олон хэмжээст интеграл, том sparse/decomposition
урсгал. Статистик fitting, интегралын convergence нь ерөнхий nonlinear solver
дэмжлэгтэй адил утга биш.

## 10. Загвар бэлтгэх шалгах хуудас

1. Тооцох зүйлээ нэг өгүүлбэрээр тодорхойлж, тохирох `kind` сонгосон уу?
2. Мэдэгдэж буй input/parameter ба олох decision/trainable-ийг ялгасан уу?
3. Мөрийн ID, баганын нэр, хэмжих нэгж, хугацааны суурь нэг мөр үү?
4. Зорилго, bounds, constraint, анхны/boundary утгууд бүрэн үү?
5. Scenario ашигласан бол жин ба тухайн мөчид мэдэгдэх мэдээлэл зөв үү?
6. Жижиг өгөгдөл дээр гараар бодсон эсвэл аналитик хариутай тулгасан уу?
7. Status, diagnostics, error estimate/gap-ийг шалгасан уу?
8. Өгөгдөл өөрчлөгдөхөд үр дүн хэрхэн өөрчлөгдөхийг туршсан уу?

---

**Дараагийн лавлах:** [README](../README.md) · [Postman](../POSTMAN_GUIDE.md) ·
[Серверийн файлууд](SERVER_FILES_AND_READINESS.md)

Энэ гарын авлагын 3 JSON хүсэлтийг цөмөөр ажиллуулж, 44, 52, 8 гэсэн
хүлээгдсэн утгуудтай тулган шалгасан. Хөдөлгүүрийн v0.6.0 сүүлийн бүрэн
regression нь 201 тест давсан; энэ нь бизнесийн бодит үр дүнгийн баталгаа биш.
