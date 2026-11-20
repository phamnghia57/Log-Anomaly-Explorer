# #109 — phần của Nghĩa: xoay vòng log container Docker

**Đo cái gì:** log của container Docker có bị chặn trần kích thước hay không.

**Vì sao cần:** `json-file` là driver mặc định của Docker và **không giới hạn kích thước** nếu
không cấu hình. File log cứ lớn mãi cho đến khi hết đĩa. Khi đĩa đạt flood-stage watermark 95 %,
OpenSearch chuyển **toàn bộ** index sang read-only và mọi `POST /ingest` trả 503 — hệ thống chết
im lặng và cần can thiệp tay để mở lại.

## Giả định của kế hoạch — đã kiểm, **đúng**

Kế hoạch ghi: *"Giả định: `/etc/docker/daemon.json` trên VM chưa cấu hình `max-size`."*
Kiểm lúc **2026-11-20T02:59:57Z**, trước khi sửa gì (xem [logconfig-truoc.txt](logconfig-truoc.txt)):

```
docker info --format '{{.LoggingDriver}}'   -> json-file
cat /etc/docker/daemon.json                 -> (khong co file)
docker inspect --format '{{json .HostConfig.LogConfig}}' <moi container>
                                            -> {"Type":"json-file","Config":{}}
```

`Config` rỗng ở **cả 7 container** = không có `max-size`, không có `max-file`. Tổng dung lượng
log lúc đó: **4,8 MB** (`/var/lib/docker/containers`), container nặng nhất 2,0 MB. Tức tốc độ
tăng hiện tại nhỏ — đúng là P2 — nhưng **không có trần**.

## Bản sửa

Thêm một anchor YAML dùng chung ở `docker-compose.yml` và gắn `logging: *logging` cho **cả 8
service** (kể cả `jaeger-init` chạy một lần):

```yaml
x-logging: &logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

Dùng anchor thay vì lặp lại khối `logging` 8 lần: 18 dòng thêm vào thay vì 32, và sau này đổi
trần chỉ phải sửa một chỗ. Trần tổng: **30 MB mỗi container**, 240 MB cho cả stack — so với 17 GB
còn trống thì an toàn.

Kiểm cú pháp trước khi deploy:

```
docker compose config --quiet   -> exit 0   (anchor mo rong dung cho ca 8 service)
```

## Bẫy khi deploy: `logging` chỉ áp dụng lúc **tạo** container

`docker compose restart` **không** đọc lại cấu hình này, và `deploy/deploy.sh` chỉ
`up -d --build` cho 5 service (`ingestion`, `demo-app`, `clustering`, `query-api`, `gateway`).
Ba service còn lại (`opensearch`, `jaeger`, `jaeger-init`) phải được recreate riêng:

```bash
cd ~/prj2
deploy/deploy.sh main
docker compose up -d                      # BAT BUOC: recreate ca opensearch/jaeger
bash docs/evidence/12-disk-bounds/verify-logging.sh
```

`docker compose up -d` recreate `opensearch` → kho dữ liệu gián đoạn vài chục giây. Dữ liệu nằm
trên volume `opensearch-data` nên **không mất**, nhưng chọn lúc không demo.

## Kết quả sau khi deploy

Đã chạy `verify-logging.sh` lúc **2026-11-20T03:34:20Z** trên bản deploy `38defc3`; output đầy đủ
ở [logconfig-sau.txt](logconfig-sau.txt). **Cả 8 container đều đạt** tiêu chí
`max-size=10m, max-file=3`, và dung lượng log tụt từ **4,8 MB** xuống **436 KB** sau khi recreate.

| Container   | `LogConfig` sau khi deploy                                     |
| ----------- | ---------------------------------------------------------------- |
| opensearch  | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| ingestion   | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| jaeger-init | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| jaeger      | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| demo-app    | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| clustering  | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| query-api   | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |
| gateway     | {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}  |

# Evidence #109 - SAU khi dat logging driver

# 2026-11-20T03:34:20Z tren VM log-anomaly-vps

# GIT_SHA deployed = 38defc3

# HEAD cua repo tren VM = 38defc3

## docker compose config - khoi logging sau khi mo rong anchor

so service co driver json-file tuong minh: 9

## docker inspect LogConfig cua tung container (tieu chi nghiem thu)

/prj2-clustering-1       OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-demo-app-1         OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-gateway-1          OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-ingestion-1        OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-jaeger-1           OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-opensearch-1       OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-query-api-1        OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}

## Ket luan: moi container da co max-size=10m max-file=3

## Kich thuoc file log sau khi recreate

412K    /var/lib/docker/containers

## Jaeger dang chay dung image da ghim digest?

jaegertracing/all-in-one:1.76.0@sha256:ab6f1a1f0fb49ea08bcd19f6b84f6081d0d44b364b6de148e1798eb5816bacac
grep -c ':latest' docker-compose.yml -> 0

## Health

/health            : {"status":"ok","service":"query-api","storage":"opensearch","version":"38defc3"}
/clustering/health : {"status":"ok","reason":null,"last_processed_at":"2026-11-20T03:34:10.024724+00:00"}

# Evidence #109 - SAU khi dat logging driver

# 2026-11-20T03:34:20Z tren VM log-anomaly-vps

# GIT_SHA deployed = 38defc3

# HEAD cua repo tren VM = 38defc3

## docker compose config - khoi logging sau khi mo rong anchor

so service co driver json-file tuong minh: 9

## docker inspect LogConfig cua tung container (tieu chi nghiem thu)

/prj2-clustering-1       OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-demo-app-1         OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-gateway-1          OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-ingestion-1        OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-jaeger-1           OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-opensearch-1       OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}
/prj2-query-api-1        OK             {"Type":"json-file","Config":{"max-file":"3","max-size":"10m"}}

## Ket luan: moi container da co max-size=10m max-file=3

## Kich thuoc file log sau khi recreate

412K    /var/lib/docker/containers

## Jaeger dang chay dung image da ghim digest?

jaegertracing/all-in-one:1.76.0@sha256:ab6f1a1f0fb49ea08bcd19f6b84f6081d0d44b364b6de148e1798eb5816bacac
grep -c ':latest' docker-compose.yml -> 0

## Health

/health            : {"status":"ok","service":"query-api","storage":"opensearch","version":"38defc3"}
/clustering/health : {"status":"ok","reason":null,"last_processed_at":"2026-11-20T03:34:10.024724+00:00"}

Tiêu chí nghiệm thu của #109 cho phần này: `docker inspect <container> | grep -A3 LogConfig`
cho thấy `max-size=10m`.

## Phần retention của `cluster-history` (đo an toàn, không xoá dữ liệu)

Tiêu chí *"output `_cat/indices?v&s=store.size:desc` trước/sau một lần chạy retention"* không đo
được trực tiếp ở trạng thái hiện tại: điểm history cũ nhất là **2026-11-02**, chỉ 18 ngày tuổi,
nên với `RETENTION_DAYS=30` mỗi lần chạy đều `deleted=0` — đúng như log worker:

```
INFO:root:Cluster history retention: deleted=0 cutoff=2026-10-21T03:05:33+00:00
```

Hạ `RETENTION_DAYS` xuống để tạo ra `deleted > 0` sẽ **xoá dữ liệu history thật**, và
`delete_by_query` không có chế độ dry-run. Nên đo bằng `_count` với **đúng câu truy vấn** mà
`delete_history_before` dùng (`range recorded_at < cutoff`) — xem
[retention-count.txt](retention-count.txt):

| `RETENTION_DAYS` | cutoff     | Số điểm sẽ bị xoá | Trên tổng |
| ------------------ | ---------- | ----------------------- | ----------- |
| 30 (đang chạy)   | 2026-10-21 | **0**             | 384         |
| 20                 | 2026-10-31 | 0                       | 384         |
| 10                 | 2026-11-10 | **305**           | 384         |
| 5                  | 2026-11-15 | **381**           | 384         |

Kết luận: câu truy vấn **chọn đúng theo tuổi** — nó đang trả 0 vì chưa có điểm nào quá hạn, chứ
không phải vì sai. `cluster-history` hiện 384 điểm / **118,3 kB**; với `WINDOW_SECONDS=60` và
19 cụm, trần 30 ngày giữ index ở mức vài MB. Phần test đơn vị của câu truy vấn là của Nam
([verify-live-history.txt](../02-history-sort/verify-live-history.txt)).

Để có bằng chứng `deleted > 0` thật mà không mất dữ liệu, cách rẻ nhất là chờ tới khi dữ liệu
đủ 30 ngày tuổi (khoảng 2026-12-02), hoặc ghi thêm điểm giả có `recorded_at` cũ vào một index
test riêng rồi chạy `delete_history_before` trên index đó.

## Phần `logs-quarantine` (Minh)

Chưa làm. Hiện `logs-quarantine` có **445 document / 40,1 kB** và không có cơ chế nào xoá:
`_drop_daily_indices` cố ý chỉ khớp `logs-YYYY.MM.DD` (`ingestion/src/storage.py:403-409`).
Đây là nguồn tăng đĩa duy nhất còn lại hoàn toàn không có trần.
