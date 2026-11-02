# Transfer ба Assortment: existing v0.4 core дээрх жишээнүүд

Эдгээр загварт зориулж engine, compiler, solver өөрчлөөгүй. `indexed_program`
contract, integer/binary domain, finite bounds-тай positive-part linearization,
HiGHS MILP backend-ийг ашиглана. Өгөгдөл нь зохиомол; Oracle/ERP-д хандахгүй.

```powershell
.\.venv\Scripts\python.exe -m math_engine examples/indexed_transfer.json
.\.venv\Scripts\python.exe -m math_engine examples/indexed_assortment.json
# Сервисүүд асаалттай үед яг эдгээр загварыг HTTP job-оор:
.\.venv\Scripts\python.exe scripts/demo_job.py indexed_transfer
.\.venv\Scripts\python.exe scripts/demo_job.py indexed_assortment
```

## Transfer

Нэг SKU, A=0/B=1 гэсэн хоёр салбар, t=0/1 үнэлгээний огноо, хоёр joint demand scenario.
Зөвхөн t=0 үед dispatch нээлттэй. Lead time=1; өмнөх pending shipment default 0.

| Оролт | A | B |
|---|---:|---:|
| Эхний нөөц | 8 | 0 |
| Илгээгчид үлдээх reserve | 2 | 0 |
| Багтаамж | 10 | 10 |
| Баталгаажсан gate | 1 | 1 |
| Нэгж shortage penalty | 5 | 5 |
| t=0 эрэлтийн зорилт | 2 | 4 |
| t=1 эрэлтийн зорилт, probability .5/.5 | 2/2 | 4/6 |

Шилжүүлэх нэгжийн өртөг 1. Зорилгын функц нь хоёр үнэлгээний огнооны expected
shortage penalty дээр dispatch өртгийг нэмсэн нийт дүн. Үр дүн: **t=0 үед A→B 6**, cost=26.

| Үе | A нөөц | B нөөц | Замд яваа |
|---|---:|---:|---:|
| t=0, илгээсний дараа | 2 | 0 | 6 |
| t=1, ирсний дараа | 2 | 6 | 0 |

Илгээгчийн reserve хадгалагдана; B-ийн t=0 дутагдлыг замд яваа бараагаар нөхөхгүй.
Тэр өдрийн 4×5=20 shortage cost нь зайлшгүй, dispatch cost=6.

Зураг дээрх J баланс борлуулалтыг өөрөөсөө хасахгүй. Энэ жишээнд өмнөх J-г
дараагийн I болгон авч, **үнэлгээний хоёр огнооны хооронд actual sales consumption=0**
гэж үзсэн. Demand нь shortage target; modeled actual sales биш. Олон өдрийн
борлуулалттай бүрэн inventory simulation хийх бол consumption/state equation-ийг
загварт нэмэх шаардлагатай. Энэ жишээ тэр dynamics-ийг далдуур тааж оруулаагүй.

Хэрэглэгчийн өгсөн gate 0/1 байна; илгээгч эсвэл хүлээн авагчийн gate=0 бол
transfer upper bound=0. Fractional gate нь infeasible. Self-transfer explicit 0.
Аудитын бодит баталгааг хөдөлгүүр өөрөө үүсгэхгүй; application түүний эх үүсвэрийг батална.

Independent enumerator-оор бүх dispatch quantity-г шалгасан. Дараах хувилбарууд
мөн тесттэй: receiver capacity=5 → transfer=5; аль нэг gate=0 → transfer=0;
lead=2, horizon-оос хойш ирэх → transfer=0; өмнөх shipment-ийг boundary-аас зөв өдөр нь нэмэх.

## Assortment — зураг дээрх томьёог яг хадгалсан

Хэрэглэгч **зургийн томьёог яг хэвээр** хэрэгжүүлэхийг сонгосон. Орлуулалтын нийлбэрт
receiver-ийн y_i нөхцөл нэмж оруулаагүй:

```text
d_i = y_i*(base_i + eta_i*log(1+f_i)) + sum_{j != i} rho_ij*base_j*(1-y_j)
sales_i = min(d_i, available_i)
profit = sum_i margin_i*sales_i - setup_i*y_i
```

Нэг салбар, гурван SKU. Shelf capacity=3.5.

| SKU индекс | base | eta | margin | setup | width | available | Fmax |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 | 4 | 2 | 4 | 2 | 1 | 7 | 3 |
| 1 | 3 | 1.5 | 6 | 3 | 1.5 | 5 | 2 |
| 2 | 5 | 1 | 3 | 1 | 1 | 6 | 3 |

rho-ийн мөр i нь орлуулсан эрэлтийг авах SKU, багана j нь сонгогдоогүй эх SKU:

```text
       j=0   j=1   j=2
i=0    0     .2    .1
i=1    .1    0     .2
i=2    .15   .1    0
```

Диагональ 0 нь `j != i` нийлбэрийг төлөөлнө. rho≥0, багана бүрийн нийлбэр≤1 нөхцөлтэй.
rho/eta-г энэ жишээ сургахгүй; тогтмол оролтоор өгсөн.

### Exact finite-level хувиргалт

k=0,1,2,3 бүрт binary level[i,k] тодорхойлно:

```text
sum_k level[i,k] = 1
y_i = 1 - level[i,0]
f_i = sum_k k*level[i,k]
y_i <= f_i <= Fmax_i*y_i
y_i*log(1+f_i) = sum_k log(1+k)*level[i,k]
```

`log(1+k)` нь index binding-ийн дараа тогтмол. Энэ нь interpolation approximation
биш, зөвшөөрсөн finite integer facings-ийн бүх утга дээр эквивалент.
Нөөцийн хязгаарыг `sales=demand-positive_part(demand-available)` equality-гаар өгсөн.
Дэмждэг Fmax-аас том утга хэрэглэх бол level axis-ийг мөн тэлнэ.
Энэ жишээний demand/sales upper=20 нь өгсөн параметрүүдийн боломжит дээд эрэлтээс их;
өөр өгөгдөлд finite bounds-ийг дахин зөв тогтоох шаардлагатай.

Үр дүн: **selected=[1,1,1], facings=[1,1,1]**, ашиг **56.8629436112**.
Shelf хэрэглээ=1+1.5+1=3.5. Борлуулалт≈[5.386294,4.039721,5.693147].
Анхны nonlinear томьёог integer f-ийн бүх боломж дээр шууд тооцсон тусдаа
enumerator-той objective, selected/facings, demand, capped sales-ийг тулгасан.

### Literal томьёоны тайлбарлах шаардлагатай үр дагавар

Shelf capacity=0 гэсэн тусдаа stress case-д selected=facings=[0,0,0] боловч
substitution demand=[1.1,1.4,.9], profit=15.5 гарна. Энэ нь solver-ийн алдаа биш:
зураг дээрх томьёо unselected receiver-д substitution зөвшөөрч байгаа үр дагавар.
Хэрэглэгчийн зааврын дагуу selected-only gate нэмээгүй. Энэ stress case-ийг
regression тестээр хадгалсан бөгөөд бодит бизнесийн зөв тайлбар гэж батлаагүй.

## Баталгаажуулалтын хүрээ

Шинэ жишээнүүдийг CLI болон HTTP job/worker урсгалаар шалгана. Full result нь Job API-д
хадгалагдана; solution нь source input мөрүүдтэй нэг-нэгээр таарахгүй тул Data API-ийн
row persistence нь indexed result mapping биш. Production transfer/order илгээхгүй.
Эдгээр нь жижиг finite загвар; production өгөгдөл, олон SKU/салбарын ачаалал,
substitution coefficient-ийн үнэлгээ, аудитын интеграци тусдаа ажил хэвээр.
