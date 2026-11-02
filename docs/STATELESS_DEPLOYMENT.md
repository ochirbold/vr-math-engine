# Хадгалалтгүй Compute API deployment

2026-11-02. Үндсэн deployment нь зөвхөн compute сервис.

```sh
# SERVICE_TOKEN-ийг хувийн утгаар environment эсвэл .env-д тохируулсан байна.
docker compose up --build -d
```

`POST http://127.0.0.1:8102/v1/executions` рүү model, dataset, parameters
өгнө. `X-Service-Token` header шаардлагатай. Prediction нь `/v1/predictions`.
Хүсэлт, үр дүнг application DB эсвэл snapshot файлд хадгалахгүй. Compute-д
SQLite volume холбохгүй. Дуудагч систем хүсэлт/үр дүн, retry, түүхээ хариуцна.

Энэ нь диск огт ашиглахгүй гэсэн үг биш: image, Python dependency, Docker
runtime/log зай эзэлнэ. Compose json-file log-ийг сервис бүрт 10 MB, 3 файл
болгон эргэлдүүлнэ. Хостын бусад log/storage policy тусдаа үйлчилнэ.

Шууд дуудлага синхрон; process wall timeout 90 секунд. Нэг compute slot
завгүй бол 429 өгнө. Restart/тасалдлын үед in-flight хүсэлтийг сэргээх queue
байхгүй. Нэг token, localhost port, HTTPS gateway-ийн шаардлага хэвээр.

## Сонголтот job платформ

```sh
docker compose --profile jobs up --build -d
```

Энэ үед compute дээр jobs/data/worker нэмэгдэнэ. Тэд snapshot, job/result,
retry/lease хадгалахад `job-data`, `snapshot-data` volume дахь SQLite ашиглана.
Retention автомат цэвэрлэгээ одоогоор байхгүй; зайг оператор удирдана.
`persist=false` нь job/snapshot хадгалалтыг бүрэн унтраах тохиргоо биш.

## Өмнөх бүтэн стекээс шилжих

Өмнө нь ажиллаж байсан jobs/data/worker нь profile нэмснээр өөрөө зогсохгүй.
Ажиллаж буй job-уудыг дуусгаж, зөвшөөрөгдсөн maintenance үед:

```sh
docker compose --profile jobs stop worker jobs data
docker compose up --build -d compute
```

Хуучин volume болон DB-г автоматаар устгахгүй; backup/retention шийдвэрийн
дараа оператор тусад нь удирдана. Энэ өөрчлөлт ямар нэг өгөгдөл устгахгүй.

## Шалгалтын хүрээ

Compose profile тохиргоог source түвшинд өөрчилсөн. Docker CLI энэ орчинд
байхгүй тул image build болон profile-ийн бодит startup target host дээр
баталгаажуулах шаардлагатай. Stateless execution-ийг хоосон working directory,
DB path-ууд тохируулсан ч DB үүсэхгүй байх integration шалгалтаар хамгаална.

Өмнөх SERVER_READINESS тайлан нь jobs стек оролцсон v0.5.0 аудитын түүхэн
баримт; энэ заавар анхдагч deployment-ийн сонголтыг шинэчилнэ.

Шалгалтын дүн: **202 passed in 72.50s**. Compute endpoint-ийн гүйцэтгэлийг
хоосон working directory-д ажиллуулахад DB эсвэл output файл үүсээгүй.
HTTP/job regression давсан; Docker build/run баталгаажаагүй хэвээр.
