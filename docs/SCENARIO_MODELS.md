# Нийтлэг scenario математик чадамж — v0.3

v0.4-ийн integer/binary, indexed recourse болон information partition нь тусдаа
`indexed_program` contract-д нэмэгдсэн: [Indexed/MILP](INDEXED_MILP.md).
Энэ хуудасны finite candidate backend-ийн хязгаарууд `scenario_program`-д хамаарна.

Зорилго: дэмждэг математик үйлдлээр илэрхийлэгдэх шинэ бодлогод core код
өөрчлөхгүй, JSON model + data + parameters өгч ажиллуулах.

## Архитектурын зааг

| Давхарга | Агуулга |
|---|---|
| Core | AST, scalar/vector шалгалт, тархалтаас sampling, finite probability measure, reductions, objective/constraint үнэлгээ, solver |
| Model contract | Хэрэглэгчийн нэртэй хувьсагч, томьёо, candidate шийдвэр, objective, constraints |
| Application | ERP, audit gate, SKU/branch, lead time, feature болон output mapping |

`uncertainty.py` нь probability operation; `scenarios.py` нь compiler ба execution;
`FiniteEnumerationSolver` нь хязгаарлагдмал Cartesian сонголтыг шалгах backend.
Цөмд inventory/demand-specific identifier эсвэл өртгийн томьёо байхгүй.
Одоогийн calculation, LP, statistical fitting contract-ууд тусдаа хэвээр.

## Өгөгдлийн хоёр горим

1. **Supplied joint scenarios:** `sampling` байхгүй. Dataset-ийн нэг мөр нь бүх
   санамсаргүй хувьсагчийн нэг хамтарсан scenario. Багануудын хамаарлыг эвдэхгүй.
   `weight_column` заавал өгвөл тэр баганын nonnegative жинг normalize хийнэ;
   өгөөгүй бол ижил жинтэй. Нийт жин эерэг байна. Zero-mass мөрийг distribution
   support-оос хасах тул тэндэх expression domain эсвэл constraint нөлөөлөхгүй.
2. **Independent sampling:** `sampling.dependence: "independent"`, `seed`, `count`,
   `variables` өгнө. Dataset яг нэг deterministic context мөртэй байна. Хамааралгүй
   гэдгийг заахгүй бол schema татгалзана. Monte Carlo нь тархалтын ойролцоо дүрслэл.

Sampling family ба аргумент:

| Family | Arguments (AST expression string) |
|---|---|
| `poisson` | `mean >= 0` |
| `negative_binomial` | `mean > 0`, `dispersion > 0`; variance = mean + dispersion × mean² |
| `normal` | `mean`, `stddev > 0` |
| `uniform` | `lower < upper` |

Sampling аргумент нь parameters болон deterministic context input-ээс хамаарч
болно. Өөр random variable, formula, decision-оос хамаарах conditional sampling
одоогоор байхгүй. Variable нэрээр тусдаа random stream үүсгэнэ; seed, variable name,
NumPy version ижил үед давтагдана. Нэр солиход draw өөрчлөгдөнө.

## Илэрхийлэл, reductions, шийдвэр

- `formulas`: `row` stage-ийн scalar AST; dependency order-ийг compiler тогтооно.
  `a+b` нь нэг scenario доторх нийлбэр. Random variable-уудын sum-ийг NB гэж автоматаар таахгүй.
- `positive_part(x)=max(x,0)`. Calculation/scenario-д хэрэглэнэ. LP decision-ийн
  nonlinear positive part-ийг автоматаар linearize хийхгүй; тодорхой алдаагаар татгалзана.
- `reductions`: нэр бүрийн `expression` + `operation` нь `expectation`, `variance`,
  `quantile`. Variance нь finite measure-ийн population variance; unbiased sample estimator биш.
- `quantile.probability`: fixed parameter-ээс тооцож болох expression, жишээ нь
  `under_cost/(over_cost+under_cost)`. Scenario эсвэл decision-оос хамаарахгүй; [0,1] утгатай.
  Weighted inverse empirical CDF хэрэглэнэ; interpolation хийхгүй. q=0 үед хамгийн бага
  positive-mass утга, q=1 үед хамгийн их утга. Үр дүн нь analytic distribution quantile биш.
- `decisions`: нэр бүрийн зөвшөөрсөн scalar `values`. Integer эсвэл noninteger утга байж болно.
- `objective`: expression + reduction + minimize/maximize. Mean, variance, quantile
  зэрэг дэмждэг хэмжүүрээр шийдвэр сонгоно; нэг weighted-sum formula-аар олон өртгийг нэгтгэж болно.
- `constraints`: `<=`, `>=`, `==`. Positive-weight scenario **бүрт** шалгана.
  Sampling үед зөвхөн sampled scenario-уудыг хангана; бүх population-д баталгаа өгөхгүй.
  Chance constraint/expectation constraint эсвэл recourse decision хараахан байхгүй.

Finite enumeration бүх candidate combination-ийг шалгана. Equal objective үед sorted
decision names болон ascending candidate values дарааллаар эхний шийдлийг сонгоно.
Invalid expression domain-ийг infeasible гэж нуухгүй, model error болгоно. Зөвхөн ил тод
constraint зөрчсөн candidate-ийг infeasible гэж үзнэ. Time limit үед partial optimum нийтлэхгүй.

Энэ backend-ийн optimum нь **өгсөн finite measure ба candidate grid доторх** optimum.
Тасралтгүй decision domain, жинхэнэ population distribution, сонгоогүй candidate-ийн
optimum гэсэн баталгаа биш. Supplied scenarios нь бодит distribution-ийг сайн дүрсэлж
байгаа эсэхийг хөдөлгүүр мэдэхгүй. Diagnostics-д source, seed, NumPy version, scenario
checksum, candidate count, optimum scope гаргана.

## Ижил хөдөлгүүр дээрх гурван жишээ

```powershell
.\.venv\Scripts\python.exe -m math_engine examples/scenario_balance.json
.\.venv\Scripts\python.exe -m math_engine examples/scenario_capacity.json
.\.venv\Scripts\python.exe -m math_engine examples/scenario_sampling.json
```

| Model | Хэрэглэгчийн өгсөн математик | Үр дүн |
|---|---|---|
| `scenario_balance` | 2×(level−requirement)⁺ + 8×(requirement−level)⁺ | level=9, expectation=6.8, q80=9 |
| `scenario_capacity` | 4×units + (workload−5×units)⁺², budget≤12 | units=2, expectation=8.25 |
| `scenario_sampling` | Independent NB a+b; mean, variance, q80 | Seed 20261027, NumPy 2.2.6: mean≈10.0218, variance≈33.4705, q80=14 |

Гурав дахь жишээний онолын mean=10, variance=33.2. Monte Carlo үр дүн яг тэнцүү
байх шаардлагагүй. Simulation-ийн numerical reproducibility нь model correctness-ийн баталгаа биш.

Сервисүүд асаалттай үед эдгээр нэрийг `scripts/demo_job.py`-д өгч болно:

```powershell
.\.venv\Scripts\python.exe scripts/demo_job.py scenario_balance
.\.venv\Scripts\python.exe scripts/demo_job.py scenario_capacity
.\.venv\Scripts\python.exe scripts/demo_job.py scenario_sampling
```

Model registration, snapshot, job, worker, isolated execution хуучин урсгалаар ажиллана.
Үр дүн `aggregates`, `solution`, `objective`-д байна. Эдгээр aggregate-only загварын
`outputs` нь source input мөр бүрт `{}`: generated scenario-уудыг эх snapshot мөрүүдтэй
андуурч map хийхгүй. `persist=true` үед Data API-д хоосон row outputs л хадгалагдана;
бүрэн aggregates/solution нь `persist`-ээс үл хамааран Job result-д хадгалагдана.

## Одоогийн хязгаар

100 random variable, 10,000 scenario, 8 decision, нэг decision-д 1,000 candidate,
нийт 10,000 candidate combination. Нийлмэл тооцооны ажлын дээд хэмжээ 2,000,000
scenario/expression evaluation estimate; solver time ≤60 секунд, service wall timeout хэвээр.

Analytic convolution, exact theoretical CDF/PPF expression, copula, conditional sampling,
automatic confidence interval, symbolic expectation, continuous stochastic optimizer,
chance constraint хараахан байхгүй. Large grid-д өөр backend шаардлагатай.
Inventory audit gate, ERP болон allocation-specific холбоос нэмээгүй. Тэд application layer-ийн ажил.
