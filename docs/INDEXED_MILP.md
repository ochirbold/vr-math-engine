# Нийтлэг indexed/MILP чадамж — v0.4

Цөмд replenishment/allocation solver нэмээгүй. Хэрэглэгч variable domain,
индекс, зорилгын функц, constraint, scenario information-оо JSON contract-аар өгнө.
Compiler эдгээрийг finite deterministic-equivalent LP/MILP matrix болгон хөрвүүлнэ.
Шинэ backend нь SciPy `milp`/HiGHS; бүх хувьсагч continuous бөгөөд nonlinear
positive-part auxiliary байхгүй үед ердийн `linprog` ашиглана.

## Хоёр contract

`mixed_integer_program` нь одоогийн `linear_program` хэлбэртэй ижил бөгөөд decision
бүрт `domain: continuous | integer | binary` нэмнэ. Binary bounds [0,1]-тэй
огтлолцоно. Integer constraint-ийг LP шийдлийг тоймлох замаар орлуулахгүй.
`linear_program` дотор integer/binary domain өгвөл ил тод татгалзана.

`indexed_program` нь хугацаа, салбар, scenario гэх мэт хэрэглэгчийн нэрлэсэн
finite integer axes-тай илэрхийллийг scalar хувьсагч/constraint болгон задална.
Axis нэрд тусгай бизнес утга байхгүй.

```json
{
  "axes": {"t": [0, 1], "s": [0, 1]},
  "decisions": {
    "order": {"axes": ["t"], "domain": "integer", "lower": 0, "upper": 6},
    "placed": {"axes": ["t"], "domain": "binary"}
  },
  "constraints": [
    {"over": ["t"], "expression": "minimum * placed[t] <= order[t]"},
    {"over": ["t"], "expression": "order[t] <= maximum * placed[t]"}
  ]
}
```

Энэ нь contract-ийн хэсэг; бүтэн ажиллах JSON-ууд `examples/indexed_*.json` дотор бий.

## Индекс ба өгөгдөл

- `inputs`: snapshot dataset-д байгаа тоон баганууд.
- `axes`: давтагдаагүй integer labels. `t-1` нь label-аас нэгийг хасна; жагсаалтын
  өмнөх элементийг автоматаар сонгохгүй. Цаг хугацааны утгыг application тодорхойлно.
- `tables`: `axes` ба `column` өгнө. Dataset-ийн axis нэртэй багануудаар key үүсгэж,
  value column-ыг уншина. Ижил key-тай давтагдсан мөрүүдийн value ижил байх ёстой.
  Table-ийн Cartesian бүх key бүрэн байх ёстой; missing утгыг 0 гэж нөхөхгүй.
- `parameters`: хүсэлтийн scalar constants; жишээ нь lead time, өртөг, эхний төлөв.
- `decisions`: нэр бүрийн axes/domain/bounds. `q[t]`, `state[t,s]` байдлаар хэрэглэнэ.
- `over`: constraint/objective term-ийг ямар axis-уудаар давтахыг заана.
- `SUM_OVER(b, allocation[b])`: нэг axis-аар нийлбэрлэнэ; nested sum зөвшөөрнө.
  Аль хэдийн bound axis-ийг давхар нэрлэж дарахгүй.
- `objective.terms`: term бүрийг `over`-оор задалж, бүгдийг нийлбэрлэнэ. Expectation
  хийх бол `probability[s] * cost[...]`-ийг хэрэглэгч ил тод бичнэ; compiler жинг автоматаар нэмэхгүй.

Index нь bound axis, fixed parameter, table value-ээс тооцогдож болно;
шийдвэрийн хувьсагчаар индекс сонгохгүй. Dynamic Python/subscript execution байхгүй.
`q[t-lead]` шиг horizon-оос өмнөх reference бүрд explicit boundary хэрэгтэй:

```json
"boundary": [{"index": [-1], "expression": "pipeline"}]
```

Boundary expression зөвхөн fixed parameter ашиглана. Давхардсан boundary эсвэл
жинхэнэ decision coordinate-ийг дарсан boundary-г хориглоно. Missing boundary нь алдаа.
Variable bounds нь тухайн indexed бүлэгт scalar байна; coordinate тус бүрийн илүү
хатуу bounds-ийг table ашигласан constraint-аар өгч болно.

## Scenario, recourse, мэдээлэл

`scenario_axis` болон `probability_table` хамт өгнө. Probability table нь тэр axis-аар
индексжсэн, эерэг, нийлбэр нь 1 байна. Zero-probability scenario-г input бэлтгэх үед хасна.
Probability-оос үл хамааран бүх explicit constraint хэрэгжинэ.

- Scenario axis агуулаагүй decision нь бүх scenario-д **нэг shared шийдвэр**.
- Scenario axis-тай decision нь `information`-оо заавал тодорхойлно.
- `information: "scenario_specific"` нь scenario бүрт тусдаа шийдвэр/төлөв зөвшөөрнө.
  Үүнийг ашигласнаар тухайн шийдвэр мэдээллийн хувьд зөв гэдгийг compiler батлахгүй.
- Explicit partition нь ялгагдахгүй scenario-уудын шийдвэрийг equality-гаар холбоно:

```json
"information": [
  {"at": {"t": 0}, "groups": [[0, 1]]},
  {"at": {"t": 1}, "groups": [[0], [1]]}
]
```

Энд t=0 үед scenario 0/1-ийн choice ижил, t=1 үед ялгаатай байж болно.
Partition нь бүх scenario-г яг нэг удаа багтааж, decision-ийн бүх non-scenario
coordinate-ийг хамарна. Scenario history-оос information groups-ийг автоматаар
үүсгэхгүй; ямар үед ямар мэдээлэл мэдэгддэгийг model author зөв тодорхойлно.
Одоогоор scenario tree-ийн цаг хугацааны refinement consistency-г автоматаар батлахгүй.

## Positive-part exact linearization

`positive_part(v)`-д v affine бөгөөд орсон хувьсагчдын explicit lower/upper finite
байвал compiler v-ийн [L,U] bounds-ийг interval arithmetic-аар тооцно.
L≥0 үед v, U≤0 үед 0. L<0<U үед y болон binary z нэмж:

```text
y >= 0, y >= v, y <= U*z, y <= v - L*(1-z)
```

гэж дүрслэнэ. Иймээс minimize/maximize, эерэг/сөрөг coefficient, equality constraint
дотор ч `y=max(0,v)` утгыг хадгална. Зөвхөн epigraph үүсгээд утгыг сулруулахгүй.
Finite bounds байхгүй бол arbitrary big-M таахгүй. Bounds-ийг бусад constraint-аас
автоматаар infer хийхгүй. Хэт сул/том bounds нь MILP-ийн тоон тогтвортой байдал,
ажиллах хугацаанд сөрөг нөлөөлж болно. Бусад nonlinear функц автоматаар linearize хийхгүй.

## Үр дүн ба шалгалт

Solver status, MIP gap, objective bound, node count, integrality violation болон
constraint residual-ийг diagnostics-д өгнө. Integer утгыг зөвхөн integer tolerance
дотор эсэхийг шалгасны дараа round хийгээд, бүх constraint/bounds-ийг дахин шалгана.
Time/node limit хүрсэн incumbent-ийг `succeeded` гэж нийтлэхгүй; `failed` ба
`limit_reached` буцаана. `mip_relative_gap` default 0; хэрэглэгч >0 өгсөн бол solver-ийн
зөвшөөрсөн gap доторх шийдэл гэдгийг diagnostics-тай нь тайлбарлана.

Indexed solution нь нэр тус бүрийн flat list; `diagnostics.indexed_layout` дахь
axis/index дарааллаар тайлбарлана. Эдгээр нь source dataset row output биш тул
`outputs` нь source row бүрт `{}`. Job result нь objective/solution/diagnostics-ийг
бүхэлд нь хадгална; Data API-ийн row writeback-д indexed solution-ийг map хийхгүй.

## Ажиллуулсан жишээнүүд

```powershell
.\.venv\Scripts\python.exe -m math_engine examples/indexed_allocation.json
.\.venv\Scripts\python.exe -m math_engine examples/indexed_replenishment.json
.\.venv\Scripts\python.exe -m math_engine examples/indexed_information.json
```

| Жишээ | Үр дүн | Хөндлөн шалгалт |
|---|---|---|
| Integer allocation, 3 салбар × 3 scenario | [3,3,1], cost=14.2, total=7 | Бүх боломжит integer хуваарилалтыг тусдаа enumerator-оор шалгасан |
| 2 хугацаа × 2 scenario, lead=1, MOQ=2 | order=[4,0], placed=[1,0], cost=9.5 | Захиалга бүрээр inventory simulator ажиллуулж шалгасан |
| 2 үеийн мэдээллийн partition | choice=[3,3,2,4], cost=6 | Information constraint-ийг хасахад clairvoyant cost=5 болж өөрчлөгддөг |

Эдгээр нь зохиомол, жижиг загварууд. Replenishment жишээ бүх order-оо урьдчилан
shared байдлаар сонгодог; adaptive order хэрэгтэй бол scenario-indexed decision ба
зөв information partition хэрэглэнэ. Lost demand, тогтмол lead, terminal salvage=0
гэсэн жишээний таамаглалтай. Захиалгагүй бол reorder time байхгүй; захиалгатай үед
эхний positive order-ийн t-г application solution-оос гаргаж авна.
Эхний нөөцийн аудит, зөвшөөрөгдсөн салбарын G gate, ERP action нь application-ийн үүрэг.

Ижил нэрүүдийг `scripts/demo_job.py`-д өгч HTTP job/worker урсгалаар ажиллуулж болно.
Generic model registration/execution endpoint-д шинэ kind-ууд холбогдсон.

Хязгаар: 4 axis, 1000 expanded variable (auxiliary-г оруулна), 5000 expanded
term/constraint, 1,000,000 dense matrix cell. Одоогийн shared AST parser-ийн
expanded expression бүрийн 400-node хязгаар мөн үйлчилнэ. Sparse matrix болон
том scenario tree-ийн decomposition хараахан байхгүй; том production хэмжээний
гүйцэтгэлийн баталгаа өгөхгүй. Scenario-уудын гаднах эрсдэл, scenario quality болон
реал мэдээллийн availability-г solver өөрөө батлахгүй.
