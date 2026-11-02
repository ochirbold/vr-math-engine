# Статистик загвар ба demand pilot

Энэ баримтын командуудыг repository-ийн үндсэн хавтсаас ажиллуулна.

## Statistical fitting ба prediction

`kind: "statistical_fit"` нь одоогийн Model/Job → Worker → Compute урсгалаар ажиллана.
Poisson болон Negative Binomial нь нэг likelihood fitting backend ашиглана. Шинэ
distribution бүрт тусдаа сервис хэрэггүй. LP нь `linprog/HiGHS`, fitting нь
`minimize/L-BFGS-B` ашиглана; LP matrix ба nonlinear objective тусдаа contract-тай.

```powershell
.\.venv\Scripts\python.exe -m math_engine examples/poisson.json
.\.venv\Scripts\python.exe -m math_engine examples/negative_binomial.json
# dev_stack.py ажиллаж байхад fit → artifact → prediction бүтэн урсгал:
.\.venv\Scripts\python.exe scripts/demo_job.py poisson
.\.venv\Scripts\python.exe scripts/demo_job.py negative_binomial --persist
```

Poisson жишээний count нь `[1,2,3,4,5,3]`. Сурсан `intercept≈log(3)` бөгөөд
prediction mean/variance нь хоёулаа `3` болно. Negative Binomial жишээнд latent count-ийг
8 дээр хязгаарлан ажигласан хоёр мөр бий. Сурсан mean нь ажигласан, таслагдсан
тоонуудын энгийн дунджаас их гарна. Эдгээр нь математик ажиллагааг шалгах зохиомол жишээ.

Contract:

- `inputs`: зөвхөн predictor-ийн feature баганууд. Response/censor багана энд орохгүй.
- `parameters`: хүсэлтээр өгөх тогтмол утга; `trainable`: сургах параметрийн initial,
  lower/upper, `identity` эсвэл `log` transform. Log transform нь эерэг утга хадгална.
- `predictor`: мөр бүрт scalar гаргах AST илэрхийлэл; `link` нь `log` эсвэл `identity`.
  Log link үед `mu=exp(predictor)`, identity үед `mu=predictor>0`.
- `distribution`: `poisson` эсвэл `negative_binomial`. NB2 нь
  `variance=mu+alpha*mu²`; `dispersion_parameter` нь alpha-г нэрлэнэ.
- `observation.kind=exact`: nonnegative integer response-ийн log PMF.
- `observation.kind=right_censored`: `response`, `censored`, `threshold` багануудтай
  `Y=min(D,A)` механизм. Indicator=0 үед `Y<A` ба log PMF; indicator=1 үед `Y=A`
  ба `log P(D>=A)=logsf(A-1)`. Indicator зөвхөн 0/1. Equality-гаас censoring таахгүй.
- `standardize`: training өгөгдлөөс center/scale сургах feature нэрс. Prediction үед
  яг хадгалсан transform-ийг ашиглана. Constant feature-ийн scale=1.

Compiler scalar/vector хэлбэр, тогтмол vector хэмжээ, нэр ба функцийн хэрэглээг шалгана.
`log(x)` нь `x>0`, `sqrt(x)` нь `x>=0`; overflow ба finite бус утгыг алдаа болгоно.
Домэйн нь execution үед шалгагдана; interval proof эсвэл физик нэгжийн type system хараахан байхгүй.
LP шийдвэрийн `exp`/`log` зэрэг nonlinear хамаарлыг matrix builder хориглосон хэвээр.
Fitting backend нь `abs/min/max/NORM` зэрэг мэдэгдэж буй nonsmooth predictor-ийг татгалзана.
`GET /v1/capabilities`-аас одоогийн функц, backend, distribution/observation төрлийг харж болно.

Амжилттай fit-ийн `fitted_artifact` нь model/version, fitted/fixed parameters,
feature preprocessing, training dataset SHA-256, мөрийн тоо, engine/SciPy version,
negative log likelihood-ийг агуулна. Job result-тэй нэг transaction-д хадгална;
`persist=false` үед ч Job API-д үлдэнэ. Job-ийн snapshot ID нь эх өгөгдлийн provenance-ийг холбоно.
`GET /v1/jobs/{id}/fitted-artifact` нь content checksum болон artifact буцаана.
Шууд compute/CLI fit бол artifact-ийг response-д буцаах бөгөөд өөрөө баазад хадгалахгүй.

Prediction хүсэлт нь `{"artifact": <fitted_artifact>, "dataset": <feature-only dataset>}`.
Үүнийг `POST /v1/predictions` эсвэл JSON файлд хадгалаад CLI-ийн `--predict` сонголтоор
ажиллуулна. Prediction дахин fit хийхгүй, response/censor багана шаардахгүй.
Гаралт нь latent distribution-ийн `mean`, `variance`; clipped observation-ийн forecast биш.
Artifact нь JSON бөгөөд pickle/Python код ачаалахгүй. Inline artifact нь trusted caller-аас
ирнэ; checksum нь тооцооны зөв байдал эсвэл эх сурвалжийн криптограф гарын үсгийн баталгаа биш.

Хязгаар: fitting нь локал maximum-likelihood estimation, numerical gradient ашиглана.
Convergence нь global optimum, identifiable параметр, прогнозын чанарыг батлахгүй.
`diagnostics` нь convergence, iteration, boundary параметр, censor мөрийн тоог харуулна.
Сургалтын хугацаа дуусах эсвэл optimizer convergence хүрэхгүй үед `failed`, artifact байхгүй.
Бүх мөр censored бол энэ backend татгалзана. All-zero/constant/collinear өгөгдөл болон
boundary estimate-ийг хэрэглээний түвшинд үнэлэх шаардлагатай. Bounds нь optional боловч
тоон тогтвортой байдалд тохирсон bounds өгөхийг зөвлөе.

Одоогоор confidence interval, quantile prediction, automatic feature generation,
zero-inflation, interval/left censoring, truncation, arbitrary likelihood, autodiff,
ерөнхий nonlinear constraint solver байхгүй. Censor threshold-ийг үл мэдэгдэх demand-тай
хамааралтайгаар сонгосон бол энэ likelihood дангаараа тухайн selection mechanism-ийг загварчлахгүй.
Production хэрэглээнд хугацаагаар салгасан validation/backtest, data leakage болон model
quality шалгалтыг тусад нь хийх ёстой; сургалтын likelihood нь backtest биш.

## Нэг SKU × салбарын demand pilot

`src/math_engine/applications/demand.py` нь ерөнхий core-ийн дээрх хэрэглээний урсгал.
Үнэ, урамшуулал, жилийн seasonality-ийн feature үүсгэх, хугацаагаар салгах, horizon
нийлбэрлэх логик энд байрлана; generic compiler/solver-д SKU, салбарын нэр оруулаагүй.

```powershell
# Бодит баазад хандахгүй. Seed=20261027 зохиомол өгөгдөл үүсгээд бүтэн туршилт хийнэ.
.\.venv\Scripts\python.exe scripts/demand_pilot.py
# Тусгай output хавтас өгөх бол шинэ, байхгүй хавтас сонгоно:
.\.venv\Scripts\python.exe scripts/demand_pilot.py --output var/my-demand-experiment
# Ижил contract-тай бодит өгөгдлийн JSON бэлтгэсэн үед:
.\.venv\Scripts\python.exe scripts/demand_pilot.py --input path/to/request.json
```

Анхдагч simulation нь 365 training өдөр, 90 holdout өдөр, 90 future өдөртэй.
`D~NB(mu,alpha)` үүсгээд, training/holdout-д зөвхөн `sales=min(D,available)` өгнө.
Zero-capacity өдрийг ч багтаасан. `latent_demand`, `true_mean` нь тусдаа truth файлд
байх бөгөөд fitting/prediction оролтод орохгүй. Генератор ба fitted model ижил
загварын ангилалтай тул энэ нь controlled recovery test; бодит өгөгдлийн баталгаа биш.

Хэрэглээний contract нь нэг `sku`, `branch`, `train_end`, `history`, `future` авна.
History мөр: ISO `date`, `price>0`, 0/1 `promotion`, integer `sales`, `available`,
0/1 `censored`. Future мөр: зөвхөн `date`, `price`, `promotion`.
Өдрүүд эрэмбэтэй, давтагдаагүй, тасралтгүй байх ёстой; missing өдрийг борлуулалт=0 гэж
автоматаар нөхөхгүй. Future нь history-ийн маргаашаас эхэлсэн яг 90 өдөр байна.
Бүх мөрийг нэг SKU/салбарт хамааруулж бэлтгэх нь input бэлтгэгчийн үүрэг.
Constant/collinear feature байвал pilot алдаа өгнө; ийм өгөгдөлд feature багатай
загварыг ил тод сонгох хэрэгтэй. Энэ preset-ийн feature нь `log(price/100)`, promotion,
2024-01-01 epoch ба 365.25 period-тай sine/cosine. Log price-ийн standardization
зөвхөн тухайн fit-ийн training өгөгдлөөс сурна.

Гүйцэтгэл нь гурван тусдаа fit хийнэ:

1. Training хэсэг дээр feature-тэй censored NB сургаж, holdout-д шалгана.
2. Ижил training дээр intercept-only censored NB сургаж baseline-тай харьцуулна.
3. Бүх history дээр дахин сургаж тусдаа artifact үүсгэн, future 90 өдрийг прогнозлоно.

Holdout-ийн observation NLL нь censoring-ийг зөв тооцно; бага байх нь сайн.
Zero-capacity мөрийг хассан NLL-ийг мөн тусад нь харуулна. Exact-subset MAE нь зөвхөн
uncensored сонгогдсон дэд олонлогийн алдаа. Simulation-д л мэдэгдэх latent-demand
MAE/RMSE/WAPE болон true-mean MAE-г тусдаа үнэлнэ. Holdout-аар parameter/model selection
хийхгүй. Future feature-үүдийг мэдэгдэж буй scenario гэж үздэг; бодит backtest-д тухайн
үед мэдэгдэж байсан үнэ/урамшууллын plan ашиглах шаардлагатай.

Output хавтас:

- `request.json`: truth агуулаагүй, дахин ажиллуулах боломжтой оролт.
- `synthetic-truth.json`: зөвхөн simulation-ийн нуугдмал demand, true mean, seed.
- `report.md`, `report.json`: split, metrics, өдрийн prediction, 7/30/90 хоногийн нийлбэр.
- `evaluation-artifact.json`, `forecast-artifact.json`: training-only болон full-history artifact.
- `prediction-request.json`: generic `POST /v1/predictions` эсвэл
  `python -m math_engine <file> --predict`-д шууд өгч болох хүсэлт.

CLI pilot нь локал core-ийг ашиглана; сервис/Oracle асаах шаардлагагүй. Нэг SKU/салбарын
энэ туршилт нь олон SKU-ийн batch orchestration, indexed/shared параметр эсвэл hierarchical
моделийг хараахан хэрэгжүүлээгүй. Prediction interval гаргахгүй, daily mean-үүдийг нийлбэрлэнэ.
